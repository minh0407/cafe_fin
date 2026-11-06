"""Transactional primitives for immutable, bounded import attempts.

Call only inside WriteCoordinator.run/execute. This module never commits a connection.
Domain rows must have a nullable import_attempt_id and use visibility_predicate everywhere.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    exists,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.sql.elements import ColumnElement

from .errors import CoreError
from .modules import Migration
from .time import utc_now

MAX_CHUNK_ROWS = 500
metadata = MetaData()
manifests = Table(
    "core_import_manifests",
    metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("pins_json", Text, nullable=False),
    Column("expected_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False, default=0),
    Column("fingerprint", String, nullable=False),
    Column("state", String, nullable=False),
    Column("created_at", String, nullable=False),
    CheckConstraint("expected_count >= 0 AND row_count >= 0 AND row_count <= expected_count"),
    CheckConstraint("state IN ('BUILDING','SEALED')"),
)
manifest_rows = Table(
    "core_import_manifest_rows",
    metadata,
    Column("manifest_id", String, ForeignKey(manifests.c.id), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("source_row_id", String, nullable=False),
    Column("snapshot_json", Text, nullable=False),
    Column("row_hash", String, nullable=False),
    UniqueConstraint("manifest_id", "source_row_id"),
    CheckConstraint("ordinal >= 0"),
)
attempts = Table(
    "core_import_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("manifest_id", String, ForeignKey(manifests.c.id), nullable=False, unique=True),
    Column("job_id", String, nullable=False),
    Column("state", String, nullable=False),
    Column("expected_count", Integer, nullable=False),
    Column("staged_committed_rows", Integer, nullable=False, default=0),
    Column("published_rows", Integer, nullable=False, default=0),
    Column("checkpoint", Integer, nullable=False, default=0),
    Column("created_at", String, nullable=False),
    Column("published_at", String),
    CheckConstraint("state IN ('PENDING','FAILED','CANCELLED','RECOVERABLE','PUBLISHED')"),
    CheckConstraint("staged_committed_rows >= 0 AND staged_committed_rows <= expected_count"),
    CheckConstraint("published_rows = 0 OR published_rows = expected_count"),
    CheckConstraint("checkpoint = staged_committed_rows"),
    CheckConstraint(
        "(state = 'PUBLISHED' AND published_rows = expected_count AND checkpoint = expected_count) OR (state != 'PUBLISHED' AND published_rows = 0)"
    ),
)
claims = Table(
    "core_import_claims",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("source_row_id", String, primary_key=True),
    Column("attempt_id", String, ForeignKey(attempts.c.id), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("target_id", String, nullable=False, unique=True),
    UniqueConstraint("attempt_id", "ordinal"),
)
receipts = Table(
    "core_import_receipts",
    metadata,
    Column("attempt_id", String, ForeignKey(attempts.c.id), primary_key=True),
    Column("chunk_id", String, primary_key=True),
    Column("start", Integer, nullable=False),
    Column("count", Integer, nullable=False),
    Column("digest", String, nullable=False),
    Column("committed_at", String, nullable=False),
    UniqueConstraint("attempt_id", "start"),
    CheckConstraint("count > 0 AND count <= 500"),
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise CoreError(
            "IMPORT_SNAPSHOT_INVALID", "Dữ liệu snapshot không phải JSON hợp lệ."
        ) from exc


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _apply(conn: Connection) -> None:
    metadata.create_all(conn)
    # Enforce immutability in SQLite, including against accidental domain SQL updates.
    for name, statement in {
        "core_import_manifest_sealed_update": "BEFORE UPDATE ON core_import_manifests WHEN OLD.state = 'SEALED'",
        "core_import_manifest_delete": "BEFORE DELETE ON core_import_manifests",
        "core_import_row_update": "BEFORE UPDATE ON core_import_manifest_rows",
        "core_import_row_delete": "BEFORE DELETE ON core_import_manifest_rows",
        "core_import_row_sealed_insert": "BEFORE INSERT ON core_import_manifest_rows WHEN (SELECT state FROM core_import_manifests WHERE id = NEW.manifest_id) != 'BUILDING'",
        "core_import_attempt_pins_update": "BEFORE UPDATE ON core_import_attempts WHEN NEW.manifest_id != OLD.manifest_id OR NEW.job_id != OLD.job_id OR NEW.expected_count != OLD.expected_count",
        "core_import_receipt_update": "BEFORE UPDATE ON core_import_receipts",
        "core_import_receipt_delete": "BEFORE DELETE ON core_import_receipts",
        "core_import_claim_update": "BEFORE UPDATE ON core_import_claims",
    }.items():
        conn.exec_driver_sql(
            f"CREATE TRIGGER {name} {statement} BEGIN SELECT RAISE(ABORT, 'immutable import snapshot'); END"
        )


MIGRATIONS = (Migration("core_imports", 1, "immutable import manifests and attempts", _apply),)


@dataclass(frozen=True)
class ManifestRow:
    source_row_id: str
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class PendingImportRow:
    source_row_id: str
    target_id: str
    ordinal: int
    snapshot: Mapping[str, Any]


def visibility_predicate(attempt_id_column: ColumnElement[Any]) -> ColumnElement[bool]:
    """Use for list, detail, CRUD preconditions, sums, export and reporting queries."""
    return or_(
        attempt_id_column.is_(None),
        exists(
            select(1)
            .where(and_(attempts.c.id == attempt_id_column, attempts.c.state == "PUBLISHED"))
            .correlate_except(attempts)
        ),
    )


class ImportAttemptService:
    def create_manifest(
        self, conn: Connection, *, job_id: str, pins: Mapping[str, Any], expected_count: int
    ) -> str:
        """Server builds selection after authoritative validation; never accept client is_valid.

        pins must include revision/token pins plus mapping/decision snapshots. Raw, edited,
        typed values and source coordinates belong to each immutable row snapshot.
        """
        required = {
            "staging_revision",
            "mapping_revision",
            "decision_revision",
            "validation_token",
            "mapping_snapshot",
            "duplicate_decisions",
            "mode",
        }
        if not required.issubset(pins) or pins.get("mode") != "valid_rows_only":
            raise CoreError(
                "IMPORT_CONFIRM_PINS_INVALID", "Thiếu phiên bản hoặc lựa chọn xác nhận import."
            )
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count < 0
        ):
            raise CoreError("IMPORT_COUNT_INVALID", "Số dòng xác nhận không hợp lệ.")
        for key in ("staging_revision", "mapping_revision", "decision_revision"):
            if not isinstance(pins[key], int) or isinstance(pins[key], bool) or pins[key] < 1:
                raise CoreError("IMPORT_CONFIRM_PINS_INVALID", "Phiên bản xác nhận không hợp lệ.")
        if not isinstance(pins["validation_token"], str) or not pins["validation_token"]:
            raise CoreError(
                "IMPORT_CONFIRM_PINS_INVALID", "Thiếu kết quả kiểm tra hợp lệ của server."
            )
        identity = str(uuid4())
        encoded = _canonical(dict(pins))
        conn.execute(
            insert(manifests).values(
                id=identity,
                job_id=job_id,
                pins_json=encoded,
                expected_count=expected_count,
                row_count=0,
                fingerprint=_hash(encoded),
                state="BUILDING",
                created_at=utc_now(),
            )
        )
        return identity

    def append_manifest_chunk(
        self,
        conn: Connection,
        manifest_id: str,
        *,
        expected_start: int,
        rows: Sequence[ManifestRow],
    ) -> None:
        manifest = self._manifest(conn, manifest_id)
        if manifest["state"] != "BUILDING" or expected_start != manifest["row_count"]:
            raise CoreError(
                "IMPORT_MANIFEST_CONFLICT",
                "Snapshot đã khóa hoặc vị trí ghi không khớp.",
                status=409,
            )
        if (
            not 1 <= len(rows) <= MAX_CHUNK_ROWS
            or expected_start + len(rows) > manifest["expected_count"]
        ):
            raise CoreError(
                "IMPORT_CHUNK_INVALID", "Chunk snapshot vượt giới hạn hoặc số dòng xác nhận."
            )
        seen: set[str] = set()
        encoded_rows = []
        fingerprint = manifest["fingerprint"]
        for offset, row in enumerate(rows):
            if not row.source_row_id or row.source_row_id in seen:
                raise CoreError(
                    "IMPORT_SOURCE_ROW_DUPLICATE", "Dòng nguồn trong snapshot bị lặp.", status=409
                )
            seen.add(row.source_row_id)
            snapshot = dict(row.snapshot)
            required = {
                "source_sheet",
                "source_row",
                "revision",
                "raw_values",
                "edited_values",
                "typed_values",
            }
            if (
                not required.issubset(snapshot)
                or not isinstance(snapshot["source_sheet"], str)
                or not snapshot["source_sheet"]
                or type(snapshot["source_row"]) is not int
                or snapshot["source_row"] < 1
                or type(snapshot["revision"]) is not int
                or snapshot["revision"] < 1
                or any(
                    not isinstance(snapshot[key], Mapping)
                    for key in ("raw_values", "edited_values", "typed_values")
                )
            ):
                raise CoreError(
                    "IMPORT_SNAPSHOT_INVALID",
                    "Snapshot phải giữ tọa độ, revision và dữ liệu raw/edited/typed.",
                )
            encoded = _canonical(snapshot)
            row_hash = _hash(_canonical([row.source_row_id, json.loads(encoded)]))
            fingerprint = _hash(fingerprint + row_hash)
            encoded_rows.append(
                dict(
                    manifest_id=manifest_id,
                    ordinal=expected_start + offset,
                    source_row_id=row.source_row_id,
                    snapshot_json=encoded,
                    row_hash=row_hash,
                )
            )
        existing = conn.execute(
            select(manifest_rows.c.source_row_id).where(
                manifest_rows.c.manifest_id == manifest_id, manifest_rows.c.source_row_id.in_(seen)
            )
        ).first()
        if existing:
            raise CoreError(
                "IMPORT_SOURCE_ROW_DUPLICATE", "Dòng nguồn đã có trong snapshot.", status=409
            )
        conn.execute(insert(manifest_rows), encoded_rows)
        conn.execute(
            update(manifests)
            .where(manifests.c.id == manifest_id)
            .values(row_count=expected_start + len(rows), fingerprint=fingerprint)
        )

    def seal_manifest(self, conn: Connection, manifest_id: str) -> str:
        manifest = self._manifest(conn, manifest_id)
        if manifest["state"] == "SEALED":
            return manifest["fingerprint"]
        if manifest["row_count"] != manifest["expected_count"]:
            raise CoreError(
                "IMPORT_MANIFEST_INCOMPLETE", "Snapshot chưa đủ số dòng đã chọn.", status=409
            )
        conn.execute(update(manifests).where(manifests.c.id == manifest_id).values(state="SEALED"))
        return manifest["fingerprint"]

    def create_attempt(self, conn: Connection, manifest_id: str, *, fingerprint: str) -> str:
        manifest = self._manifest(conn, manifest_id)
        if manifest["state"] != "SEALED" or fingerprint != manifest["fingerprint"]:
            raise CoreError(
                "IMPORT_SNAPSHOT_CONFLICT",
                "Snapshot xác nhận chưa khóa hoặc đã thay đổi.",
                status=409,
            )
        existing = conn.execute(
            select(attempts.c.id).where(attempts.c.manifest_id == manifest_id)
        ).scalar_one_or_none()
        if existing:
            return existing
        identity = str(uuid4())
        conn.execute(
            insert(attempts).values(
                id=identity,
                manifest_id=manifest_id,
                job_id=manifest["job_id"],
                state="PENDING",
                expected_count=manifest["expected_count"],
                staged_committed_rows=0,
                published_rows=0,
                checkpoint=0,
                created_at=utc_now(),
            )
        )
        return identity

    def commit_chunk(
        self,
        conn: Connection,
        attempt_id: str,
        *,
        chunk_id: str,
        start: int,
        count: int,
        write_pending: Callable[[Connection, str, tuple[PendingImportRow, ...]], None],
    ) -> tuple[str, ...]:
        attempt = self._attempt(conn, attempt_id)
        receipt = (
            conn.execute(
                select(receipts).where(
                    receipts.c.attempt_id == attempt_id, receipts.c.chunk_id == chunk_id
                )
            )
            .mappings()
            .first()
        )
        if receipt:
            if receipt["start"] != start or receipt["count"] != count:
                raise CoreError(
                    "IMPORT_CHUNK_CONFLICT", "Mã chunk đã dùng cho tập dòng khác.", status=409
                )
            return tuple(
                conn.execute(
                    select(claims.c.target_id)
                    .where(
                        claims.c.attempt_id == attempt_id,
                        claims.c.ordinal >= start,
                        claims.c.ordinal < start + count,
                    )
                    .order_by(claims.c.ordinal)
                ).scalars()
            )
        if attempt["state"] != "PENDING":
            raise CoreError(
                "IMPORT_ATTEMPT_NOT_WRITABLE",
                "Lượt import không ở trạng thái cho phép ghi.",
                status=409,
            )
        if (
            not chunk_id
            or not 1 <= count <= MAX_CHUNK_ROWS
            or start != attempt["checkpoint"]
            or start + count > attempt["expected_count"]
        ):
            raise CoreError(
                "IMPORT_CHUNK_INVALID",
                "Chunk không khớp checkpoint hoặc vượt giới hạn.",
                status=409,
            )
        rows = (
            conn.execute(
                select(manifest_rows)
                .where(
                    manifest_rows.c.manifest_id == attempt["manifest_id"],
                    manifest_rows.c.ordinal >= start,
                    manifest_rows.c.ordinal < start + count,
                )
                .order_by(manifest_rows.c.ordinal)
            )
            .mappings()
            .all()
        )
        if len(rows) != count:
            raise CoreError("IMPORT_MANIFEST_INCOMPLETE", "Snapshot thiếu dòng nguồn.", status=409)
        source_ids = [row["source_row_id"] for row in rows]
        if conn.execute(
            select(claims.c.source_row_id).where(
                claims.c.job_id == attempt["job_id"], claims.c.source_row_id.in_(source_ids)
            )
        ).first():
            raise CoreError(
                "IMPORT_SOURCE_ALREADY_CLAIMED",
                "Dòng nguồn đã thuộc một lượt import khác.",
                status=409,
            )
        pending = tuple(
            PendingImportRow(
                row["source_row_id"], str(uuid4()), row["ordinal"], json.loads(row["snapshot_json"])
            )
            for row in rows
        )
        conn.execute(
            insert(claims),
            [
                dict(
                    job_id=attempt["job_id"],
                    source_row_id=row.source_row_id,
                    attempt_id=attempt_id,
                    ordinal=row.ordinal,
                    target_id=row.target_id,
                )
                for row in pending
            ],
        )
        write_pending(conn, attempt_id, pending)
        conn.execute(
            insert(receipts).values(
                attempt_id=attempt_id,
                chunk_id=chunk_id,
                start=start,
                count=count,
                digest=_hash("".join(row["row_hash"] for row in rows)),
                committed_at=utc_now(),
            )
        )
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(
                staged_committed_rows=attempt["staged_committed_rows"] + count,
                checkpoint=start + count,
            )
        )
        return tuple(row.target_id for row in pending)

    def publish(self, conn: Connection, attempt_id: str) -> dict[str, Any]:
        attempt = self._attempt(conn, attempt_id)
        if attempt["state"] == "PUBLISHED":
            return dict(attempt)
        if (
            attempt["state"] != "PENDING"
            or attempt["checkpoint"] != attempt["expected_count"]
            or attempt["staged_committed_rows"] != attempt["expected_count"]
        ):
            raise CoreError(
                "IMPORT_ATTEMPT_INCOMPLETE",
                "Lượt import bị dừng hoặc chưa ghi đủ tập xác nhận.",
                status=409,
            )
        conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt_id)
            .values(
                state="PUBLISHED", published_rows=attempt["expected_count"], published_at=utc_now()
            )
        )
        return dict(self._attempt(conn, attempt_id))

    def set_interrupted(self, conn: Connection, attempt_id: str, state: str) -> None:
        if state not in {"FAILED", "CANCELLED", "RECOVERABLE"}:
            raise CoreError("IMPORT_STATE_INVALID", "Trạng thái dừng import không hợp lệ.")
        if self._attempt(conn, attempt_id)["state"] == "PUBLISHED":
            raise CoreError(
                "IMPORT_ALREADY_PUBLISHED", "Không thay đổi trạng thái lượt đã công bố.", status=409
            )
        conn.execute(update(attempts).where(attempts.c.id == attempt_id).values(state=state))

    def resume(self, conn: Connection, attempt_id: str) -> None:
        attempt = self._attempt(conn, attempt_id)
        if attempt["state"] not in {"FAILED", "CANCELLED", "RECOVERABLE", "PENDING"}:
            raise CoreError(
                "IMPORT_RESUME_INVALID", "Không thể tiếp tục lượt đã công bố.", status=409
            )
        conn.execute(update(attempts).where(attempts.c.id == attempt_id).values(state="PENDING"))

    def status(self, conn: Connection, attempt_id: str) -> dict[str, Any]:
        result = dict(self._attempt(conn, attempt_id))
        result["pending"] = result["staged_committed_rows"] - result["published_rows"]
        return result

    @staticmethod
    def _manifest(conn: Connection, identity: str) -> Mapping[str, Any]:
        row = conn.execute(select(manifests).where(manifests.c.id == identity)).mappings().first()
        if row is None:
            raise CoreError(
                "IMPORT_MANIFEST_NOT_FOUND", "Không tìm thấy snapshot import.", status=404
            )
        return row

    @staticmethod
    def _attempt(conn: Connection, identity: str) -> Mapping[str, Any]:
        row = conn.execute(select(attempts).where(attempts.c.id == identity)).mappings().first()
        if row is None:
            raise CoreError("IMPORT_ATTEMPT_NOT_FOUND", "Không tìm thấy lượt import.", status=404)
        return row
