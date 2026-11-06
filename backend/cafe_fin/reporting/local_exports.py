"""Recoverable, non-overwriting human copies derived only from canonical bytes."""

import hashlib
from datetime import date
from uuid import UUID

from sqlalchemy import select

from cafe_fin.core.audit import AuditService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from .downloads import reference
from .local_export_migrations import LOCAL_EXPORTS


def safe_key(report_id, first, version, format):
    try:
        valid = (
            str(UUID(report_id)) == report_id
            and date.fromisoformat(first).isoformat() == first
            and type(version) is int
            and version >= 1
            and format in ("pdf", "xlsx", "txt")
        )
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise CoreError("LOCAL_EXPORT_REFERENCE_INVALID", "Tham chiếu bản lưu không hợp lệ.", 409)
    return f"reports/CafeFin-{first}-v{version}-{report_id}.{format}"


def local_state(conn, export_id):
    row = (
        conn.execute(select(LOCAL_EXPORTS).where(LOCAL_EXPORTS.c.export_id == export_id))
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def matches(path, receipt):
    if not path.exists():
        return False
    if not path.is_file():
        raise CoreError(
            "LOCAL_EXPORT_CONFLICT", "Tên bản lưu local đã được dùng; không ghi đè.", 409
        )
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if size != receipt["size"] or digest.hexdigest() != receipt["sha256"]:
        raise CoreError(
            "LOCAL_EXPORT_CONFLICT", "Bản lưu local khác bản canonical; không ghi đè.", 409
        )
    return True


def record(conn, actor_id, export_id, before, after):
    AuditService.record(
        conn,
        actor=actor_id,
        entity="reporting_local_export",
        entity_id=export_id,
        action="local_export",
        before=before,
        after=after,
    )


def finish(service, actor, export_id, attempt):
    def operation(conn):
        service.authorize(actor)(conn)
        old = local_state(conn, export_id)
        if old["attempts"] != attempt or old["state"] != "COPYING":
            raise CoreError("LOCAL_EXPORT_CHANGED", "Lượt lưu local đã thay đổi; hãy thử lại.", 409)
        conn.execute(
            LOCAL_EXPORTS.update()
            .where(LOCAL_EXPORTS.c.export_id == export_id)
            .values(state="READY", error_code=None, verified_at=utc_now(), updated_at=utc_now())
        )
        result = local_state(conn, export_id)
        record(conn, actor.id, export_id, old, result)
        return result

    return service.runtime.writer.run(operation)


def failed(service, export_id, attempt, code):
    def operation(conn):
        old = local_state(conn, export_id)
        if old is None or old["attempts"] != attempt or old["state"] != "COPYING":
            return
        conn.execute(
            LOCAL_EXPORTS.update()
            .where(LOCAL_EXPORTS.c.export_id == export_id)
            .values(
                state="CONFLICT" if code == "LOCAL_EXPORT_CONFLICT" else "FAILED",
                error_code=code,
                updated_at=utc_now(),
            )
        )
        record(conn, "reporting.local-export", export_id, old, local_state(conn, export_id))

    # Maintenance failure bookkeeping grants no new file access or domain mutation.
    service.runtime.writer.run(operation)


def ensure_local_copy(service, actor, receipt):
    export_id, report_id = receipt["id"], receipt["report_id"]
    pinned = reference(service, actor, report_id, export_id)
    with service.runtime.reader() as conn:
        report = service.report(conn, report_id)
        key = safe_key(report_id, report.from_on, report.version, receipt["format"])

    def authorize(conn):
        service.authorize(actor)(conn)
        old = local_state(conn, export_id)
        if old is not None and any(
            old[field] != value
            for field, value in (
                ("relative_key", key),
                ("sha256", receipt["sha256"]),
                ("size", receipt["size"]),
            )
        ):
            raise CoreError("LOCAL_EXPORT_REFERENCE_INVALID", "Tham chiếu bản lưu không khớp.", 409)
        return old

    old = service.runtime.writer.run(authorize)
    if old is not None and old["state"] == "READY":
        try:
            valid = matches(service.runtime.root.resolve_key(key), receipt)
        except (OSError, CoreError):
            valid = False  # Claim below so a newly discovered IO/conflict is durable.
        if valid:
            if reference(service, actor, report_id, export_id) != pinned:
                raise CoreError("LOCAL_EXPORT_CHANGED", "Tham chiếu bản lưu đã thay đổi.", 409)
            service.runtime.writer.run(service.authorize(actor))
            return old

    def claim(conn):
        previous = authorize(conn)
        values = dict(
            state="COPYING",
            error_code=None,
            attempts=(previous["attempts"] if previous else 0) + 1,
            updated_at=utc_now(),
        )
        if previous is None:
            conn.execute(
                LOCAL_EXPORTS.insert().values(
                    export_id=export_id,
                    relative_key=key,
                    sha256=receipt["sha256"],
                    size=receipt["size"],
                    verified_at=None,
                    **values,
                )
            )
        else:
            conn.execute(
                LOCAL_EXPORTS.update()
                .where(LOCAL_EXPORTS.c.export_id == export_id)
                .values(**values)
            )
        result = local_state(conn, export_id)
        record(conn, actor.id, export_id, previous, result)
        return result["attempts"]

    attempt = service.runtime.writer.run(claim)
    try:
        destination = service.runtime.root.resolve_key(key)
        if not matches(destination, receipt):
            try:
                service.runtime.files.export(receipt["file_id"], destination)
            except CoreError as exc:
                if exc.code != "EXPORT_EXISTS":
                    raise
                # External Explorer/process won the non-overwrite race: only reuse
                # an exact verified copy, never replace the winner.
            if not matches(service.runtime.root.resolve_key(key), receipt):
                raise CoreError("LOCAL_EXPORT_IO", "Chưa tạo được bản lưu local.", 409)
        if reference(service, actor, report_id, export_id) != pinned:
            raise CoreError("LOCAL_EXPORT_CHANGED", "Tham chiếu bản lưu đã thay đổi.", 409)
        return finish(service, actor, export_id, attempt)
    except CoreError as exc:
        code = (
            exc.code
            if exc.code
            in {
                "LOCAL_EXPORT_CONFLICT",
                "LOCAL_EXPORT_IO",
                "LOCAL_EXPORT_CHANGED",
                "FILE_MISSING",
                "FILE_HASH_MISMATCH",
                "DISK_FULL",
                "STORAGE_IO",
                "FILE_KEY_INVALID",
                "REPORT_EXPORT_UNAVAILABLE",
                "SESSION_EXPIRED",
                "PERMISSION_DENIED",
            }
            else "LOCAL_EXPORT_FAILED"
        )
        failed(service, export_id, attempt, code)
        if code in {"SESSION_EXPIRED", "PERMISSION_DENIED"}:
            raise
        raise CoreError(
            code,
            "Chưa lưu được bản local; bản canonical vẫn được giữ. Kiểm tra trạng thái và thử lại.",
            409,
        ) from None
    except Exception:
        failed(service, export_id, attempt, "LOCAL_EXPORT_IO")
        raise CoreError(
            "LOCAL_EXPORT_IO", "Không lưu được bản local; bản canonical vẫn được giữ.", 409
        ) from None
