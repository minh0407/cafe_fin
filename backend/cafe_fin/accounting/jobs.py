"""Bounded background phases, immutable confirmation and atomic publication."""

from __future__ import annotations

import csv
import json
import os
from decimal import Decimal
from itertools import islice

from sqlalchemy import bindparam, func, insert, select, update

from cafe_fin.core.auth import Principal
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import (
    ManifestRow,
    manifest_rows,
    manifests,
    receipts,
    visibility_predicate,
)
from cafe_fin.core.time import utc_now

from . import parsers
from . import schema as s
from .exporting import write_xlsx
from .service import (
    ATTEMPTS,
    AccountingService,
    _audit,
    _batch,
    _book,
    _touch_data,
    effective_decision,
    eligible,
    identity,
    published_target,
    scaled_cells,
    visible,
)
from .validation import fingerprint, normalize_value, safe_export_text

CHUNK = 500


def _chunked(iterator, size=CHUNK):
    while rows := list(islice(iterator, size)):
        yield rows


class AccountingJobs:
    def __init__(self, runtime):
        self.rt = runtime
        self.service = AccountingService(runtime)

    def run(self, context, payload):
        with self.rt.reader() as conn:
            task = dict(
                conn.execute(select(s.tasks).where(s.tasks.c.id == payload["task_id"]))
                .mappings()
                .one()
            )
            if task["kind"] != "accounting.export":
                batch = _batch(conn, task["entity_id"])
                if batch["active_task_id"] != task["id"]:
                    raise CoreError(
                        "JOB_SUPERSEDED",
                        "Tác vụ đã được thay bằng revision mới; không đọc lại staging mới.",
                        409,
                    )
        actor_data = json.loads(task["actor_json"])
        actor_data["permissions"] = tuple(actor_data["permissions"])
        actor = Principal(**actor_data)
        authorize = self.service.authorize(actor)
        self.rt.writer.run(authorize)
        handler = {
            "accounting.parse": self.parse,
            "accounting.validate": self.validate,
            "accounting.commit": self.commit,
            "accounting.export": self.export,
        }[task["kind"]]
        try:
            handler(context, actor, task["entity_id"], json.loads(task["payload_json"]))
        except parsers.ParserError as exc:
            raise CoreError(exc.code, str(exc), 422) from None
        except OSError:
            raise CoreError(
                "STORAGE_UNAVAILABLE",
                "Không đủ dung lượng hoặc không truy cập được ổ local; giữ checkpoint để tiếp tục.",
                503,
            ) from None

    def _effect(self, actor, callback):
        def authorized(conn):
            self.service.authorize(actor)(conn)
            return callback(conn)

        return authorized

    def _load(self, batch_id):
        with self.rt.reader() as conn:
            batch = _batch(conn, batch_id)
            book = _book(conn, batch["book_id"])
        return batch, book

    def parse(self, context, actor, batch_id, payload):
        batch, _ = self._load(batch_id)
        file = self.rt.files.get(batch["file_id"])
        # Verify actual source hash on every resume; neither parser nor exporter saves it.
        with self.rt.files.read(file.id):
            path = self.rt.root.resolve_key(file.relative_key)
            self.rt.root.check_writable(max(256 * 1024**2, file.size * 12))
            source_manifest = parsers.manifest(path, file.original_name)
            checkpoint = context.checkpoint()
            skip = checkpoint.get("parsed", 0)
            profile = json.loads(batch["profile_json"])
            ordinal = 0
            for chunk in _chunked(parsers.iter_rows(path, file.original_name, profile)):
                context.check_cancelled()
                ordinal += len(chunk)
                if ordinal <= skip:
                    continue
                if ordinal - len(chunk) < skip:
                    raise CoreError(
                        "PARSE_CHECKPOINT_INVALID",
                        "Checkpoint parse không khớp nguồn bất biến.",
                        409,
                    )
                records = [
                    dict(
                        batch_id=batch_id,
                        row_id=f"{r.sheet_id}:{r.source_row}",
                        source_sheet=r.sheet_id,
                        sheet_name=r.sheet_name,
                        source_row=r.source_row,
                        revision=1,
                        raw_json=canonical_json(r.values),
                        metadata_json=canonical_json(r.metadata),
                        formulas_json=canonical_json(r.formulas),
                        edited_json="{}",
                        typed_json="{}",
                        issues_json="[]",
                        valid=0,
                        duplicate_count=0,
                    )
                    for r in chunk
                ]

                def effect(conn):
                    conn.execute(insert(s.stage), records)
                    conn.execute(
                        update(s.batches)
                        .where(s.batches.c.id == batch_id)
                        .values(
                            state="PARSING",
                            source_manifest_json=canonical_json(source_manifest),
                            counts_json=canonical_json({"source_rows": ordinal, "parsed": ordinal}),
                            updated_at=utc_now(),
                        )
                    )
                    return {"parsed": ordinal}

                context.commit_chunk(
                    f"parse:{ordinal}",
                    {"end": ordinal, "file_hash": batch["file_hash"]},
                    checkpoint={"parsed": ordinal},
                    counts={"parsed": ordinal},
                    phase="parse",
                    effect=self._effect(actor, effect),
                )

            def finish(conn):
                conn.execute(
                    update(s.batches)
                    .where(s.batches.c.id == batch_id)
                    .values(
                        state="READY_FOR_MAPPING",
                        source_manifest_json=canonical_json(source_manifest),
                        counts_json=canonical_json({"source_rows": ordinal, "parsed": ordinal}),
                        updated_at=utc_now(),
                    )
                )
                return {"source_rows": ordinal}

            context.finalize(self._effect(actor, finish))

    def _stage_values(self, conn, batch, book, row):
        from .formulas import FormulaError, LiteralCell

        mapping = json.loads(batch["mapping_json"])
        raw, edited = json.loads(row["raw_json"]), json.loads(row["edited_json"])
        meta, formulas = json.loads(row["metadata_json"]), json.loads(row["formulas_json"])
        values = {column: raw.get(source) for column, source in mapping.items()} | edited
        date_cells = {
            column: meta.get("date_cells", {}).get(source)
            for column, source in mapping.items()
            if source in meta.get("date_cells", {}) and column not in edited
        }
        mapped_formulas = {
            column: formulas[source]
            for column, source in mapping.items()
            if source in formulas and column not in edited
        }
        columns = {c["id"]: c for c in json.loads(book["columns_json"])}
        for column, source in mapping.items():
            if (
                column not in edited
                and source not in formulas
                and source in meta.get("numeric_cells", {})
                and columns[column]["kind"] in ("integer", "decimal", "money", "formula")
            ):
                values[column] = Decimal(meta["numeric_cells"][source])

        def resolver(reference):
            import re

            match = re.fullmatch("([A-Z]+)([1-9][0-9]*)", reference)
            source_col, source_row = match[1], int(match[2])
            target = (
                conn.execute(
                    select(s.stage).where(
                        s.stage.c.batch_id == batch["id"],
                        s.stage.c.source_sheet == row["source_sheet"],
                        s.stage.c.source_row == source_row,
                    )
                )
                .mappings()
                .first()
            )
            if target is None:
                raise FormulaError(
                    "FORMULA_REFERENCE", "Tham chiếu nằm ngoài phạm vi đã chọn; không coi là trống."
                )
            mapped = next((c for c, src in mapping.items() if src == source_col), None)
            if mapped is None:
                raise FormulaError(
                    "FORMULA_REFERENCE",
                    "Cột tham chiếu chưa được ánh xạ kiểu; cần mapping rõ trước khi tính.",
                )
            target_raw, target_edit, target_formulas = (
                json.loads(target.raw_json),
                json.loads(target.edited_json),
                json.loads(target.formulas_json),
            )
            if mapped and mapped in target_edit:
                value = target_edit[mapped]
            elif source_col in target_formulas:
                info = target_formulas[source_col]
                if not info.get("formula_text"):
                    raise FormulaError(
                        "FORMULA_UNSUPPORTED",
                        "Shared formula chưa có biểu thức riêng; cache không authoritative.",
                    )
                return info["formula_text"]
            else:
                value = target_raw.get(source_col)
                target_metadata = json.loads(target.metadata_json)
                if source_col in target_metadata.get("numeric_cells", {}) and columns[mapped][
                    "kind"
                ] in ("integer", "decimal", "money", "formula"):
                    value = Decimal(target_metadata["numeric_cells"][source_col])
            if (
                mapped
                and columns[mapped]["kind"] in ("integer", "decimal", "money", "formula")
                and value not in ("", None)
            ):
                normalized, _ = normalize_value(
                    value, columns[mapped], json.loads(batch["profile_json"])
                )
                return Decimal(normalized)
            return LiteralCell(value)

        typed, errors, calculation = self.service.normalize_row(
            conn,
            book,
            values,
            profile=json.loads(batch["profile_json"]),
            metadata={"date_cells": date_cells, "epoch": meta.get("epoch", "1900")},
            formulas=mapped_formulas,
            resolver=resolver,
            current_row=row["source_row"],
        )
        for column, info in mapped_formulas.items():
            if not info.get("formula_text"):
                typed[column] = None
                errors.append(
                    dict(
                        column_id=column,
                        code="FORMULA_UNSUPPORTED",
                        message="Shared formula không có biểu thức riêng; chưa xác nhận cache.",
                        severity="error",
                        raw_value=str(info.get("cached_value"))[:256],
                        suggestion="Nhập giá trị rõ ràng hoặc công thức được hỗ trợ.",
                    )
                )
        for error in errors:
            source_col = mapping.get(error["column_id"], "")
            error.update(
                source_sheet=row["source_sheet"],
                sheet_name=row["sheet_name"],
                source_row=row["source_row"],
                source_column=source_col,
                cell=f"{source_col}{row['source_row']}",
                validation_revision=batch["revision"],
                resolved=False,
            )
        return typed, errors, calculation

    def validate(self, context, actor, batch_id, payload):
        batch, book = self._load(batch_id)
        if payload["revision"] != batch["revision"]:
            raise CoreError("VALIDATION_STALE", "Revision kiểm tra đã thay đổi.", 409)
        semantic = json.loads(book["semantics_json"])
        checkpoint = context.checkpoint()
        last = checkpoint.get("last", "") if checkpoint.get("phase") == "normalize" else ""
        normalized = checkpoint.get("normalized", 0)
        if checkpoint.get("phase") not in ("deduplicate", "done"):
            while True:
                context.check_cancelled()
                with self.rt.reader() as conn:
                    rows = (
                        conn.execute(
                            select(s.stage)
                            .where(
                                s.stage.c.batch_id == batch_id,
                                s.stage.c.row_id > last,
                                published_target().is_(None),
                            )
                            .order_by(s.stage.c.row_id)
                            .limit(CHUNK)
                        )
                        .mappings()
                        .all()
                    )
                    if not rows:
                        break
                    normalized_rows = []
                    issue_rows = []
                    for row in rows:
                        typed, errors, calculation = self._stage_values(conn, batch, book, row)
                        # Preserve raw source-keyed formula metadata and calculated provenance separately.
                        metadata = json.loads(row.metadata_json)
                        metadata["calculations"] = calculation
                        normalized_rows.append(
                            dict(
                                _row_id=row.row_id,
                                typed_json=canonical_json(typed),
                                issues_json=canonical_json(errors),
                                metadata_json=canonical_json(metadata),
                                valid=0 if errors else 1,
                                fingerprint=fingerprint(typed),
                                candidate_key=fingerprint(
                                    typed, semantic.get("duplicate_columns", [])
                                ),
                                business_key=fingerprint(
                                    typed, semantic.get("business_key_columns", [])
                                ),
                                validation_revision=batch["revision"],
                            )
                        )
                        issue_rows.extend(
                            dict(
                                id=identity(),
                                batch_id=batch_id,
                                row_id=row.row_id,
                                column_id=e["column_id"],
                                validation_revision=batch["revision"],
                                resolved=0,
                                issue_json=canonical_json(e),
                            )
                            for e in errors
                        )
                last = rows[-1].row_id
                normalized += len(rows)

                def effect(conn):
                    conn.execute(
                        update(s.issues)
                        .where(
                            s.issues.c.batch_id == batch_id,
                            s.issues.c.row_id.in_([r.row_id for r in rows]),
                        )
                        .values(resolved=1)
                    )
                    if issue_rows:
                        conn.execute(insert(s.issues), issue_rows)
                    fields = {key: bindparam(key) for key in normalized_rows[0] if key != "_row_id"}
                    conn.execute(
                        update(s.stage)
                        .where(
                            s.stage.c.batch_id == batch_id, s.stage.c.row_id == bindparam("_row_id")
                        )
                        .values(**fields),
                        normalized_rows,
                    )
                    return {"normalized": normalized}

                context.commit_chunk(
                    "normalize:" + last,
                    {"revision": batch["revision"], "last": last},
                    checkpoint={"phase": "normalize", "last": last, "normalized": normalized},
                    counts={"validated": normalized},
                    phase="normalize",
                    effect=self._effect(actor, effect),
                )
        # Candidate matching is set-based per bounded chunk, never one DB query per row.
        checkpoint = context.checkpoint()
        last = checkpoint.get("last", "") if checkpoint.get("phase") == "deduplicate" else ""
        deduped = checkpoint.get("deduped", 0)
        while True:
            context.check_cancelled()
            with self.rt.reader() as conn:
                rows = (
                    conn.execute(
                        select(s.stage)
                        .where(
                            s.stage.c.batch_id == batch_id,
                            s.stage.c.row_id > last,
                            published_target().is_(None),
                        )
                        .order_by(s.stage.c.row_id)
                        .limit(CHUNK)
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    break
                matches = {}
                for field in ("fingerprint", "candidate_key", "business_key"):
                    keys = {r[field] for r in rows if r[field]}
                    extra = [published_target().is_(None)]
                    if field == "business_key":
                        from sqlalchemy import or_

                        extra = [
                            published_target().is_(None),
                            or_(effective_decision().is_(None), effective_decision() != "skip"),
                        ]
                    stage_counts = (
                        dict(
                            conn.execute(
                                select(s.stage.c[field], func.count())
                                .where(
                                    s.stage.c.batch_id == batch_id,
                                    s.stage.c[field].in_(keys),
                                    *extra,
                                )
                                .group_by(s.stage.c[field])
                            ).all()
                        )
                        if keys
                        else {}
                    )
                    db_counts = (
                        dict(
                            conn.execute(
                                select(s.entries.c[field], func.count())
                                .where(
                                    s.entries.c.book_id == book["id"],
                                    s.entries.c[field].in_(keys),
                                    s.entries.c.deleted_at.is_(None),
                                    visible(),
                                )
                                .group_by(s.entries.c[field])
                            ).all()
                        )
                        if keys
                        else {}
                    )
                    matches[field] = (stage_counts, db_counts)
                revised = []
                for row in rows:
                    duplicates, conflict = 0, False
                    for field, (in_file, in_db) in matches.items():
                        key = row[field]
                        count = max(0, in_file.get(key, 0) - 1) + in_db.get(key, 0) if key else 0
                        if field == "business_key" and count and row.decision != "skip":
                            conflict = True
                        else:
                            duplicates = max(duplicates, count)
                    errors = [
                        e
                        for e in json.loads(row.issues_json)
                        if e["code"] != "BUSINESS_KEY_CONFLICT"
                    ]
                    if conflict:
                        errors.append(
                            dict(
                                column_id="",
                                code="BUSINESS_KEY_CONFLICT",
                                message="Khóa nghiệp vụ đã được cấu hình bị trùng. Cần sửa khóa hoặc loại dòng; không ghi đè.",
                                severity="error",
                                source_sheet=row.source_sheet,
                                source_row=row.source_row,
                                source_column="",
                                cell=str(row.source_row),
                                suggestion="Kiểm tra khóa nghiệp vụ đã chọn.",
                            )
                        )
                    revised.append((row.row_id, duplicates, errors))
            last = rows[-1].row_id
            deduped += len(rows)

            def effect(conn):
                values = [
                    {
                        "_row_id": row_id,
                        "duplicate_count": duplicates,
                        "issues_json": canonical_json(errors),
                        "valid": 0 if errors else 1,
                    }
                    for row_id, duplicates, errors in revised
                ]
                conn.execute(
                    update(s.stage)
                    .where(s.stage.c.batch_id == batch_id, s.stage.c.row_id == bindparam("_row_id"))
                    .values(
                        duplicate_count=bindparam("duplicate_count"),
                        issues_json=bindparam("issues_json"),
                        valid=bindparam("valid"),
                    ),
                    values,
                )
                conflicts = [
                    dict(
                        id=identity(),
                        batch_id=batch_id,
                        row_id=row_id,
                        column_id=e.get("column_id", ""),
                        validation_revision=batch["revision"],
                        resolved=0,
                        issue_json=canonical_json(e),
                    )
                    for row_id, _, errors in revised
                    for e in errors
                    if e["code"] == "BUSINESS_KEY_CONFLICT"
                ]
                if conflicts:
                    conn.execute(insert(s.issues), conflicts)
                return {"deduplicated": deduped}

            context.commit_chunk(
                "dedup:" + last,
                {"last": last, "revision": batch["revision"]},
                checkpoint={
                    "phase": "deduplicate",
                    "last": last,
                    "normalized": normalized,
                    "deduped": deduped,
                },
                counts={"validated": normalized, "deduplicated": deduped},
                phase="duplicates",
                effect=self._effect(actor, effect),
            )

        def finish(conn):
            counts = self.counts(conn, batch_id)
            token = identity()
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    state="READY_FOR_CONFIRM",
                    validation_token=token,
                    validated_revision=batch["revision"],
                    counts_json=canonical_json(counts),
                    updated_at=utc_now(),
                )
            )
            _audit(
                conn,
                actor,
                "batch",
                batch_id,
                "validate",
                after={"revision": batch["revision"], "counts": counts},
            )
            return counts

        context.finalize(self._effect(actor, finish))

    @staticmethod
    def counts(conn, batch_id):
        source = conn.execute(
            select(func.count()).select_from(s.stage).where(s.stage.c.batch_id == batch_id)
        ).scalar_one()

        def count(*pred):
            return conn.execute(
                select(func.count())
                .select_from(s.stage)
                .where(s.stage.c.batch_id == batch_id, *pred)
            ).scalar_one()

        published = count(published_target().is_not(None))
        valid = count(s.stage.c.valid == 1)
        return dict(
            source_rows=source,
            validated=source,
            valid=valid,
            invalid=source - valid,
            potential_duplicates=count(s.stage.c.duplicate_count > 0),
            conflicts=count(s.stage.c.issues_json.contains("BUSINESS_KEY_CONFLICT")),
            excluded=count(effective_decision() == "skip"),
            staged_committed_rows=published,
            published_rows=published,
            pending=0,
            eligible=count(*eligible(batch_id)[1:]),
        )

    def commit(self, context, actor, batch_id, payload):
        batch, book = self._load(batch_id)
        manifest_id = payload["manifest_id"]
        with self.rt.reader() as conn:
            manifest = dict(
                conn.execute(select(manifests).where(manifests.c.id == manifest_id))
                .mappings()
                .one()
            )
        pins = json.loads(manifest["pins_json"])
        # Conservative headroom for snapshot JSON, pending entries, cell indexes,
        # WAL and one derived export, beyond originals/staging already on disk.
        if manifest["state"] == "BUILDING":
            width = max(1, len(pins["book_snapshot"]["columns"]))
            self.rt.root.check_writable(
                max(512 * 1024**2, manifest["expected_count"] * (2048 + width * 768))
            )
        if manifest["state"] == "BUILDING":
            offset = manifest["row_count"]
            while offset < manifest["expected_count"]:
                context.check_cancelled()
                with self.rt.reader() as conn:
                    # Batch is locked until finalization: paging cannot change underneath snapshot.
                    previous = (
                        conn.execute(
                            select(manifest_rows.c.source_row_id).where(
                                manifest_rows.c.manifest_id == manifest_id,
                                manifest_rows.c.ordinal == offset - 1,
                            )
                        ).scalar_one_or_none()
                        if offset
                        else ""
                    )
                    selected = (
                        conn.execute(
                            select(
                                *[c for c in s.stage.c if c.name != "decision"],
                                effective_decision().label("decision"),
                            )
                            .where(*eligible(batch_id), s.stage.c.row_id > (previous or ""))
                            .order_by(s.stage.c.row_id)
                            .limit(CHUNK)
                        )
                        .mappings()
                        .all()
                    )
                    snapshots = []
                    for row in selected:
                        typed = json.loads(row.typed_json)
                        snapshots.append(
                            ManifestRow(
                                row.row_id,
                                dict(
                                    source_sheet=row.source_sheet,
                                    source_row=row.source_row,
                                    revision=row.revision,
                                    raw_values=json.loads(row.raw_json),
                                    edited_values=json.loads(row.edited_json),
                                    typed_values=typed,
                                    formulas=json.loads(row.metadata_json).get("calculations", {}),
                                    raw_formulas=json.loads(row.formulas_json),
                                    metadata=json.loads(row.metadata_json),
                                    fingerprint=row.fingerprint,
                                    candidate_key=row.candidate_key,
                                    business_key=row.business_key,
                                    decision=row.decision,
                                    duplicate_count=row.duplicate_count,
                                ),
                            )
                        )
                if not snapshots:
                    raise CoreError("SELECTION_CHANGED", "Tập xác nhận không còn đủ dòng.", 409)
                start = offset
                offset += len(snapshots)

                def effect(conn):
                    ATTEMPTS.append_manifest_chunk(
                        conn, manifest_id, expected_start=start, rows=snapshots
                    )
                    return {"snapshot_rows": offset}

                context.commit_chunk(
                    f"snapshot:{start}",
                    {"manifest": manifest_id, "start": start},
                    checkpoint={"snapshot_rows": offset},
                    counts={"snapshot_rows": offset},
                    phase="snapshot",
                    effect=self._effect(actor, effect),
                )

            def seal(conn):
                self.service.authorize(actor)(conn)
                fingerprint = ATTEMPTS.seal_manifest(conn, manifest_id)
                attempt_id = ATTEMPTS.create_attempt(conn, manifest_id, fingerprint=fingerprint)
                conn.execute(
                    update(s.batches)
                    .where(s.batches.c.id == batch_id)
                    .values(attempt_id=attempt_id)
                )
                return attempt_id

            # Lease check is included in the effect transaction by commit_chunk.
            context.commit_chunk(
                "seal",
                {"manifest_id": manifest_id},
                checkpoint={"sealed": True},
                counts={"snapshot_rows": manifest["expected_count"]},
                phase="seal",
                effect=self._effect(actor, seal),
            )
        batch, book = self._load(batch_id)
        attempt_id = batch["attempt_id"]
        if attempt_id is None:
            # Crash after seal commit must have attempt_id in same transaction.
            raise CoreError("ATTEMPT_MISSING", "Snapshot chưa liên kết lượt nhập.", 409)
        with self.rt.reader() as conn:
            progress = ATTEMPTS.status(conn, attempt_id)
        start = progress["checkpoint"]
        columns = pins["book_snapshot"]["columns"]
        while start < progress["expected_count"]:
            context.check_cancelled()
            count = min(CHUNK, progress["expected_count"] - start)
            chunk_start = start

            def pending(conn, attempt, rows):
                current_book = _book(conn, book["id"])
                base = current_book["next_logical_row"]
                now = utc_now()
                data, cell_data = [], []
                for offset, row in enumerate(rows):
                    v = row.snapshot["typed_values"]
                    data.append(
                        dict(
                            id=row.target_id,
                            book_id=book["id"],
                            version=1,
                            logical_row=base + offset,
                            schema_revision=pins["schema_revision"],
                            values_json=canonical_json(v),
                            formulas_json=canonical_json(row.snapshot.get("formulas", {})),
                            fingerprint=row.snapshot["fingerprint"],
                            candidate_key=row.snapshot.get("candidate_key"),
                            business_key=row.snapshot.get("business_key"),
                            import_attempt_id=attempt,
                            batch_id=batch_id,
                            source_row_id=row.source_row_id,
                            created_by=actor.id,
                            updated_by=actor.id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    cell_data.extend(scaled_cells(row.target_id, book["id"], v, columns))
                conn.execute(insert(s.entries), data)
                if cell_data:
                    conn.execute(insert(s.cells), cell_data)
                conn.execute(
                    update(s.books)
                    .where(s.books.c.id == book["id"])
                    .values(next_logical_row=base + len(rows))
                )
                _audit(
                    conn,
                    actor,
                    "attempt",
                    attempt,
                    "pending_chunk",
                    after={"start": chunk_start, "count": count},
                )

            def effect(conn):
                ATTEMPTS.commit_chunk(
                    conn,
                    attempt_id,
                    chunk_id=str(chunk_start),
                    start=chunk_start,
                    count=count,
                    write_pending=pending,
                )
                return {"staged_committed_rows": chunk_start + count}

            start += count
            context.commit_chunk(
                "commit:" + str(chunk_start),
                {"attempt_id": attempt_id, "start": chunk_start, "count": count},
                checkpoint={"staged_committed_rows": start},
                counts={"staged_committed_rows": start, "published_rows": 0},
                phase="commit_pending",
                effect=self._effect(actor, effect),
            )

        def publish(conn):
            current = _book(conn, book["id"])
            if current["schema_revision"] != pins["schema_revision"]:
                raise CoreError("SCHEMA_STALE", "Schema đổi trong lúc import; không công bố.", 409)
            # Recheck explicit keys against live published CRUD, set-wise before publication.
            own = s.entries.alias("own")
            prior = s.entries.alias("prior")
            conflicts = conn.execute(
                select(own.c.id)
                .select_from(
                    own.join(
                        prior,
                        (own.c.business_key == prior.c.business_key)
                        & (own.c.book_id == prior.c.book_id),
                    )
                )
                .where(
                    own.c.import_attempt_id == attempt_id,
                    own.c.business_key.is_not(None),
                    prior.c.import_attempt_id.is_distinct_from(attempt_id),
                    prior.c.deleted_at.is_(None),
                    visibility_predicate(prior.c.import_attempt_id),
                )
                .limit(1)
            ).first()
            if conflicts:
                raise CoreError(
                    "BUSINESS_KEY_CONFLICT",
                    "Có bản ghi cùng khóa nghiệp vụ vừa thay đổi. Không công bố phần pending.",
                    409,
                )
            actual = conn.execute(
                select(func.count())
                .select_from(s.entries)
                .where(s.entries.c.import_attempt_id == attempt_id)
            ).scalar_one()
            if actual != progress["expected_count"]:
                raise CoreError(
                    "IMPORT_COUNT_MISMATCH", "Số dòng pending không khớp manifest.", 409
                )
            committed = conn.execute(
                select(func.coalesce(func.sum(receipts.c.count), 0)).where(
                    receipts.c.attempt_id == attempt_id
                )
            ).scalar_one()
            if committed != actual:
                raise CoreError(
                    "IMPORT_RECEIPT_MISMATCH", "Số dòng receipt không khớp dữ liệu pending.", 409
                )
            result = ATTEMPTS.publish(conn, attempt_id)
            # No million-row UPDATE at publication: target identity derives from published claims.
            _touch_data(conn, book["id"])
            counts = json.loads(_batch(conn, batch_id)["counts_json"])
            counts["published_rows"] = counts.get("published_rows", 0) + result["published_rows"]
            counts["staged_committed_rows"] = counts["published_rows"]
            counts["pending"] = 0
            counts["eligible"] = max(0, counts.get("eligible", 0) - result["published_rows"])
            conn.execute(
                update(s.batches)
                .where(s.batches.c.id == batch_id)
                .values(
                    state="COMPLETED"
                    if counts["published_rows"] + counts["excluded"] == counts["source_rows"]
                    else "PARTIALLY_COMMITTED",
                    counts_json=canonical_json(counts),
                    updated_at=utc_now(),
                )
            )
            _audit(
                conn,
                actor,
                "attempt",
                attempt_id,
                "publish",
                after={"count": result["published_rows"], "manifest_id": manifest_id},
            )
            return {"published_rows": result["published_rows"]}

        context.finalize(self._effect(actor, publish))

    def export(self, context, actor, export_id, payload):
        with self.rt.reader() as conn:
            task = dict(
                conn.execute(select(s.exports).where(s.exports.c.id == export_id)).mappings().one()
            )
            book = _book(conn, task["book_id"])
        format_name = task["format"]
        path = self.rt.root.resolve_key(f"imports/{export_id}.derived.{format_name}.part")
        # Restart exports re-render from the pinned revision, not append an ambiguous partial ZIP.
        columns = json.loads(book["columns_json"])
        count = 0
        try:
            with self.rt.reader() as conn:
                conn.exec_driver_sql("BEGIN")
                pinned = _book(conn, book["id"])
                if (
                    pinned["data_revision"] != task["data_revision"]
                    or pinned["schema_revision"] != task["schema_revision"]
                ):
                    raise CoreError(
                        "EXPORT_REVISION_STALE",
                        "Dữ liệu đã đổi trước lúc xuất. Tạo yêu cầu xuất mới.",
                        409,
                    )
                if payload.get("dataset") == "issues":
                    batch = _batch(conn, payload["batch_id"], actor)
                    if (
                        batch["revision"] != payload["revision"]
                        or batch["validation_token"] != payload["validation_token"]
                    ):
                        raise CoreError(
                            "EXPORT_REVISION_STALE",
                            "Lỗi đã thay đổi sau yêu cầu xuất; tạo yêu cầu mới.",
                            409,
                        )
                    fields = (
                        "source_sheet",
                        "source_row",
                        "source_column",
                        "column_id",
                        "cell",
                        "code",
                        "message",
                        "severity",
                        "raw_value",
                        "suggestion",
                        "validation_revision",
                    )
                    columns = [dict(id=f, name=f, kind="text") for f in fields]
                    query = (
                        select(s.issues.c.issue_json)
                        .where(s.issues.c.batch_id == batch["id"], s.issues.c.resolved == 0)
                        .order_by(s.issues.c.row_id, s.issues.c.id)
                    )
                else:
                    query = (
                        select(s.entries.c.values_json)
                        .where(
                            s.entries.c.book_id == book["id"],
                            s.entries.c.deleted_at.is_(None),
                            visible(),
                        )
                        .order_by(s.entries.c.logical_row)
                    )
                if format_name == "csv":
                    with path.open("w", encoding="utf-8-sig", newline="") as output:
                        writer = csv.writer(output)
                        writer.writerow([safe_export_text(c["name"]) for c in columns])
                        for encoded in conn.execute(query).scalars():
                            v = json.loads(encoded)
                            writer.writerow(
                                [
                                    safe_export_text(v.get(c["id"]))
                                    if c["kind"] in ("text", "choice")
                                    else v.get(c["id"])
                                    for c in columns
                                ]
                            )
                            count += 1
                            if count % CHUNK == 0:
                                context.check_cancelled()
                        output.flush()
                        os.fsync(output.fileno())
                else:
                    count = write_xlsx(
                        path,
                        columns,
                        (json.loads(encoded) for encoded in conn.execute(query).scalars()),
                        context.check_cancelled,
                    )
            context.check_cancelled()
            with path.open("rb") as source:
                stored = self.rt.files.put(
                    source,
                    category="reports",
                    original_name=f"accounting-derived-exact-{export_id}.{format_name}",
                    actor=actor.id,
                    request_key="accounting-export-file:" + export_id,
                    authorize=self.service.authorize(actor),
                )

            def finish(conn):
                conn.execute(
                    update(s.exports).where(s.exports.c.id == export_id).values(file_id=stored.id)
                )
                _audit(
                    conn,
                    actor,
                    "export",
                    export_id,
                    "complete",
                    after={
                        "file_id": stored.id,
                        "rows": count,
                        "data_revision": task["data_revision"],
                        "derived": True,
                        "numeric_encoding": "numeric_up_to_15_digits_else_exact_text",
                    },
                )
                return {"file_id": stored.id, "rows": count}

            context.finalize(self._effect(actor, finish))
        finally:
            path.unlink(missing_ok=True)
