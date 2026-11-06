"""Versioned records and chronological inventory in one core writer transaction."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

from pydantic import ValidationError
from sqlalchemy import and_, func, insert, select

from cafe_fin.core.amounts import checked_int64, kg_string, money_string, parse_kg, parse_money
from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.contracts import PartyInput
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.stock_guard import StockPoint, assert_nonnegative
from cafe_fin.core.time import BUSINESS_ZONE

from .migrations import DOCUMENTS as D
from .migrations import LINES
from .migrations import MOVEMENTS as M
from .migrations import REFERENCES as F
from .migrations import REVISIONS as R
from .models import MODELS, day, identity, parse_timestamp

RESOURCES = frozenset(MODELS)


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def cutoff_text(cutoff: datetime) -> str:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise CoreError("INVALID_CUTOFF", "Thời điểm chốt phải có múi giờ.")
    return cutoff.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def decimal_total(value: int, scale: int) -> str:
    sign = "-" if value < 0 else ""
    whole, remainder = divmod(abs(value), 10**scale)
    return f"{sign}{whole}.{remainder:0{scale}d}"


def invalid(field: str, message: str, code: str = "INVALID_RECORD"):
    raise CoreError(
        code, message, 422, field_errors=[{"field": field, "code": code, "message": message}]
    )


def current_query(kind=None, *, cutoff=None):
    if cutoff is None:
        join = D.join(R, and_(D.c.id == R.c.document_id, D.c.version == R.c.version))
    else:
        latest = (
            select(R.c.document_id, func.max(R.c.version).label("version"))
            .where(R.c.recorded_at <= cutoff_text(cutoff))
            .group_by(R.c.document_id)
            .subquery()
        )
        join = D.join(latest, D.c.id == latest.c.document_id).join(
            R, and_(D.c.id == R.c.document_id, latest.c.version == R.c.version)
        )
    query = select(
        D.c.id,
        D.c.kind,
        D.c.sequence,
        R.c.version,
        R.c.data_json,
        R.c.recorded_at,
        R.c.commercial_scaled,
    ).select_from(join)
    return query.where(D.c.kind == kind) if kind else query


def effective_movements(*, cutoff=None):
    effective = current_query("entries", cutoff=cutoff).subquery()
    return select(M).join(
        effective, and_(M.c.entry_id == effective.c.id, M.c.version == effective.c.version)
    )


def get_record(conn, kind, document_id, *, allow_deleted=True):
    row = conn.execute(current_query(kind).where(D.c.id == document_id)).mappings().first()
    if row is None:
        raise CoreError("NOT_FOUND", "Không tìm thấy hồ sơ.", 404)
    data = json.loads(row.data_json)
    if not allow_deleted and data["deleted_at"] is not None:
        raise CoreError("RECORD_DELETED", "Hồ sơ đã ngừng/xóa; cần khôi phục trước.", 409)
    return data, row.sequence


def checked_page(page, page_size):
    if type(page) is not int or page < 1 or type(page_size) is not int or not 1 <= page_size <= 500:
        raise CoreError("INVALID_PAGE", "Phân trang phải từ 1, tối đa 500 dòng.", 422)


class RecordsService:
    def __init__(self, runtime):
        self.runtime = runtime

    def _authorize(self, conn, actor, permission="records.read"):
        return self.runtime.auth.authorize(conn, actor, permission)

    def _snapshot(self, actor):
        # Explicit read transaction: cutoff selection and child rows share one WAL snapshot.
        return self.runtime.reader()

    def get(self, kind, document_id, *, actor):
        with self._snapshot(actor) as conn:
            conn.exec_driver_sql("BEGIN")
            self._authorize(conn, actor)
            return get_record(conn, kind, document_id)[0]

    def list(self, kind, *, actor, page=1, page_size=50, search="", sort="code", filters=None):
        checked_page(page, page_size)
        if len(search) > 300:
            invalid("search", "Từ khóa quá dài.")
        filters = filters or {}
        allowed = {
            "from_on",
            "through_on",
            "party_id",
            "entry_type",
            "status",
            "active",
            "include_deleted",
        }
        if not isinstance(filters, dict) or set(filters) - allowed:
            invalid("filters", "Bộ lọc không được hỗ trợ.")
        for key in ("active", "include_deleted"):
            if key in filters and type(filters[key]) is not bool:
                invalid(f"filters.{key}", "Bộ lọc phải là boolean.")
        for key in ("from_on", "through_on"):
            if key in filters:
                try:
                    day(filters[key])
                except (ValueError, TypeError):
                    invalid(f"filters.{key}", "Ngày không hợp lệ.")
        if filters.get("from_on", "") > filters.get("through_on", "9999-12-31"):
            invalid("filters", "Ngày bắt đầu phải trước ngày kết thúc.")
        for key in ("party_id", "entry_type", "status"):
            if key in filters and not isinstance(filters[key], str):
                invalid(f"filters.{key}", "Bộ lọc phải là chuỗi.")
        field = sort.lstrip("-")
        if field not in {"code", "occurred_on", "updated_at", "name"}:
            invalid("sort", "Thứ tự sắp xếp không được hỗ trợ.")
        query = current_query(kind)

        def extract(key):
            return func.json_extract(R.c.data_json, "$." + key)

        if not filters.get("include_deleted"):
            query = query.where(R.c.deleted_at.is_(None))
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(
                (extract("code").ilike(f"%{escaped}%", escape="\\"))
                | (extract("name").ilike(f"%{escaped}%", escape="\\"))
                | (extract("note").ilike(f"%{escaped}%", escape="\\"))
            )
        for key in ("party_id", "entry_type", "status", "active"):
            if key in filters:
                query = query.where(extract(key) == filters[key])
        if "from_on" in filters:
            query = query.where(R.c.occurred_on >= filters["from_on"])
        if "through_on" in filters:
            query = query.where(R.c.occurred_on <= filters["through_on"])
        order = extract(field).desc() if sort.startswith("-") else extract(field).asc()
        with self._snapshot(actor) as conn:
            conn.exec_driver_sql("BEGIN")
            self._authorize(conn, actor)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(order, D.c.sequence).offset((page - 1) * page_size).limit(page_size)
            ).mappings()
            return {
                "items": [json.loads(row.data_json) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def history(self, kind, document_id, *, actor, page=1, page_size=50):
        checked_page(page, page_size)
        with self._snapshot(actor) as conn:
            conn.exec_driver_sql("BEGIN")
            self._authorize(conn, actor)
            get_record(conn, kind, document_id)
            query = select(R).where(R.c.document_id == document_id)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(R.c.version.desc()).offset((page - 1) * page_size).limit(page_size)
            ).mappings()
            return {
                "items": [
                    {
                        "version": row.version,
                        "action": row.action,
                        "recorded_at": row.recorded_at,
                        "actor": row.actor,
                        "data": json.loads(row.data_json),
                    }
                    for row in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def save(self, kind, data, *, actor, request_key, identity=None, expected_version=None):
        if kind not in RESOURCES:
            raise CoreError("NOT_FOUND", "Loại hồ sơ không tồn tại.", 404)
        # Validate trusted service callers just as strictly as HTTP callers.
        try:
            parsed = MODELS[kind].model_validate(
                data | {"request_key": request_key, "expected_version": expected_version}
            )
        except ValidationError as exc:
            invalid("record", str(exc))
        clean = parsed.model_dump(mode="json", exclude={"request_key", "expected_version"})
        action = "create" if identity is None else "update"
        if identity is None and expected_version is not None:
            invalid("expected_version", "Tạo mới không có expected_version.")
        return self._execute(kind, clean, actor, request_key, identity, expected_version, action)

    def command(self, kind, document_id, command, *, actor, request_key, expected_version):
        if command not in {"delete", "restore", "post", "cancel"}:
            invalid("command", "Lệnh không hợp lệ.")
        if command in {"post", "cancel"} and kind != "entries":
            invalid("command", "Lệnh chỉ dành cho phiếu hàng.")
        return self._execute(kind, None, actor, request_key, document_id, expected_version, command)

    def _execute(self, kind, clean, actor, request_key, document_id, expected_version, action):
        if document_id is not None:
            try:
                identity(document_id)
            except (ValueError, TypeError, AttributeError):
                invalid("id", "ID phải là UUID canonical.")
        payload = {"id": document_id, "data": clean, "expected_version": expected_version}

        def operation(conn):
            old, sequence = None, None
            version, doc_id, timestamp = 1, document_id or str(uuid.uuid4()), now_text()
            if document_id is not None:
                old, sequence = get_record(conn, kind, doc_id)
                version = require_version(old["version"], expected_version)
                if old["deleted_at"] and action != "restore":
                    raise CoreError("RECORD_DELETED", "Cần khôi phục hồ sơ trước khi sửa.", 409)
                if action == "restore" and not old["deleted_at"]:
                    raise CoreError("INVALID_STATE", "Hồ sơ chưa bị xóa.", 409)
            if action in {"delete", "restore", "post", "cancel"}:
                data = {
                    key: value
                    for key, value in old.items()
                    if key
                    not in {
                        "id",
                        "version",
                        "created_at",
                        "updated_at",
                        "created_by",
                        "updated_by",
                        "recorded_at",
                        "deleted_at",
                        "order_key",
                    }
                }
                if action in {"post", "cancel"}:
                    if old["status"] == ("posted" if action == "post" else "cancelled"):
                        raise CoreError("INVALID_STATE", "Phiếu đã ở trạng thái được yêu cầu.", 409)
                    data["status"] = "posted" if action == "post" else "cancelled"
            else:
                data = dict(clean)
            deleted = timestamp if action == "delete" else None
            if kind in {"parties", "products", "units", "warehouses"} and action == "delete":
                # A master record remains readable, but referenced records use deactivation.
                if conn.execute(
                    select(F.c.document_id).where(F.c.target_id == doc_id).limit(1)
                ).first():
                    raise CoreError(
                        "RECORD_REFERENCED", "Hồ sơ đang được tham chiếu; hãy ngừng sử dụng.", 409
                    )
            references = self._normalize(conn, kind, data, old, deleted)
            code_key = data["code"].casefold()
            collision = conn.execute(
                select(D.c.id).where(D.c.kind == kind, D.c.code_key == code_key, D.c.id != doc_id)
            ).first()
            if collision:
                raise CoreError("CODE_CONFLICT", "Mã hồ sơ đã tồn tại, kể cả hồ sơ đã xóa.", 409)
            if old is None:
                result = conn.execute(
                    insert(D).values(
                        id=doc_id,
                        kind=kind,
                        code_key=code_key,
                        version=version,
                        created_at=timestamp,
                        created_by=actor.id,
                    )
                )
                sequence = result.inserted_primary_key[0]
            else:
                conn.execute(
                    D.update().where(D.c.id == doc_id).values(version=version, code_key=code_key)
                )
            result = data | {
                "id": doc_id,
                "version": version,
                "created_at": old["created_at"] if old else timestamp,
                "created_by": old["created_by"] if old else actor.id,
                "updated_at": timestamp,
                "updated_by": actor.id,
                "recorded_at": timestamp,
                "deleted_at": deleted,
                "order_key": f"{sequence:020d}",
            }
            conn.execute(
                insert(R).values(
                    document_id=doc_id,
                    version=version,
                    recorded_at=timestamp,
                    actor=actor.id,
                    action=action,
                    data_json=canonical_json(result),
                    occurred_on=data.get("occurred_on"),
                    status=data.get("status"),
                    commercial_scaled=(
                        parse_money(data["commercial_amount_vnd"])
                        if data.get("commercial_amount_vnd") is not None
                        else None
                    ),
                    deleted_at=deleted,
                )
            )
            for target in sorted(references):
                conn.execute(
                    insert(F).values(document_id=doc_id, version=version, target_id=target)
                )
            for number, line in enumerate(data.get("lines", []), start=1):
                amounts = {
                    scaled: parse_kg(line[field]) if line.get(field) is not None else None
                    for field, scaled in (
                        ("quantity_kg", "quantity_scaled"),
                        ("gross_kg", "gross_scaled"),
                        ("tare_kg", "tare_scaled"),
                        ("net_kg", "net_scaled"),
                    )
                }
                conn.execute(
                    insert(LINES).values(
                        document_id=doc_id,
                        version=version,
                        line_number=number,
                        product_id=line.get("product_id"),
                        warehouse_id=line.get("warehouse_id"),
                        quantity_source=line.get("quantity_source"),
                        direction=line.get("direction"),
                        **amounts,
                    )
                )
            if kind == "entries":
                affected = self._scopes(old) | self._scopes(result)
                if data["status"] == "posted" and deleted is None:
                    self._write_movements(conn, result)
                self._guard(conn, affected)
            AuditService.record(
                conn,
                actor=actor.id,
                entity=f"records.{kind}",
                entity_id=doc_id,
                action=action,
                before=old,
                after=result,
            )
            return result

        return self.runtime.writer.execute(
            actor.id,
            f"records.{kind}.{action}",
            request_key,
            payload,
            operation,
            authorize=lambda conn: self._authorize(conn, actor, "records.write"),
        )

    def _normalize(self, conn, kind, data, old, deleted):
        references = set()
        previous_refs = {(old or {}).get(field) for field in ("party_id", "unit_id", "weighing_id")}
        for line in (old or {}).get("lines", []):
            previous_refs.update(line.get(field) for field in ("product_id", "warehouse_id"))
        if "name" in data and not data["name"].strip():
            invalid("name", "Tên hồ sơ không được chỉ chứa khoảng trắng.")

        def ref(target, resource, field, old_target=None):
            if target is None:
                return
            try:
                linked, _ = get_record(conn, resource, target)
            except CoreError as exc:
                if exc.code == "NOT_FOUND":
                    invalid(field, "Không tìm thấy hồ sơ được chọn.", "REFERENCE_NOT_FOUND")
                raise
            if (
                linked["deleted_at"] or not linked.get("active", True)
            ) and target not in previous_refs:
                invalid(field, "Hồ sơ được chọn đã ngừng sử dụng.", "REFERENCE_INACTIVE")
            references.add(target)

        if "occurred_on" in data and data.get("occurred_at") is not None:
            try:
                actual = parse_timestamp(data["occurred_at"])
                if actual.astimezone(BUSINESS_ZONE).date().isoformat() != data["occurred_on"]:
                    invalid("occurred_at", "Thời điểm không thuộc ngày nghiệp vụ Việt Nam.")
                data["occurred_at"] = actual.astimezone(timezone.utc).isoformat()
            except (ValueError, TypeError):
                invalid("occurred_at", "Thời điểm phải hợp lệ và có múi giờ.")
        if kind == "parties":
            try:
                PartyInput.model_validate_json(
                    canonical_json(
                        {
                            key: data[key]
                            for key in (
                                "type",
                                "roles",
                                "name",
                                "tax_code",
                                "address",
                                "contacts",
                                "bank_details",
                                "representative",
                            )
                        }
                    )
                )
            except ValidationError:
                invalid("roles", "Vai trò đối tác không được trống hoặc trùng.")
        if kind == "products":
            ref(data.get("unit_id"), "units", "unit_id", (old or {}).get("unit_id"))
        if kind in {"weighings", "entries"}:
            ref(data.get("party_id"), "parties", "party_id", (old or {}).get("party_id"))
        if kind == "weighings":
            for index, line in enumerate(data["lines"]):
                prefix = f"lines.{index}"
                old_line = old["lines"][index] if old and index < len(old["lines"]) else {}
                ref(
                    line.get("product_id"),
                    "products",
                    prefix + ".product_id",
                    old_line.get("product_id"),
                )
                if line["quantity_source"] == "direct_net":
                    if line.get("net_kg") is None:
                        invalid(prefix + ".net_kg", "Cần nhập kg tịnh.")
                    if line.get("gross_kg") is not None or line.get("tare_kg") is not None:
                        invalid(prefix, "Dạng tịnh trực tiếp không dùng cân đầy/rỗng.")
                    fields = ("net_kg",)
                else:
                    if line.get("gross_kg") is None or line.get("tare_kg") is None:
                        invalid(prefix, "Dạng đầy/rỗng cần đủ hai số cân.")
                    fields = ("gross_kg", "tare_kg")
                for field in fields:
                    value = self._quantity(line[field], prefix + "." + field, positive=False)
                    line[field] = kg_string(value)
                if line["quantity_source"] == "gross_tare":
                    net = parse_kg(line["gross_kg"]) - parse_kg(line["tare_kg"])
                    if net < 0:
                        invalid(prefix, "Cân đầy phải lớn hơn hoặc bằng cân rỗng.")
                    net_string = kg_string(net)
                    if line.get("net_kg") is not None and parse_kg(line["net_kg"]) != net:
                        invalid(prefix + ".net_kg", "Kg tịnh không bằng đầy trừ rỗng.")
                    line["net_kg"] = net_string
        if kind == "entries":
            ref(data.get("weighing_id"), "weighings", "weighing_id", (old or {}).get("weighing_id"))
            if data.get("commercial_amount_vnd") is not None:
                try:
                    data["commercial_amount_vnd"] = money_string(
                        parse_money(data["commercial_amount_vnd"])
                    )
                except CoreError as exc:
                    invalid("commercial_amount_vnd", exc.message, exc.code)
                if data.get("party_id") is None:
                    invalid("party_id", "Số dư thương mại cần đối tác.")
            posted = data["status"] == "posted" and not deleted
            if posted and not data["lines"]:
                invalid("lines", "Phiếu ghi sổ cần ít nhất một dòng hàng.")
            if posted and data["entry_type"] in {"opening", "adjustment"} and not data.get("note"):
                invalid("note", "Tồn đầu/điều chỉnh cần ghi căn cứ hoặc lý do.")
            directions = set()
            transfer = defaultdict(int)
            directional_totals = defaultdict(int)
            for index, line in enumerate(data["lines"]):
                prefix = f"lines.{index}"
                old_line = old["lines"][index] if old and index < len(old["lines"]) else {}
                for field, resource in (("product_id", "products"), ("warehouse_id", "warehouses")):
                    if posted and line.get(field) is None:
                        invalid(prefix + "." + field, "Dòng ghi sổ cần hàng hóa và vị trí.")
                    ref(line.get(field), resource, prefix + "." + field, old_line.get(field))
                quantity = line.get("quantity_kg")
                if quantity is None:
                    if posted:
                        invalid(prefix + ".quantity_kg", "Dòng ghi sổ cần kg dương.")
                else:
                    value = self._quantity(quantity, prefix + ".quantity_kg")
                    line["quantity_kg"] = kg_string(value)
                    directional_totals[line["direction"]] += value
                    transfer[line.get("product_id")] += value * (
                        1 if line["direction"] == "in" else -1
                    )
                directions.add(line["direction"])
            if posted:
                required = {
                    "receipt": {"in"},
                    "opening": {"in"},
                    "issue": {"out"},
                    "production": {"in", "out"},
                    "transfer": {"in", "out"},
                }
                if data["entry_type"] in required and directions != required[data["entry_type"]]:
                    invalid("lines", "Chiều nhập/xuất không phù hợp loại phiếu.")
                if data["entry_type"] == "transfer" and any(transfer.values()):
                    invalid("lines", "Chuyển kho phải cân bằng kg theo từng sản phẩm.")
                if (
                    data["entry_type"] == "production"
                    and directional_totals["in"] > directional_totals["out"]
                ):
                    invalid(
                        "lines",
                        "Tổng kg sản phẩm thu được vượt nguyên liệu đã ghi; cần ghi đủ nguồn nguyên liệu.",
                    )
        return references

    @staticmethod
    def _quantity(value, field, positive=True):
        try:
            quantity = parse_kg(value)
        except CoreError as exc:
            invalid(field, exc.message, exc.code)
        if quantity < 0 or (positive and quantity == 0):
            invalid(field, "Số kg phải dương." if positive else "Số kg không được âm.")
        return quantity

    @staticmethod
    def _scopes(data):
        return {
            (line["product_id"], line["warehouse_id"])
            for line in (data or {}).get("lines", [])
            if line.get("product_id") and line.get("warehouse_id")
        }

    @staticmethod
    def _write_movements(conn, data):
        grouped, line_numbers = defaultdict(int), defaultdict(list)
        for index, line in enumerate(data["lines"]):
            key = (line["product_id"], line["warehouse_id"], line["direction"])
            grouped[key] = checked_int64(grouped[key] + parse_kg(line["quantity_kg"]))
            line_numbers[key].append(index + 1)
        for (product, warehouse, direction), quantity in sorted(grouped.items()):
            # Consume before producing even when production uses the same stock scope.
            phase = "0" if direction == "out" else "1"
            movement_id = str(
                uuid.uuid5(
                    uuid.UUID(data["id"]), f"{data['version']}:{product}:{warehouse}:{direction}"
                )
            )
            conn.execute(
                insert(M).values(
                    id=movement_id,
                    entry_id=data["id"],
                    version=data["version"],
                    product_id=product,
                    warehouse_id=warehouse,
                    direction=direction,
                    delta_scaled=quantity * (1 if direction == "in" else -1),
                    occurred_on=data["occurred_on"],
                    order_key=data["order_key"] + phase,
                    entry_type=data["entry_type"],
                    line_numbers=canonical_json(line_numbers[(product, warehouse, direction)]),
                )
            )

    @staticmethod
    def _guard(conn, scopes):
        for product, warehouse in sorted(scopes):
            query = effective_movements().where(
                M.c.product_id == product, M.c.warehouse_id == warehouse
            )
            rows = conn.execute(
                query.order_by(M.c.occurred_on, M.c.order_key, M.c.entry_id)
            ).mappings()
            try:
                assert_nonnegative(
                    (
                        StockPoint(
                            row.entry_id,
                            date.fromisoformat(row.occurred_on),
                            row.order_key,
                            row.delta_scaled,
                        )
                        for row in rows
                    ),
                    scope=f"{product}/{warehouse}",
                )
            except CoreError as exc:
                if exc.code == "STOCK_NEGATIVE":
                    related = exc.details.get("related_entry_id")
                    detail = (
                        conn.execute(
                            effective_movements().where(
                                M.c.entry_id == related,
                                M.c.product_id == product,
                                M.c.warehouse_id == warehouse,
                                M.c.direction == "out",
                            )
                        )
                        .mappings()
                        .first()
                    )
                    exc.details.update(
                        product_id=product,
                        warehouse_id=warehouse,
                        shortage_kg=kg_string(-parse_kg(exc.details["balance_kg"])),
                        line_numbers=json.loads(detail.line_numbers) if detail else [],
                    )
                    exc.field_errors = [
                        {
                            "field": f"lines.{n - 1}.quantity_kg",
                            "code": exc.code,
                            "message": f"Dòng {n}: thiếu {exc.details['shortage_kg']} kg tại phiếu {related}.",
                        }
                        for n in exc.details["line_numbers"]
                    ]
                raise

    def movements(self, *, actor, page=1, page_size=50, filters=None):
        checked_page(page, page_size)
        filters = filters or {}
        allowed = {"from_on", "through_on", "product_id", "warehouse_id", "entry_id", "entry_type"}
        if not isinstance(filters, dict) or set(filters) - allowed:
            invalid("filters", "Bộ lọc ledger không hợp lệ.")
        query = effective_movements()
        for key, value in filters.items():
            if not isinstance(value, str):
                invalid("filters." + key, "Bộ lọc phải là chuỗi.")
            if key in {"from_on", "through_on"}:
                try:
                    day(value)
                except (ValueError, TypeError):
                    invalid("filters." + key, "Ngày không hợp lệ.")
                query = query.where(
                    M.c.occurred_on >= value if key == "from_on" else M.c.occurred_on <= value
                )
            else:
                query = query.where(M.c[key] == value)
        with self._snapshot(actor) as conn:
            conn.exec_driver_sql("BEGIN")
            self._authorize(conn, actor)
            total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(M.c.occurred_on, M.c.order_key, M.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            items = [
                {
                    key: row[key]
                    for key in (
                        "id",
                        "entry_id",
                        "version",
                        "product_id",
                        "warehouse_id",
                        "occurred_on",
                        "order_key",
                        "entry_type",
                        "direction",
                    )
                }
                | {
                    "delta_kg": kg_string(row.delta_scaled),
                    "line_numbers": json.loads(row.line_numbers),
                }
                for row in rows
            ]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
