"""Public accounting service: versioned books, cells, staging and durable commands."""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from uuid import uuid4

from sqlalchemy import case, delete, exists, func, insert, or_, select, update

from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.auth import Principal
from cafe_fin.core.contracts import BookSummaryDTO, MappedBookMetricDTO
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import (
    ImportAttemptService,
    attempts,
    claims,
    manifests,
    visibility_predicate,
)
from cafe_fin.core.jobs import JOBS
from cafe_fin.core.time import utc_now

from . import schema as s
from .validation import check_row_budget, fingerprint, normalize_schema, normalize_value

BUSY = {"PARSING", "VALIDATING", "COMMITTING", "UPLOADED"}
ATTEMPTS = ImportAttemptService()
DEFAULT_PROFILE = {
    "encoding": "utf-8-sig",
    "delimiter": ",",
    "header_row": 1,
    "decimal_separator": ".",
    "thousands_separator": "",
    "skip_blank": True,
    "hidden_rows": "include",
    "merged_cells": "reject",
}


def identity():
    return str(uuid4())


def page_result(items, total, page, size):
    return dict(items=items, total=total, page=page, page_size=size)


def check_page(page, size):
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 500:
        raise CoreError("INVALID_PAGE", "Trang cần dương và kích thước trang tối đa 500.")


def visible():
    return visibility_predicate(s.entries.c.import_attempt_id)


def _book(conn, book_id):
    row = conn.execute(select(s.books).where(s.books.c.id == book_id)).mappings().first()
    if row is None:
        raise CoreError("BOOK_NOT_FOUND", "Không tìm thấy sổ.", 404)
    return dict(row)


def book_dto(book):
    return {k: v for k, v in book.items() if not k.endswith("_json")} | {
        "columns": json.loads(book["columns_json"]),
        "semantics": json.loads(book["semantics_json"]),
    }


def _batch(conn, batch_id, actor=None):
    row = conn.execute(select(s.batches).where(s.batches.c.id == batch_id)).mappings().first()
    if row is None:
        raise CoreError("IMPORT_NOT_FOUND", "Không tìm thấy lượt nhập.", 404)
    if actor and row.actor_id != actor.id and actor.role != "admin":
        raise CoreError("PERMISSION_DENIED", "Lượt nhập thuộc tài khoản khác.", 403)
    result = dict(row)
    if result["state"] in BUSY and result["job_id"]:
        state = conn.execute(
            select(JOBS.c.state).where(JOBS.c.id == result["job_id"])
        ).scalar_one_or_none()
        if state in ("FAILED", "CANCELLED", "RECOVERABLE"):
            result["state"] = state
    return result


def stage_dto(row):
    return {
        k: row[k]
        for k in ("row_id", "source_sheet", "source_row", "revision", "duplicate_count", "decision")
    } | {
        "sheet_name": row["sheet_name"],
        "raw_values": json.loads(row["raw_json"]),
        "edited_values": json.loads(row["edited_json"]),
        "typed_values": json.loads(row["typed_json"]),
        "issues": json.loads(row["issues_json"]),
        "formulas": json.loads(row["formulas_json"]),
        "imported": bool(row["target_id"]),
        "target_id": row["target_id"],
    }


def row_dto(row):
    return {k: v for k, v in dict(row).items() if not k.endswith("_json")} | {
        "values": json.loads(row["values_json"]),
        "formulas": json.loads(row["formulas_json"]),
        "issues": [],
    }


def published_target():
    return (
        select(claims.c.target_id)
        .join(attempts, attempts.c.id == claims.c.attempt_id)
        .where(
            claims.c.job_id == s.stage.c.batch_id,
            claims.c.source_row_id == s.stage.c.row_id,
            attempts.c.state == "PUBLISHED",
        )
        .correlate(s.stage)
        .scalar_subquery()
    )


def effective_decision():
    default = (
        select(s.batches.c.duplicate_default)
        .where(s.batches.c.id == s.stage.c.batch_id)
        .correlate(s.stage)
        .scalar_subquery()
    )
    return func.coalesce(s.stage.c.decision, case((s.stage.c.duplicate_count > 0, default)))


def _idle(batch, conn=None):
    if batch["state"] in BUSY:
        raise CoreError(
            "IMPORT_BUSY",
            "Lượt nhập đang xử lý revision đã khóa. Chờ hoàn tất hoặc hủy rồi tiếp tục.",
            409,
        )
    if conn is not None and batch.get("manifest_id"):
        manifest = conn.execute(
            select(manifests.c.state).where(manifests.c.id == batch["manifest_id"])
        ).scalar_one()
        state = conn.execute(
            select(attempts.c.state).where(attempts.c.id == batch.get("attempt_id"))
        ).scalar_one_or_none()
        if manifest == "BUILDING" or state != "PUBLISHED":
            raise CoreError(
                "IMPORT_ATTEMPT_LOCKED",
                "Snapshot/pending của lượt xác nhận còn được giữ. Tiếp tục lượt đó trước khi sửa hoặc xác nhận mới.",
                409,
            )


def _require_parse_complete(conn, batch_id):
    latest = conn.execute(
        select(JOBS.c.state)
        .select_from(s.tasks.outerjoin(JOBS, JOBS.c.id == s.tasks.c.job_id))
        .where(s.tasks.c.entity_id == batch_id, s.tasks.c.kind == "accounting.parse")
        .order_by(s.tasks.c.created_at.desc(), s.tasks.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest != "COMPLETED":
        raise CoreError(
            "PARSE_INCOMPLETE",
            "Nguồn chưa parse hoàn tất. Tiếp tục hoặc sửa profile parser trước khi validate/xác nhận; không coi phần chưa đọc là trống.",
            409,
        )


def _audit(conn, actor, entity, entity_id, action, before=None, after=None):
    return AuditService.record(
        conn,
        actor=actor.id,
        entity="accounting_" + entity,
        entity_id=entity_id,
        action=action,
        before=before,
        after=after,
    )


def _touch_data(conn, book_id):
    conn.execute(
        update(s.books)
        .where(s.books.c.id == book_id)
        .values(data_revision=s.books.c.data_revision + 1, updated_at=utc_now())
    )


def _queue(conn, actor, kind, entity_id, payload):
    task_id = identity()
    conn.execute(
        insert(s.tasks).values(
            id=task_id,
            kind=kind,
            entity_id=entity_id,
            actor_id=actor.id,
            actor_json=canonical_json(actor.public()),
            payload_json=canonical_json(payload),
            created_at=utc_now(),
        )
    )
    if kind != "accounting.export":
        conn.execute(
            update(s.batches).where(s.batches.c.id == entity_id).values(active_task_id=task_id)
        )
    return task_id


def scaled_cells(row_id, book_id, values, columns):
    result = []
    for col in columns:
        value = values.get(col["id"])
        scaled = None
        if value is not None and col["kind"] in ("integer", "decimal", "money", "formula"):
            with localcontext() as ctx:
                ctx.prec = 80
                scaled = int(Decimal(value) * 10 ** col["scale"])
        result.append(
            dict(
                row_id=row_id,
                column_id=col["id"],
                book_id=book_id,
                text_value=value,
                scaled_value=scaled,
            )
        )
    return result


class AccountingService:
    def __init__(self, runtime):
        self.rt = runtime

    def authorize(self, actor, permission="accounting.write"):
        return lambda conn: self.rt.auth.authorize(conn, actor, permission)

    def write(
        self,
        actor,
        action,
        key,
        payload,
        operation,
        permission="accounting.write",
        *,
        referenced_file_id=None,
    ):
        def authorize(conn):
            current = self.rt.auth.authorize(conn, actor, permission)
            if referenced_file_id is not None:
                self.rt.files.require_owner_or_admin(conn, current, referenced_file_id)

        return self.rt.writer.execute(
            actor.id,
            "accounting." + action,
            key,
            payload,
            operation,
            authorize=authorize,
        )

    def dispatch(self):
        # Durable outbox covers death after a command commits but before JobService.submit.
        with self.rt.reader() as conn:
            pending = (
                conn.execute(
                    select(s.tasks)
                    .where(s.tasks.c.job_id.is_(None), s.tasks.c.dispatch_error.is_(None))
                    .limit(100)
                )
                .mappings()
                .all()
            )
        for task in pending:
            actor = Principal(
                **(
                    json.loads(task.actor_json)
                    | {"permissions": tuple(json.loads(task.actor_json)["permissions"])}
                )
            )
            try:
                job = self.rt.jobs.submit(
                    actor.id,
                    task.kind,
                    {"task_id": task.id},
                    "accounting-task:" + task.id,
                    authorize=self.authorize(actor),
                )
            except CoreError as exc:
                if exc.code not in ("SESSION_EXPIRED", "PERMISSION_DENIED"):
                    raise
                error_code = exc.code

                def blocked(conn):
                    conn.execute(
                        update(s.tasks)
                        .where(s.tasks.c.id == task.id)
                        .values(dispatch_error=error_code)
                    )
                    if task.kind != "accounting.export":
                        conn.execute(
                            update(s.batches)
                            .where(
                                s.batches.c.id == task.entity_id,
                                s.batches.c.active_task_id == task.id,
                            )
                            .values(state="FAILED", error_code=error_code)
                        )

                self.rt.writer.run(blocked)
                continue

            def attach(conn):
                conn.execute(
                    update(s.tasks).where(s.tasks.c.id == task.id).values(job_id=job["job_id"])
                )
                table = s.exports if task.kind == "accounting.export" else s.batches
                predicate = [table.c.id == task.entity_id]
                if task.kind != "accounting.export":
                    predicate.append(table.c.active_task_id == task.id)
                conn.execute(update(table).where(*predicate).values(job_id=job["job_id"]))

            self.rt.writer.run(attach)

    def get_books(self, actor, page=1, page_size=100):
        actor.require("accounting.read")
        check_page(page, page_size)
        with self.rt.reader() as conn:
            total = conn.execute(select(func.count()).select_from(s.books)).scalar_one()
            rows = conn.execute(
                select(s.books)
                .order_by(s.books.c.created_at, s.books.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return page_result([book_dto(dict(r)) for r in rows], total, page, page_size)

    def create_book(self, actor, name, columns, semantics, request_key):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise CoreError("BOOK_NAME_INVALID", "Tên sổ cần từ 1 đến 120 ký tự.")
        columns, semantics = normalize_schema(columns, semantics)

        def op(conn):
            book_id, now = identity(), utc_now()
            data = dict(
                id=book_id,
                name=name.strip(),
                version=1,
                schema_revision=1,
                data_revision=1,
                next_logical_row=1,
                columns_json=canonical_json(columns),
                semantics_json=canonical_json(semantics),
                created_by=actor.id,
                created_at=now,
                updated_at=now,
            )
            conn.execute(insert(s.books).values(**data))
            conn.execute(
                insert(s.schemas).values(
                    book_id=book_id,
                    revision=1,
                    columns_json=data["columns_json"],
                    semantics_json=data["semantics_json"],
                    created_by=actor.id,
                    created_at=now,
                )
            )
            result = book_dto(data)
            _audit(conn, actor, "book", book_id, "create", after=result)
            return result

        return self.write(
            actor,
            "books.create",
            request_key,
            dict(name=name, columns=columns, semantics=semantics),
            op,
            "accounting.configure",
        )

    def update_schema(self, actor, book_id, expected_version, columns, semantics, request_key):
        def op(conn):
            old = _book(conn, book_id)
            version = require_version(old["version"], expected_version)
            retained = conn.execute(
                select(s.batches.c.id)
                .select_from(
                    s.batches.join(manifests, manifests.c.id == s.batches.c.manifest_id).outerjoin(
                        attempts, attempts.c.id == s.batches.c.attempt_id
                    )
                )
                .where(
                    s.batches.c.book_id == book_id,
                    or_(
                        manifests.c.state == "BUILDING",
                        attempts.c.id.is_(None),
                        attempts.c.state != "PUBLISHED",
                    ),
                )
                .limit(1)
            ).first()
            if retained:
                raise CoreError(
                    "BOOK_IMPORT_LOCKED",
                    "Sổ còn snapshot hoặc attempt chưa công bố; hoàn tất/tiếp tục lượt nhập trước khi đổi schema, kể cả đổi tên.",
                    409,
                )
            previous = json.loads(old["columns_json"])
            configured, meaning = normalize_schema(columns, semantics, previous)
            occupied = conn.execute(
                select(s.entries.c.id).where(s.entries.c.book_id == book_id).limit(1)
            ).first()
            staged = conn.execute(
                select(s.batches.c.id).where(s.batches.c.book_id == book_id).limit(1)
            ).first()
            if occupied or staged:
                current = {c["id"]: c for c in configured}
                for col in previous:
                    new = current.get(col["id"])
                    if new is None or any(
                        new.get(k) != col.get(k)
                        for k in (
                            "kind",
                            "scale",
                            "precision",
                            "required",
                            "validation",
                            "choices",
                            "formula",
                        )
                    ):
                        raise CoreError(
                            "SCHEMA_DATA_INCOMPATIBLE",
                            "Sổ có dữ liệu: không xóa/đổi kiểu hoặc validation. Tạo sổ mới hoặc migration dữ liệu đã kiểm.",
                            409,
                        )
                if any(
                    c["id"] not in {x["id"] for x in previous}
                    and (c.get("required") or c["kind"] == "formula")
                    for c in configured
                ):
                    raise CoreError(
                        "SCHEMA_DATA_INCOMPATIBLE",
                        "Cột mới trong sổ có dữ liệu phải nullable và không có công thức.",
                        409,
                    )
            revised = old | dict(
                version=version,
                schema_revision=old["schema_revision"] + 1,
                columns_json=canonical_json(configured),
                semantics_json=canonical_json(meaning),
                updated_at=utc_now(),
            )
            conn.execute(update(s.books).where(s.books.c.id == book_id).values(**revised))
            conn.execute(
                insert(s.schemas).values(
                    book_id=book_id,
                    revision=revised["schema_revision"],
                    columns_json=revised["columns_json"],
                    semantics_json=revised["semantics_json"],
                    created_by=actor.id,
                    created_at=utc_now(),
                )
            )
            _audit(conn, actor, "book", book_id, "schema", book_dto(old), book_dto(revised))
            return book_dto(revised)

        return self.write(
            actor,
            "books.schema",
            request_key,
            dict(
                book_id=book_id,
                expected_version=expected_version,
                columns=columns,
                semantics=semantics,
            ),
            op,
            "accounting.configure",
        )

    def _entry(self, conn, row_id, *, include_deleted=False):
        conditions = [s.entries.c.id == row_id, visible()]
        if not include_deleted:
            conditions.append(s.entries.c.deleted_at.is_(None))
        row = conn.execute(select(s.entries).where(*conditions)).mappings().first()
        if row is None:
            raise CoreError("ROW_NOT_FOUND", "Không tìm thấy dòng đã công bố.", 404)
        return dict(row)

    def normalize_row(
        self,
        conn,
        book,
        values,
        *,
        profile=None,
        metadata=None,
        formulas=None,
        resolver=None,
        current_row=None,
        cancelled=None,
    ):
        from .formulas import ENGINE_VERSION, FormulaEngine, FormulaError, LiteralCell

        columns = json.loads(book["columns_json"])
        check_row_budget(values)
        if not columns:
            raise CoreError(
                "BOOK_SCHEMA_REQUIRED", "Cấu hình cột sổ trước khi nhập hoặc thêm dòng.", 422
            )
        if set(values) - {c["id"] for c in columns}:
            raise CoreError("COLUMN_UNKNOWN", "Dữ liệu chứa ID cột không thuộc schema.")
        typed, errors, formula_info = {}, [], {}
        remaining_formula_cost = 100_000
        profile, metadata, formulas = profile or {}, metadata or {}, formulas or {}

        def resolve(reference, prefer_external=True):
            if resolver is not None and prefer_external:
                return resolver(reference)
            match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", reference)
            index = 0
            for char in match[1]:
                index = index * 26 + ord(char) - 64
            column = next((c for c in columns if c["logical_index"] == index - 1), None)
            if column is None:
                raise FormulaError("FORMULA_REFERENCE", "Tham chiếu cột không tồn tại.")
            if current_row == int(match[2]):
                v = values.get(column["id"])
                if v is None and column.get("formula"):
                    v = column["formula"].replace("{row}", str(current_row))
            else:
                row = conn.execute(
                    select(s.entries.c.values_json).where(
                        s.entries.c.book_id == book["id"],
                        s.entries.c.logical_row == int(match[2]),
                        s.entries.c.deleted_at.is_(None),
                        visible(),
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise FormulaError(
                        "FORMULA_REFERENCE",
                        "Dòng chưa có hoặc đã xóa; không coi ô chưa tải là trống.",
                    )
                v = json.loads(row).get(column["id"])
            if column["kind"] in ("text", "choice", "date"):
                return LiteralCell(v)
            if v is not None and not str(v).startswith("="):
                normalized, _ = normalize_value(v, column, profile)
                return Decimal(normalized) if normalized is not None else None
            return v

        for col in columns:
            key = col["id"]
            value = values.get(key)
            provenance = formulas.get(key)
            try:
                formula = col.get("formula") if col["kind"] == "formula" else None
                if provenance and provenance.get("formula_text"):
                    formula = provenance["formula_text"]
                if formula:
                    if current_row and "{row}" in formula:
                        formula = formula.replace("{row}", str(current_row))
                    if remaining_formula_cost <= 0:
                        raise FormulaError(
                            "FORMULA_COST", "Tổng công thức của dòng vượt ngân sách tính toán."
                        )
                    engine = FormulaEngine(
                        resolve if provenance else lambda ref: resolve(ref, False),
                        max_cost=remaining_formula_cost,
                        cancelled=cancelled,
                    )
                    try:
                        result = engine.evaluate(formula)
                    finally:
                        remaining_formula_cost -= engine.cost
                    if isinstance(result, Decimal):
                        value = result
                    else:
                        value = result
                    formula_info[key] = dict(
                        formula_text=formula,
                        cached_value=provenance.get("cached_value") if provenance else None,
                        calculated_value=format(value, "f")
                        if isinstance(value, Decimal)
                        else value,
                        calculation_status="supported_calculated",
                        engine=ENGINE_VERSION,
                        schema_revision=book["schema_revision"],
                        dependency_revision=book["data_revision"],
                        dependencies=sorted(engine.dependencies),
                    )
                elif provenance:
                    raise CoreError(
                        "FORMULA_CACHE_NOT_AUTHORITATIVE",
                        "Cache công thức chưa được tính lại; cần nhập giá trị có provenance.",
                    )
                date_meta = metadata.get("date_cells", {}).get(key)
                if formula:
                    # Cache metadata describes the original cached value, not this
                    # engine result. In particular iso_date must not beat serial2.
                    date_meta = (
                        {
                            "epoch": (date_meta or {}).get("epoch", metadata.get("epoch", "1900")),
                            "excel_serial": format(value, "f"),
                        }
                        if col["kind"] == "date" and isinstance(value, Decimal)
                        else None
                    )
                typed[key], _ = normalize_value(value, col, profile, date_meta)
                if formula and col["kind"] == "date":
                    formula_info[key]["calculated_value"] = typed[key]
            except (CoreError, FormulaError) as exc:
                typed[key] = None
                errors.append(
                    dict(
                        column_id=key,
                        code=exc.code,
                        message=str(getattr(exc, "message", "Công thức không hợp lệ.")),
                        severity="error",
                        suggestion="Sửa giá trị hoặc cấu hình rồi kiểm tra lại.",
                        raw_value=str(value)[:256],
                    )
                )
                if formula:
                    formula_info[key] = dict(
                        formula_text=formula,
                        cached_value=provenance.get("cached_value") if provenance else None,
                        calculated_value=None,
                        calculation_status="circular"
                        if "CIRCULAR" in exc.code
                        else "external_reference"
                        if "EXTERNAL" in exc.code
                        else "unsupported"
                        if "UNSUPPORTED" in exc.code
                        else "calculation_error",
                        engine=ENGINE_VERSION,
                        error_code=exc.code,
                    )
        return typed, errors, formula_info

    def create_row(self, actor, book_id, values, request_key):
        def op(conn):
            book = _book(conn, book_id)
            row_id, now = identity(), utc_now()
            typed, errors, formulas = self.normalize_row(
                conn, book, values, current_row=book["next_logical_row"]
            )
            if errors:
                raise CoreError(
                    "ROW_INVALID", "Kiểm tra lỗi tại ô.", 422, details={"issues": errors}
                )
            semantic = json.loads(book["semantics_json"])
            data = dict(
                id=row_id,
                book_id=book_id,
                version=1,
                logical_row=book["next_logical_row"],
                schema_revision=book["schema_revision"],
                values_json=canonical_json(typed),
                formulas_json=canonical_json(formulas),
                fingerprint=fingerprint(typed),
                candidate_key=fingerprint(typed, semantic.get("duplicate_columns", [])),
                business_key=fingerprint(typed, semantic.get("business_key_columns", [])),
                created_by=actor.id,
                updated_by=actor.id,
                created_at=now,
                updated_at=now,
                deleted_at=None,
            )
            self._check_business_key(conn, book_id, data["business_key"], None, data["fingerprint"])
            conn.execute(insert(s.entries).values(**data))
            if json.loads(book["columns_json"]):
                conn.execute(
                    insert(s.cells),
                    scaled_cells(row_id, book_id, typed, json.loads(book["columns_json"])),
                )
            conn.execute(
                update(s.books)
                .where(s.books.c.id == book_id)
                .values(next_logical_row=book["next_logical_row"] + 1)
            )
            _touch_data(conn, book_id)
            _audit(conn, actor, "row", row_id, "create", after=row_dto(data))
            return row_dto(data)

        return self.write(
            actor, "rows.create", request_key, dict(book_id=book_id, values=values), op
        )

    @staticmethod
    def _check_business_key(conn, book_id, key, row_id, row_fingerprint):
        if (
            key
            and conn.execute(
                select(s.entries.c.id)
                .where(
                    s.entries.c.book_id == book_id,
                    s.entries.c.business_key == key,
                    s.entries.c.deleted_at.is_(None),
                    s.entries.c.id != (row_id or ""),
                    s.entries.c.fingerprint != row_fingerprint,
                    visible(),
                )
                .limit(1)
            ).first()
        ):
            raise CoreError(
                "BUSINESS_KEY_CONFLICT",
                "Khóa nghiệp vụ đã cấu hình có bản ghi khác. Không ghi đè tự động.",
                409,
            )

    def mutate_row(
        self, actor, row_id, expected_version, request_key, values=None, action="update"
    ):
        def op(conn):
            old = self._entry(conn, row_id, include_deleted=action == "restore")
            version = require_version(old["version"], expected_version)
            book = _book(conn, old["book_id"])
            revised = old | dict(version=version, updated_at=utc_now(), updated_by=actor.id)
            if action == "update":
                configured = {c["id"]: c for c in json.loads(book["columns_json"])}
                if any(k in configured and not configured[k].get("editable", True) for k in values):
                    raise CoreError(
                        "CELL_READ_ONLY", "Cột không cho phép sửa kết quả trực tiếp.", 403
                    )
                merged = json.loads(old["values_json"]) | values
                typed, errors, formulas = self.normalize_row(
                    conn, book, merged, current_row=old["logical_row"]
                )
                if errors:
                    raise CoreError(
                        "ROW_INVALID", "Kiểm tra lỗi tại ô.", 422, details={"issues": errors}
                    )
                semantic = json.loads(book["semantics_json"])
                preserved = json.loads(old["formulas_json"])
                for column, info in preserved.items():
                    if column in values and column not in formulas:
                        preserved[column] = info | {
                            "calculation_status": "manual_override",
                            "manual_value": typed.get(column),
                            "override_version": version,
                        }
                formulas = preserved | formulas
                revised.update(
                    values_json=canonical_json(typed),
                    formulas_json=canonical_json(formulas),
                    fingerprint=fingerprint(typed),
                    candidate_key=fingerprint(typed, semantic.get("duplicate_columns", [])),
                    business_key=fingerprint(typed, semantic.get("business_key_columns", [])),
                )
                self._check_business_key(
                    conn, book["id"], revised["business_key"], row_id, revised["fingerprint"]
                )
                conn.execute(delete(s.cells).where(s.cells.c.row_id == row_id))
                if json.loads(book["columns_json"]):
                    conn.execute(
                        insert(s.cells),
                        scaled_cells(row_id, book["id"], typed, json.loads(book["columns_json"])),
                    )
            elif action in ("delete", "restore"):
                revised["deleted_at"] = utc_now() if action == "delete" else None
                if action == "restore":
                    self._check_business_key(
                        conn, book["id"], revised["business_key"], row_id, revised["fingerprint"]
                    )
            else:
                raise CoreError("ACTION_INVALID", "Thao tác không được hỗ trợ.")
            conn.execute(update(s.entries).where(s.entries.c.id == row_id).values(**revised))
            _touch_data(conn, book["id"])
            _audit(conn, actor, "row", row_id, action, row_dto(old), row_dto(revised))
            return row_dto(revised)

        return self.write(
            actor,
            "rows." + action,
            request_key,
            dict(row_id=row_id, expected_version=expected_version, values=values),
            op,
            "accounting.restore" if action == "restore" else "accounting.write",
        )

    def list_rows(
        self, actor, book_id, page=1, page_size=200, search="", sort="", filters=None, deleted=False
    ):
        actor.require("accounting.read")
        check_page(page, page_size)
        with self.rt.reader() as conn:
            book = _book(conn, book_id)
            columns = {c["id"]: c for c in json.loads(book["columns_json"])}
            predicates = [s.entries.c.book_id == book_id, visible()]
            if not deleted:
                predicates.append(s.entries.c.deleted_at.is_(None))
            if search:
                predicates.append(s.entries.c.values_json.contains(search[:256], autoescape=True))
            for f in filters or []:
                if f.get("column_id") not in columns or f.get("op") not in (
                    "eq",
                    "contains",
                    "gte",
                    "lte",
                    "empty",
                ):
                    raise CoreError("FILTER_INVALID", "Cột hoặc toán tử lọc không được hỗ trợ.")
                col, op, val = columns[f["column_id"]], f["op"], f.get("value")
                cell_conditions = [
                    s.cells.c.row_id == s.entries.c.id,
                    s.cells.c.column_id == col["id"],
                ]
                if op == "empty":
                    condition = or_(s.cells.c.text_value.is_(None), s.cells.c.text_value == "")
                elif col["kind"] in ("integer", "decimal", "money", "formula") and op != "contains":
                    _, scaled = normalize_value(val, col)
                    condition = {
                        "eq": s.cells.c.scaled_value == scaled,
                        "gte": s.cells.c.scaled_value >= scaled,
                        "lte": s.cells.c.scaled_value <= scaled,
                    }[op]
                else:
                    text = str(val or "")
                    condition = {
                        "eq": s.cells.c.text_value == text,
                        "gte": s.cells.c.text_value >= text,
                        "lte": s.cells.c.text_value <= text,
                        "contains": s.cells.c.text_value.contains(text, autoescape=True),
                    }[op]
                predicates.append(exists(select(1).where(*cell_conditions, condition)))
            ordering = [s.entries.c.logical_row, s.entries.c.id]
            if sort:
                key, _, direction = sort.partition(":")
                if key not in columns or direction not in ("asc", "desc"):
                    raise CoreError("SORT_INVALID", "Cột hoặc chiều sắp xếp không được hỗ trợ.")
                field = (
                    s.cells.c.scaled_value
                    if columns[key]["kind"] in ("integer", "decimal", "money", "formula")
                    else s.cells.c.text_value
                )
                value = (
                    select(field)
                    .where(s.cells.c.row_id == s.entries.c.id, s.cells.c.column_id == key)
                    .scalar_subquery()
                )
                ordering = [value.desc() if direction == "desc" else value.asc(), s.entries.c.id]
            total = conn.execute(
                select(func.count()).select_from(s.entries).where(*predicates)
            ).scalar_one()
            rows = conn.execute(
                select(s.entries)
                .where(*predicates)
                .order_by(*ordering)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return page_result([row_dto(r) for r in rows], total, page, page_size) | {
                "data_revision": book["data_revision"],
                "schema_revision": book["schema_revision"],
            }

    def get_batch(self, actor, batch_id):
        actor.require("accounting.read")
        with self.rt.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            batch = _batch(conn, batch_id, actor)
            result = {k: v for k, v in batch.items() if not k.endswith("_json") and k != "actor_id"}
            result.update(
                profile=json.loads(batch["profile_json"]),
                mapping=json.loads(batch["mapping_json"]),
                source_manifest=json.loads(batch["source_manifest_json"]),
                counts=json.loads(batch["counts_json"]),
            )
            if batch["attempt_id"]:
                progress = ATTEMPTS.status(conn, batch["attempt_id"])
                result["counts"]["pending"] = progress["pending"]
                result["counts"]["staged_committed_rows"] = (
                    result["counts"].get("published_rows", 0) + progress["pending"]
                )
            if batch["job_id"]:
                row = (
                    conn.execute(select(JOBS).where(JOBS.c.id == batch["job_id"])).mappings().one()
                )
                job = {
                    k: row[k]
                    for k in (
                        "id",
                        "kind",
                        "actor",
                        "state",
                        "phase",
                        "attempts",
                        "generation",
                        "error_code",
                        "created_at",
                        "updated_at",
                        "cancel_requested",
                    )
                }
                job.update(
                    counts=json.loads(row["counts_json"]),
                    checkpoint=json.loads(row["checkpoint_json"]),
                )
                result["job"] = job
                result["error_code"] = job.get("error_code") or result.get("error_code")
                if (
                    job["state"] in ("FAILED", "CANCELLED", "RECOVERABLE")
                    and result["state"] in BUSY
                ):
                    result["state"] = job["state"]
        return result

    def create_batch(
        self, actor, book_id, file_id, profile, request_key, allow_duplicate_file=False
    ):
        def op(conn):
            book = _book(conn, book_id)
            stored = self.rt.files.get(file_id, connection=conn)
            if stored.category not in ("workbooks", "imports"):
                raise CoreError("SOURCE_FILE_INVALID", "Chọn tệp nguồn workbook hoặc import.")
            existing = conn.execute(
                select(s.batches.c.id)
                .where(
                    s.batches.c.book_id == book_id,
                    s.batches.c.file_hash == stored.sha256,
                    s.batches.c.actor_id == actor.id,
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing and not allow_duplicate_file:
                raise CoreError(
                    "FILE_ALREADY_UPLOADED",
                    "Tệp này đã có batch; tiếp tục batch cũ hoặc chủ động xác nhận tạo batch mới.",
                    409,
                    details={"batch_id": existing},
                )
            batch_id, now = identity(), utc_now()
            conn.execute(
                insert(s.batches).values(
                    id=batch_id,
                    book_id=book_id,
                    file_id=file_id,
                    file_hash=stored.sha256,
                    actor_id=actor.id,
                    actor_json=canonical_json(actor.public()),
                    state="UPLOADED",
                    version=1,
                    revision=1,
                    mapping_revision=1,
                    decision_revision=1,
                    schema_revision=book["schema_revision"],
                    profile_json=canonical_json(DEFAULT_PROFILE | profile),
                    mapping_json="{}",
                    source_manifest_json="{}",
                    counts_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
            _queue(conn, actor, "accounting.parse", batch_id, {})
            _audit(
                conn,
                actor,
                "batch",
                batch_id,
                "upload",
                after={"file_id": file_id, "sha256": stored.sha256},
            )
            return {"id": batch_id}

        result = self.write(
            actor,
            "batch.create",
            request_key,
            dict(
                book_id=book_id,
                file_id=file_id,
                profile=profile,
                allow_duplicate_file=allow_duplicate_file,
            ),
            op,
            referenced_file_id=file_id,
        )
        self.dispatch()
        return self.get_batch(actor, result["id"])

    def list_batches(self, actor, book_id, page=1, page_size=100):
        check_page(page, page_size)
        with self.rt.reader() as conn:
            pred = [s.batches.c.book_id == book_id]
            if actor.role != "admin":
                pred.append(s.batches.c.actor_id == actor.id)
            total = conn.execute(
                select(func.count()).select_from(s.batches).where(*pred)
            ).scalar_one()
            ids = (
                conn.execute(
                    select(s.batches.c.id)
                    .where(*pred)
                    .order_by(s.batches.c.created_at.desc(), s.batches.c.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                .scalars()
                .all()
            )
        return page_result([self.get_batch(actor, i) for i in ids], total, page, page_size)

    def staging_page(self, actor, batch_id, page=1, page_size=200, status="", search=""):
        check_page(page, page_size)
        with self.rt.reader() as conn:
            _batch(conn, batch_id, actor)
            pred = [s.stage.c.batch_id == batch_id]
            target = published_target()
            flags = {
                "invalid": s.stage.c.valid == 0,
                "valid": s.stage.c.valid == 1,
                "duplicates": s.stage.c.duplicate_count > 0,
                "pending": target.is_(None),
                "imported": target.is_not(None),
                "excluded": effective_decision() == "skip",
            }
            if status:
                if status not in flags:
                    raise CoreError("FILTER_INVALID", "Trạng thái lọc không hợp lệ.")
                pred.append(flags[status])
            if search:
                pred.append(
                    or_(
                        s.stage.c.raw_json.contains(search[:256], autoescape=True),
                        s.stage.c.row_id == search,
                        s.stage.c.source_row == (int(search) if search.isdigit() else -1),
                    )
                )
            total = conn.execute(
                select(func.count()).select_from(s.stage).where(*pred)
            ).scalar_one()
            rows = conn.execute(
                select(
                    *[c for c in s.stage.c if c.name not in ("target_id", "decision")],
                    target.label("target_id"),
                    effective_decision().label("decision"),
                )
                .where(*pred)
                .order_by(s.stage.c.source_row, s.stage.c.row_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return page_result([stage_dto(r) for r in rows], total, page, page_size)

    def mapping(self, actor, batch_id, expected_version, mapping, profile, request_key):
        def op(conn):
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            version = require_version(batch["version"], expected_version)
            book = _book(conn, batch["book_id"])
            allowed = {c["id"] for c in json.loads(book["columns_json"])}
            if set(mapping) - allowed or any(
                not isinstance(v, str) or not re.fullmatch("[A-Z]{1,3}", v)
                for v in mapping.values()
            ):
                raise CoreError("MAPPING_INVALID", "Ánh xạ cần ID cột ổn định và chữ cột nguồn.")
            new_profile = json.loads(batch["profile_json"]) | (profile or {})
            parse_keys = (
                "sheet_id",
                "header_row",
                "start_row",
                "end_row",
                "encoding",
                "delimiter",
                "skip_blank",
                "hidden_rows",
                "merged_cells",
            )
            reparse = any(
                new_profile.get(k) != json.loads(batch["profile_json"]).get(k) for k in parse_keys
            )
            if reparse:
                has_patches = conn.execute(
                    select(s.patches.c.id).where(s.patches.c.batch_id == batch_id).limit(1)
                ).first()
                has_claims = conn.execute(
                    select(claims.c.source_row_id).where(claims.c.job_id == batch_id).limit(1)
                ).first()
                if has_patches or has_claims:
                    raise CoreError(
                        "PARSE_PROFILE_LOCKED",
                        "Batch đã sửa hoặc xác nhận: tạo batch mới để đổi phạm vi/parser.",
                        409,
                    )
                conn.execute(delete(s.stage).where(s.stage.c.batch_id == batch_id))
                _queue(conn, actor, "accounting.parse", batch_id, {})
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    version=version,
                    revision=batch["revision"] + 1,
                    mapping_revision=batch["mapping_revision"] + 1,
                    mapping_json=canonical_json(mapping),
                    profile_json=canonical_json(new_profile),
                    schema_revision=book["schema_revision"],
                    validation_token=None,
                    state="UPLOADED" if reparse else "READY_FOR_MAPPING",
                    updated_at=utc_now(),
                )
            )
            _audit(
                conn,
                actor,
                "batch",
                batch_id,
                "mapping",
                after={"mapping": mapping, "profile": new_profile},
            )
            return {"id": batch_id}

        self.write(
            actor,
            "batch.mapping",
            request_key,
            dict(
                batch_id=batch_id,
                expected_version=expected_version,
                mapping=mapping,
                profile=profile,
            ),
            op,
        )
        self.dispatch()
        return self.get_batch(actor, batch_id)

    def patch_staging(self, actor, batch_id, expected_version, patches, request_key):
        if not 1 <= len(patches) <= 500 or sum(len(p.get("values", {})) for p in patches) > 10000:
            raise CoreError(
                "PATCH_TOO_LARGE",
                "Dán tối đa 500 dòng/10.000 ô mỗi lượt; dùng tệp cho tập lớn hơn.",
            )

        def op(conn):
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            version = require_version(batch["version"], expected_version)
            allowed = {
                c["id"]: c for c in json.loads(_book(conn, batch["book_id"])["columns_json"])
            }
            for patch in patches:
                row = (
                    conn.execute(
                        select(s.stage).where(
                            s.stage.c.batch_id == batch_id, s.stage.c.row_id == patch["row_id"]
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise CoreError("STAGING_ROW_NOT_FOUND", "Không tìm thấy dòng nguồn.", 404)
                revision = require_version(row.revision, patch["expected_version"])
                if conn.execute(
                    select(published_target())
                    .select_from(s.stage)
                    .where(s.stage.c.batch_id == batch_id, s.stage.c.row_id == row.row_id)
                ).scalar_one_or_none():
                    raise CoreError(
                        "ALREADY_IMPORTED",
                        "Dòng đã nhập; chỉnh sửa qua sổ và version của giao dịch.",
                        409,
                    )
                if set(patch["values"]) - set(allowed) or any(
                    not allowed[k].get("editable", True) for k in patch["values"]
                ):
                    raise CoreError("CELL_READ_ONLY", "Cột không cho phép chỉnh sửa.")
                edited = json.loads(row.edited_json) | patch["values"]
                raw = json.loads(row.raw_json)
                mapping = json.loads(batch["mapping_json"])
                check_row_budget({col: raw.get(source) for col, source in mapping.items()} | edited)
                conn.execute(
                    update(s.stage)
                    .where(s.stage.c.batch_id == batch_id, s.stage.c.row_id == row.row_id)
                    .values(
                        edited_json=canonical_json(edited),
                        revision=revision,
                        valid=0,
                        validation_revision=None,
                    )
                )
                conn.execute(
                    insert(s.patches).values(
                        id=identity(),
                        batch_id=batch_id,
                        row_id=row.row_id,
                        revision=revision,
                        values_json=canonical_json(patch["values"]),
                        actor_id=actor.id,
                        created_at=utc_now(),
                    )
                )
                _audit(
                    conn,
                    actor,
                    "stage",
                    batch_id + ":" + row.row_id,
                    "patch",
                    json.loads(row.edited_json),
                    edited,
                )
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    version=version,
                    revision=batch["revision"] + 1,
                    state="READY_FOR_MAPPING",
                    validation_token=None,
                    updated_at=utc_now(),
                )
            )
            return {"id": batch_id}

        self.write(
            actor,
            "batch.patch",
            request_key,
            dict(batch_id=batch_id, expected_version=expected_version, patches=patches),
            op,
        )
        return self.get_batch(actor, batch_id)

    def decisions(
        self, actor, batch_id, expected_version, decisions, all_pending_duplicates, request_key
    ):
        if len(decisions) > 500 or all_pending_duplicates not in (None, "keep", "skip"):
            raise CoreError("DECISION_INVALID", "Quyết định trùng không hợp lệ.")

        def op(conn):
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            version = require_version(batch["version"], expected_version)
            if all_pending_duplicates:
                conn.execute(
                    update(s.batches)
                    .where(s.batches.c.id == batch_id)
                    .values(duplicate_default=all_pending_duplicates)
                )
            for decision in decisions:
                if decision["decision"] not in ("keep", "skip"):
                    raise CoreError("DECISION_INVALID", "Chỉ giữ hoặc bỏ qua dòng, không tự merge.")
                conn.execute(
                    update(s.stage)
                    .where(
                        s.stage.c.batch_id == batch_id,
                        s.stage.c.row_id == decision["row_id"],
                        published_target().is_(None),
                    )
                    .values(decision=decision["decision"])
                )
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    version=version,
                    decision_revision=batch["decision_revision"] + 1,
                    updated_at=utc_now(),
                )
            )
            _audit(
                conn,
                actor,
                "batch",
                batch_id,
                "duplicate_decisions",
                after={"decisions": decisions, "all_pending_duplicates": all_pending_duplicates},
            )
            return {"id": batch_id}

        self.write(
            actor,
            "batch.decisions",
            request_key,
            dict(
                batch_id=batch_id,
                expected_version=expected_version,
                decisions=decisions,
                all_pending_duplicates=all_pending_duplicates,
            ),
            op,
        )
        # Aggregate outside the writer: the only follow-up write replaces a small
        # DTO if no concurrent decision/patch/validation has changed its version.
        from .jobs import AccountingJobs

        with self.rt.reader() as conn:
            current = _batch(conn, batch_id, actor)
            counts = AccountingJobs.counts(conn, batch_id)

        def persist_counts(conn):
            self.authorize(actor)(conn)
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id, s.batches.c.version == current["version"])
                .values(counts_json=canonical_json(counts))
            )

        self.rt.writer.run(persist_counts)
        return self.get_batch(actor, batch_id)

    def validate(self, actor, batch_id, expected_version, request_key):
        def op(conn):
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            _require_parse_complete(conn, batch_id)
            version = require_version(batch["version"], expected_version)
            book = _book(conn, batch["book_id"])
            if book["schema_revision"] != batch["schema_revision"]:
                raise CoreError(
                    "SCHEMA_STALE", "Schema đã đổi; lưu lại mapping trước khi kiểm tra.", 409
                )
            mapping = json.loads(batch["mapping_json"])
            if any(
                c["required"] and c["id"] not in mapping and not c.get("formula")
                for c in json.loads(book["columns_json"])
            ):
                raise CoreError("MAPPING_REQUIRED", "Chưa ánh xạ đủ cột bắt buộc.", 422)
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    state="VALIDATING", version=version, validation_token=None, updated_at=utc_now()
                )
            )
            _queue(conn, actor, "accounting.validate", batch_id, {"revision": batch["revision"]})
            return {"id": batch_id}

        self.write(
            actor,
            "batch.validate",
            request_key,
            dict(batch_id=batch_id, expected_version=expected_version),
            op,
        )
        self.dispatch()
        return self.get_batch(actor, batch_id)

    def confirm(self, actor, batch_id, command):
        def op(conn):
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            _require_parse_complete(conn, batch_id)
            version = require_version(batch["version"], command["expected_version"])
            book = _book(conn, batch["book_id"])
            for key, expected in (
                ("staging_revision", batch["revision"]),
                ("mapping_revision", batch["mapping_revision"]),
                ("decision_revision", batch["decision_revision"]),
                ("validation_token", batch["validation_token"]),
            ):
                if not expected or command.get(key) != expected:
                    raise CoreError(
                        "VALIDATION_STALE", "Phiên bản xác nhận đã cũ. Kiểm tra lại dữ liệu.", 409
                    )
            if (
                book["schema_revision"] != batch["schema_revision"]
                or command.get("mode") != "valid_rows_only"
            ):
                raise CoreError(
                    "VALIDATION_STALE", "Schema hoặc chế độ xác nhận không hợp lệ.", 409
                )
            count = conn.execute(
                select(func.count()).select_from(s.stage).where(*eligible(batch_id))
            ).scalar_one()
            if count == 0:
                raise CoreError(
                    "NO_ELIGIBLE_ROWS", "Không có dòng hợp lệ đã được quyết định để nhập.", 409
                )
            pins = dict(
                staging_revision=batch["revision"],
                mapping_revision=batch["mapping_revision"],
                decision_revision=batch["decision_revision"],
                validation_token=batch["validation_token"],
                mapping_snapshot=json.loads(batch["mapping_json"]),
                duplicate_decisions={
                    "selection": "persisted_row_decisions",
                    "revision": batch["decision_revision"],
                    "default_for_undecided": batch.get("duplicate_default"),
                },
                mode="valid_rows_only",
                schema_revision=batch["schema_revision"],
                book_snapshot=book_dto(book),
            )
            manifest = ATTEMPTS.create_manifest(
                conn, job_id=batch_id, pins=pins, expected_count=count
            )
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    version=version,
                    state="COMMITTING",
                    manifest_id=manifest,
                    attempt_id=None,
                    updated_at=utc_now(),
                )
            )
            _queue(
                conn,
                actor,
                "accounting.commit",
                batch_id,
                {"manifest_id": manifest, "expected_count": count},
            )
            _audit(
                conn,
                actor,
                "batch",
                batch_id,
                "confirm",
                after={"manifest_id": manifest, "pins": pins, "selected_rows": count},
            )
            return {"id": batch_id}

        self.write(
            actor, "batch.confirm", command["request_key"], dict(command, batch_id=batch_id), op
        )
        self.dispatch()
        return self.get_batch(actor, batch_id)

    def cancel_resume(self, actor, batch_id, action):
        batch = self.get_batch(actor, batch_id)
        if not batch["job_id"]:
            raise CoreError("JOB_NOT_FOUND", "Chưa có tác vụ.", 404)
        authorize = self.authorize(actor)
        if action == "cancel":
            self.rt.jobs.cancel(batch["job_id"], authorize=authorize)

            def cancel(conn):
                authorize(conn)
                current = _batch(conn, batch_id, actor)
                task = (
                    conn.execute(select(s.tasks).where(s.tasks.c.job_id == batch["job_id"]))
                    .mappings()
                    .one()
                )
                if task.kind == "accounting.commit" and current["attempt_id"]:
                    ATTEMPTS.set_interrupted(conn, current["attempt_id"], "CANCELLED")
                conn.execute(
                    update(s.batches)
                    .where(s.batches.c.id == batch_id)
                    .values(state="CANCELLED", updated_at=utc_now())
                )
                _audit(conn, actor, "batch", batch_id, "cancel")

            self.rt.writer.run(cancel)
        else:

            def prepare(conn):
                authorize(conn)
                current = _batch(conn, batch_id, actor)
                task = (
                    conn.execute(select(s.tasks).where(s.tasks.c.job_id == batch["job_id"]))
                    .mappings()
                    .one()
                )
                if task.kind == "accounting.commit" and current["attempt_id"]:
                    ATTEMPTS.resume(conn, current["attempt_id"])
                conn.execute(
                    update(s.batches)
                    .where(s.batches.c.id == batch_id)
                    .values(
                        state={
                            "accounting.parse": "PARSING",
                            "accounting.validate": "VALIDATING",
                            "accounting.commit": "COMMITTING",
                        }[task.kind],
                        updated_at=utc_now(),
                    )
                )

            self.rt.writer.run(prepare)
            self.rt.jobs.resume(batch["job_id"], authorize=authorize)
        return self.get_batch(actor, batch_id)

    def preview_summary(self, actor, batch_id, from_on, through_on):
        with self.rt.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            batch = _batch(conn, batch_id, actor)
            _idle(batch, conn)
            if not batch["validation_token"]:
                raise CoreError(
                    "VALIDATION_REQUIRED",
                    "Kiểm tra dữ liệu trước khi so sánh số tiền dự kiến.",
                    409,
                )
            book = _book(conn, batch["book_id"])
            if book["schema_revision"] != batch["schema_revision"]:
                raise CoreError(
                    "SCHEMA_STALE",
                    "Schema đã đổi; lưu mapping và kiểm tra lại trước khi so sánh.",
                    409,
                )
            before = self.summary(
                actor, book["id"], from_on, through_on, connection=conn, include_groups=False
            )
            if not before["has_valid_money_mapping"]:
                return {
                    "before": before,
                    "new_batch": {},
                    "after": {},
                    "provisional": True,
                    "validation_flags": before["validation_flags"],
                }
            meaning = json.loads(book["semantics_json"])
            totals = {}
            with localcontext() as ctx:
                ctx.prec = 80
                query = (
                    select(s.stage.c.typed_json)
                    .where(*eligible(batch_id))
                    .order_by(s.stage.c.row_id)
                )
                for encoded in conn.execute(query).scalars():
                    v = json.loads(encoded)
                    day = v.get(meaning["date_column"])
                    if not day or not from_on <= day <= through_on:
                        continue
                    currency = v.get(meaning.get("currency_column")) or meaning.get(
                        "currency", "VND"
                    )
                    item = totals.setdefault(
                        currency, {"income": Decimal(0), "expense": Decimal(0), "row_count": 0}
                    )
                    item["row_count"] += 1
                    for key in ("income", "expense"):
                        if meaning.get(key + "_column"):
                            item[key] += Decimal(v.get(meaning[key + "_column"]) or "0")
                        elif meaning.get("amount_column") and v.get(
                            meaning.get("direction_column")
                        ) == meaning.get(key + "_value", "thu" if key == "income" else "chi"):
                            item[key] += Decimal(v.get(meaning["amount_column"]) or "0")
                new_batch = {
                    c: {
                        k: format(v, ".2f") if isinstance(v, Decimal) else v
                        for k, v in item.items()
                    }
                    for c, item in totals.items()
                }
                after = {}
                for currency in set(before["totals"]) | set(new_batch):
                    old, new = before["totals"].get(currency, {}), new_batch.get(currency, {})
                    after[currency] = {
                        key: format(Decimal(old.get(key, "0")) + Decimal(new.get(key, "0")), ".2f")
                        for key in ("income", "expense")
                    }
                    after[currency]["row_count"] = old.get("row_count", 0) + new.get("row_count", 0)
            return {
                "before": before,
                "new_batch": new_batch,
                "after": after,
                "provisional": True,
                "staging_revision": batch["revision"],
                "mapping_revision": batch["mapping_revision"],
                "decision_revision": batch["decision_revision"],
                "data_revision": book["data_revision"],
                "validation_token": batch["validation_token"],
                "validation_flags": [],
            }

    def summary(
        self,
        actor,
        book_id,
        from_on,
        through_on,
        *,
        connection=None,
        cutoff=None,
        include_groups=True,
    ):
        actor.require("accounting.read")
        try:
            if (
                not isinstance(from_on, str)
                or not isinstance(through_on, str)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", from_on)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", through_on)
            ):
                raise ValueError()
            start, end = date.fromisoformat(from_on), date.fromisoformat(through_on)
        except (ValueError, TypeError):
            raise CoreError(
                "DATE_RANGE_INVALID", "Ngày bắt đầu/kết thúc phải có định dạng YYYY-MM-DD."
            ) from None
        if end < start:
            raise CoreError(
                "DATE_RANGE_INVALID", "Ngày cuối được bao gồm và phải từ ngày đầu trở đi."
            )
        with self.rt.reader() if connection is None else nullcontext(connection) as conn:
            if connection is None:
                conn.exec_driver_sql("BEGIN")
            self.rt.auth.authorize(conn, actor, "accounting.read")
            book = _book(conn, book_id)
            semantics = json.loads(book["semantics_json"])
            columns = {c["id"]: c for c in json.loads(book["columns_json"])}
            valid = bool(
                semantics.get("date_column")
                and (
                    semantics.get("income_column")
                    or semantics.get("expense_column")
                    or (semantics.get("amount_column") and semantics.get("direction_column"))
                )
            )
            money_keys = [
                semantics[k]
                for k in ("income_column", "expense_column", "amount_column")
                if semantics.get(k)
            ]
            valid = (
                valid
                and columns[semantics["date_column"]]["kind"] == "date"
                and all(
                    columns[k]["kind"] == "money"
                    or (columns[k]["kind"] == "formula" and columns[k]["scale"] == 2)
                    for k in money_keys
                )
            )
            if semantics.get("amount_column") and semantics.get("direction_column"):
                valid = (
                    valid
                    and isinstance(semantics.get("income_value"), str)
                    and isinstance(semantics.get("expense_value"), str)
                    and semantics["income_value"] != semantics["expense_value"]
                )
            if not valid:
                return {
                    "book_id": book_id,
                    "has_valid_money_mapping": False,
                    "totals": {},
                    "validation_flags": ["MONEY_MAPPING_REQUIRED"],
                    "data_revision": book["data_revision"],
                    "schema_revision": book["schema_revision"],
                    "from_on": from_on,
                    "through_on": through_on,
                }
            totals, groups, unknown_directions = {}, {}, 0
            query = (
                select(s.entries.c.values_json)
                .where(s.entries.c.book_id == book_id, s.entries.c.deleted_at.is_(None), visible())
                .order_by(s.entries.c.logical_row)
            )
            with localcontext() as ctx:
                ctx.prec = 80
                for encoded in conn.execute(query).scalars():
                    v = json.loads(encoded)
                    day = v.get(semantics["date_column"])
                    if not day or not from_on <= day <= through_on:
                        continue
                    currency = v.get(semantics.get("currency_column")) or semantics.get(
                        "currency", "VND"
                    )
                    item = totals.setdefault(
                        currency, {"income": Decimal(0), "expense": Decimal(0), "row_count": 0}
                    )
                    item["row_count"] += 1
                    before_income, before_expense = item["income"], item["expense"]
                    if semantics.get("direction_column") and v.get(
                        semantics["direction_column"]
                    ) not in (semantics.get("income_value"), semantics.get("expense_value")):
                        unknown_directions += 1
                    for key in ("income", "expense"):
                        if semantics.get(key + "_column"):
                            item[key] += Decimal(v.get(semantics[key + "_column"]) or "0")
                        elif semantics.get("amount_column") and v.get(
                            semantics.get("direction_column")
                        ) == semantics.get(key + "_value", "thu" if key == "income" else "chi"):
                            item[key] += Decimal(v.get(semantics["amount_column"]) or "0")
                    if include_groups and semantics.get("group_columns"):
                        dimensions = {
                            column: v.get(column) for column in semantics["group_columns"]
                        }
                        group_key = canonical_json([currency, dimensions])
                        group = groups.setdefault(
                            group_key,
                            {
                                "currency": currency,
                                "dimensions": dimensions,
                                "income": Decimal(0),
                                "expense": Decimal(0),
                                "row_count": 0,
                            },
                        )
                        if len(groups) > 1000:
                            raise CoreError(
                                "REPORT_GROUP_LIMIT",
                                "Báo cáo tương tác hỗ trợ tối đa 1000 nhóm; thu hẹp kỳ hoặc chiều nhóm.",
                                413,
                            )
                        group["row_count"] += 1
                        group["income"] += item["income"] - before_income
                        group["expense"] += item["expense"] - before_expense
                totals = {
                    c: {
                        k: format(v, ".2f") if isinstance(v, Decimal) else v
                        for k, v in item.items()
                    }
                    for c, item in totals.items()
                }
            return dict(
                book_id=book_id,
                has_valid_money_mapping=True,
                totals=totals,
                validation_flags=[f"UNMAPPED_DIRECTION_ROWS:{unknown_directions}"]
                if unknown_directions
                else [],
                groups=[
                    {k: format(v, ".2f") if isinstance(v, Decimal) else v for k, v in group.items()}
                    for group in groups.values()
                ],
                metric_meanings=semantics.get("metric_meanings", {}),
                metric_keys=[
                    key
                    for key in ("income", "expense")
                    if semantics.get(key + "_column")
                    or (semantics.get("direction_column") and semantics.get("amount_column"))
                ],
                data_revision=book["data_revision"],
                schema_revision=book["schema_revision"],
                coverage="entered_records_only",
                cutoff=cutoff.isoformat() if cutoff is not None else utc_now(),
                from_on=from_on,
                through_on=through_on,
            )


def eligible(batch_id):
    return (
        s.stage.c.batch_id == batch_id,
        s.stage.c.valid == 1,
        ~exists(
            select(1).where(claims.c.job_id == batch_id, claims.c.source_row_id == s.stage.c.row_id)
        ),
        or_(effective_decision().is_(None), effective_decision() != "skip"),
        or_(s.stage.c.duplicate_count == 0, effective_decision() == "keep"),
    )


class AccountingReadProvider:
    """Read-only bridge bound by coordinator with the caller's principal."""

    def __init__(self, runtime, actor, *, connection=None):
        self.service, self.actor = AccountingService(runtime), actor
        self.connection = connection

    def book_summary(self, book_id, from_on, through_on, *, cutoff):
        result = self.service.summary(
            self.actor,
            book_id,
            from_on.isoformat(),
            through_on.isoformat(),
            connection=self.connection,
            cutoff=cutoff,
            include_groups=False,
        )
        # Live reads cannot represent a historical cutoff: force consumer to freeze now.
        if cutoff.tzinfo is None or (
            self.connection is None
            and abs((datetime.now(timezone.utc) - cutoff).total_seconds()) > 60
        ):
            raise CoreError(
                "HISTORICAL_SNAPSHOT_REQUIRED", "Cần snapshot đã đóng băng cho cutoff lịch sử.", 409
            )
        metrics, flags = [], list(result["validation_flags"])
        if result["has_valid_money_mapping"]:
            if set(result["totals"]) - {"VND"}:
                flags.append("NON_VND_CURRENCIES_OMITTED")
            for key in result["metric_keys"]:
                amount = result["totals"].get("VND", {}).get(key, "0.00")
                meaning = result["metric_meanings"].get(key)
                if meaning in (None, "other"):
                    flags.append("METRIC_MEANING_UNKNOWN:" + key)
                elif Decimal(amount) < 0:
                    # Preserve signed source amount; don't claim a known positive cash
                    # measure for a net refund/reversal that hasn't been classified.
                    meaning = None
                    flags.append("NEGATIVE_METRIC_REQUIRES_CLASSIFICATION:" + key)
                metrics.append(
                    MappedBookMetricDTO(
                        key=key,
                        amount_vnd=amount,
                        mapping_revision=result["schema_revision"],
                        meaning=meaning,
                    )
                )
            by_meaning = {m.meaning: m for m in metrics if m.meaning not in (None, "other")}
            for subset, total in (
                ("cash_receipt_deposits", "cash_receipts"),
                ("cash_payment_deposits", "cash_payments"),
            ):
                if (
                    subset in by_meaning
                    and total in by_meaning
                    and Decimal(by_meaning[subset].amount_vnd)
                    > Decimal(by_meaning[total].amount_vnd)
                ):
                    flags.append("METRIC_SUBSET_EXCEEDS_TOTAL:" + subset)
                    metrics = [
                        m.model_copy(update={"meaning": None}) if m.meaning == subset else m
                        for m in metrics
                    ]
        return BookSummaryDTO(
            book_id=book_id,
            from_on=from_on,
            through_on=through_on,
            cutoff=cutoff,
            has_valid_money_mapping=result["has_valid_money_mapping"],
            metrics=tuple(metrics),
            validation_flags=tuple(flags),
        )
