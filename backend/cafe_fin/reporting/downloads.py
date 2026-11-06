"""Shared report exports use saved domain references, never raw file-ID grants."""

import hashlib
import tempfile
from contextlib import ExitStack

from sqlalchemy import select
from starlette.responses import StreamingResponse

from cafe_fin.core.errors import CoreError

from .migrations import EXPORTS

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain; charset=utf-8",
}


def unavailable():
    return CoreError("REPORT_EXPORT_UNAVAILABLE", "Tệp tổng hợp không khớp bản đã lưu.", 409)


def reference(service, actor, report_id, export_id):
    with service.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        service.runtime.auth.authorize(conn, actor, "reporting.read")
        report = service.report(conn, report_id)
        if report.state != "SAVED":
            raise CoreError("REPORT_NOT_SAVED", "Báo cáo chưa được lưu.", 409)
        row = (
            conn.execute(
                select(EXPORTS).where(EXPORTS.c.id == export_id, EXPORTS.c.report_id == report_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise CoreError("REPORT_EXPORT_NOT_FOUND", "Không tìm thấy tệp của báo cáo này.", 404)
        try:
            stored = service.runtime.files.get(row.file_id, connection=conn)
        except CoreError as exc:
            if exc.code == "FILE_NOT_FOUND":
                raise unavailable() from None
            raise
        if (
            row.format not in MEDIA_TYPES
            or stored.id != row.file_id
            or stored.sha256 != row.sha256
            or stored.size != row.size
            or stored.category != "reports"
            or stored.media_type != MEDIA_TYPES[row.format]
        ):
            raise unavailable()
        return dict(row), stored, (report.id, report.state, report.version, report.sha256)


class VerifiedExportResponse(StreamingResponse):
    def __init__(self, content, *, resources, **kwargs):
        super().__init__(content, **kwargs)
        self.resources = resources

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.resources.close()


def export_content(service, actor, report_id, export_id):
    pinned = reference(service, actor, report_id, export_id)
    row, stored, _ = pinned
    resources = ExitStack()
    try:
        # Finish all IO/hash checks before HTTP 200. Freeze verified bytes on disk
        # so a source edit after verification cannot change the outgoing stream.
        frozen = resources.enter_context(
            tempfile.TemporaryFile(mode="w+b", dir=service.runtime.root.resolve_key("imports"))
        )
        digest, size = hashlib.sha256(), 0
        # Trusted read is allowed only after current permission and saved domain
        # reference checks above. Generic file ownership/ACL remains unchanged.
        with service.runtime.files.read(stored.id) as source:
            while chunk := source.read(64 * 1024):
                size += len(chunk)
                if size > row["size"]:
                    raise unavailable()
                digest.update(chunk)
                frozen.write(chunk)
        if size != row["size"] or digest.hexdigest() != row["sha256"]:
            raise unavailable()
        frozen.seek(0)
        # Fresh snapshot: do not hide a role/version change by resolving a new
        # principal, or hold a DB read transaction over potentially slow IO.
        if reference(service, actor, report_id, export_id) != pinned:
            raise unavailable()
    except OSError:
        resources.close()
        raise CoreError(
            "REPORT_EXPORT_UNAVAILABLE", "Không đọc được tệp tổng hợp đã lưu.", 409
        ) from None
    except BaseException:
        resources.close()
        raise

    def stream():
        try:
            while chunk := frozen.read(64 * 1024):
                yield chunk
        finally:
            resources.close()

    return VerifiedExportResponse(
        stream(),
        resources=resources,
        media_type=stored.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="CafeFin-tong-hop.{row["format"]}"',
            "Content-Length": str(row["size"]),
            "X-Content-SHA256": row["sha256"],
        },
    )
