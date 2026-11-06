"""Reporting persistence. Source reads, rendering and network never hold the writer."""

import hashlib
import io
import json
import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from . import exports
from .local_export_migrations import LOCAL_EXPORTS
from .local_exports import ensure_local_copy, local_state, repair_relocated_copies
from .migrations import ATTEMPTS, EXPORTS, LOCKS, OUTBOX, REPORTS, SETTINGS
from .models import DATE_RANGE_CONTRACT
from .restore import REVIEW_CODE, apply_guard, held_series, require_reviewed, suspended
from .sources import UnboundSources, build_snapshot


def new_id():
    return str(uuid.uuid4())


def report_dto(row, *, detail=True):
    result = {
        key: row[key]
        for key in (
            "id",
            "version",
            "from_on",
            "through_on",
            "state",
            "sha256",
            "reason",
            "created_at",
            "created_by",
            "saved_at",
        )
    }
    if detail:
        result["snapshot"] = json.loads(row["snapshot_json"])
    return result


def outbox_dto(row):
    return {
        key: row[key]
        for key in (
            "id",
            "report_id",
            "destination",
            "oa_id",
            "config_version",
            "state",
            "phase",
            "version",
            "attempts",
            "message_id",
            "file_message_id",
            "error_code",
            "attachment_export_id",
            "created_at",
            "updated_at",
        )
    }


class ReportingService:
    def __init__(
        self,
        runtime,
        *,
        source=None,
        actor_source_factory=None,
        secret_store=None,
        transport=None,
        heartbeat_bound=False,
        clock=None,
    ):
        from .zalo import MissingSecrets, OfficialGMF

        self.runtime = runtime
        self.source = source or UnboundSources()
        if source is not None and actor_source_factory is not None:
            raise ValueError("Choose source or actor_source_factory")
        self.actor_source_factory = actor_source_factory
        self.secrets = secret_store or MissingSecrets()
        self.transport = transport or OfficialGMF()
        # Compatibility argument only. Public status is derived from real registration,
        # never from a caller's claim that an external heartbeat exists.
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def authorize(self, actor, permission="reporting.write"):
        return lambda conn: self.runtime.auth.authorize(conn, actor, permission)

    def command(self, actor, action, request_key, payload, operation, *, admin=False):
        def authorize(conn):
            self.authorize(actor, "core.manage" if admin else "reporting.write")(conn)
            if action in {"enqueue", "retry"}:
                self.require_delivery_review(conn)

        return self.runtime.writer.execute(
            actor.id,
            "reporting." + action,
            request_key,
            payload,
            operation,
            authorize=authorize,
        )

    @staticmethod
    def report(conn, identity):
        row = conn.execute(select(REPORTS).where(REPORTS.c.id == identity)).mappings().first()
        if not row:
            raise CoreError("REPORT_NOT_FOUND", "Không tìm thấy báo cáo.", 404)
        if hashlib.sha256(row.snapshot_json.encode()).hexdigest() != row.sha256:
            raise CoreError("REPORT_HASH_MISMATCH", "Snapshot báo cáo không còn khớp hash.", 409)
        return row

    def detail(self, identity):
        with self.runtime.reader() as conn:
            row = self.report(conn, identity)
            result = report_dto(row)
            result["exports"] = [
                {**dict(x), "local_export": local_state(conn, x.id)}
                for x in conn.execute(
                    select(EXPORTS).where(EXPORTS.c.report_id == identity)
                ).mappings()
            ]
        result["short_message"] = exports.short_message(result["snapshot"], row.version, row.sha256)
        return result

    def preview(self, actor, command, *, capture_metadata=None):
        payload = command.model_dump()
        payload.pop("request_key")
        series = hashlib.sha256(
            canonical_json(
                {
                    "from_on": command.from_on,
                    "through_on": command.through_on,
                    "book_ids": command.book_ids,
                }
            ).encode()
        ).hexdigest()
        # Replay lookup via writer.execute must precede expensive reads. Reserve no
        # mutation here: a replay returns its original immutable preview below.
        with self.runtime.reader() as conn:
            previous = conn.execute(
                select(REPORTS.c.id).where(
                    REPORTS.c.created_by == actor.id, REPORTS.c.command_key == command.request_key
                )
            ).first()
        if previous:
            return self.command(actor, "preview", command.request_key, payload, lambda conn: None)
        self.runtime.writer.run(self.authorize(actor))
        source = (
            self.actor_source_factory(self.runtime, actor)
            if self.actor_source_factory
            else self.source
        )
        capture_time = self.clock().astimezone(timezone.utc)
        if (
            capture_metadata is not None
            and capture_metadata.get("kind") == "scheduled_daily"
            and command.from_on
            != capture_time.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
        ):
            raise CoreError(
                "SCHEDULE_DAY_MISSED", "Đã sang ngày mới; không tự tạo số ngày cũ.", 409
            )
        snapshot = build_snapshot(source, command, capture_time)
        if capture_metadata is not None:
            snapshot["generation"] = capture_metadata
        encoded = canonical_json(snapshot)
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise CoreError("REPORT_TOO_LARGE", "Báo cáo quá lớn; chọn khoảng ngắn hơn.", 413)

        def operation(conn):
            version = (
                conn.execute(
                    select(func.max(REPORTS.c.version)).where(REPORTS.c.series_key == series)
                ).scalar_one()
                or 0
            )
            if version and not command.reason.strip():
                raise CoreError(
                    "REPORT_REVISION_REASON_REQUIRED", "Bản mới cần lý do điều chỉnh.", 409
                )
            row = dict(
                id=new_id(),
                series_key=series,
                version=version + 1,
                from_on=command.from_on,
                through_on=command.through_on,
                state="PREVIEW",
                snapshot_json=encoded,
                sha256=hashlib.sha256(encoded.encode()).hexdigest(),
                reason=command.reason.strip(),
                created_at=utc_now(),
                created_by=actor.id,
                command_key=command.request_key,
                saved_at=None,
            )
            conn.execute(REPORTS.insert().values(**row))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_report",
                entity_id=row["id"],
                action="preview",
                after={"version": row["version"], "sha256": row["sha256"]},
            )
            return report_dto(row)

        return self.command(actor, "preview", command.request_key, payload, operation)

    def save(self, actor, identity, command):
        def operation(conn):
            row = self.report(conn, identity)
            # Snapshot version identifies content; state changes do not create new content.
            require_version(row.version, command.expected_version)
            if row.state == "PREVIEW":
                conn.execute(
                    REPORTS.update()
                    .where(REPORTS.c.id == identity)
                    .values(state="SAVED", saved_at=utc_now())
                )
                AuditService.record(
                    conn,
                    actor=actor.id,
                    entity="reporting_report",
                    entity_id=identity,
                    action="save",
                    after={"version": row.version, "sha256": row.sha256},
                )
            return report_dto(self.report(conn, identity))

        return self.command(
            actor,
            "save",
            command.request_key,
            {"id": identity, "expected_version": command.expected_version},
            operation,
        )

    def export(self, actor, identity, command):
        with self.runtime.render_lock:
            canonical = self._export(actor, identity, command)
            return {**canonical, "local_export": ensure_local_copy(self, actor, canonical)}

    def _export(self, actor, identity, command):
        with self.runtime.reader() as conn:
            row = self.report(conn, identity)
            if row.state != "SAVED":
                raise CoreError("REPORT_NOT_SAVED", "Lưu báo cáo trước khi xuất.", 409)
            existing = (
                conn.execute(
                    select(EXPORTS).where(
                        EXPORTS.c.report_id == identity, EXPORTS.c.format == command.format
                    )
                )
                .mappings()
                .first()
            )
        content = stored = None
        if not existing:
            content, media_type = exports.render(
                json.loads(row.snapshot_json), row.version, row.sha256, command.format
            )
            stored = self.runtime.files.put(
                io.BytesIO(content),
                category="reports",
                original_name=f"CafeFin-{row.from_on}-v{row.version}.{command.format}",
                actor="reporting.export",
                request_key=f"report-{identity}-{command.format}",
                media_type=media_type,
                authorize=self.authorize(actor),
            )

        def operation(conn):
            current = (
                conn.execute(
                    select(EXPORTS).where(
                        EXPORTS.c.report_id == identity, EXPORTS.c.format == command.format
                    )
                )
                .mappings()
                .first()
            )
            if current:
                return dict(current)
            result = dict(
                id=new_id(),
                report_id=identity,
                format=command.format,
                file_id=stored.id,
                sha256=stored.sha256,
                size=stored.size,
                created_at=utc_now(),
            )
            conn.execute(EXPORTS.insert().values(**result))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_export",
                entity_id=result["id"],
                action="export",
                after=result,
            )
            return result

        return self.command(
            actor,
            "export",
            command.request_key,
            {"id": identity, "format": command.format},
            operation,
        )

    def settings(self, conn=None):
        if conn is None:
            with self.runtime.reader() as read:
                return self.settings(read)
        row = conn.execute(select(SETTINGS).where(SETTINGS.c.id == "delivery")).mappings().first()
        defaults = {
            "version": 0,
            "group_id": "",
            "oa_id": "",
            "enabled": False,
            "timezone": "Asia/Ho_Chi_Minh",
            "send_at": None,
            "attachments_enabled": False,
            "auto_generate_daily": False,
            "daily_book_ids": [],
            "daily_export_formats": ["pdf", "xlsx", "txt"],
            "scheduled_actor_id": None,
            "auto_activated_on": None,
            "restore_review": None,
        }
        return defaults | ({"version": row.version, **json.loads(row.config_json)} if row else {})

    def resolve_scheduled_actor(self, config):
        if not config.get("scheduled_actor_id"):
            raise CoreError("SCHEDULE_ACTOR_UNCONFIGURED", "Admin cần lưu lại cấu hình lịch.", 409)
        with self.runtime.reader() as conn:
            return self.runtime.auth.resolve_actor(
                conn, config["scheduled_actor_id"], "core.manage"
            )

    def guard_schedule(self, conn, config, actor):
        self.runtime.auth.authorize(conn, actor, "core.manage")
        self.require_delivery_review(conn)
        if self.settings(conn)["version"] != config["version"]:
            raise CoreError(
                "SCHEDULE_CONFIG_CHANGED", "Cấu hình lịch đã đổi; giữ nguyên bản đã tạo.", 409
            )

    def public_settings(self):
        config = self.settings()
        config["credential_store_available"] = self.secrets.available
        config["restore_review_required"] = suspended(config)
        try:
            if suspended(config):
                config["credential_configured"] = None  # Deliberately not read during restore hold.
            else:
                config["credential_configured"] = self.secrets.has(self.secret_key(config))
        except Exception:
            config["credential_configured"] = False
        config["sender_status"] = (
            "RESTORE_SUSPENDED"
            if suspended(config)
            else "CONFIGURED"
            if (config["group_id"] and config["oa_id"] and config["credential_configured"])
            else "UNCONFIGURED"
        )
        periodic = self.runtime.periodic
        status = periodic.status() if periodic is not None else {}
        registered = "reporting.tick" in status.get("runs", {})
        config["scheduler_mode"] = "APP_RUNTIME" if registered else "MANUAL"
        config["scheduler_status"] = {
            "registered": registered,
            "state": status.get("state", "UNBOUND") if registered else "UNBOUND",
            "running": bool(registered and status.get("running")),
            "active": registered and status.get("active_task") == "reporting.tick",
            "error_code": status.get("error_code") if registered else None,
            "last_error_code": status.get("last_error_code") if registered else None,
            "task_error_code": status.get("task_errors", {}).get("reporting.tick"),
            "runs": status.get("runs", {}).get("reporting.tick", 0),
            "failures": status.get("failures", {}).get("reporting.tick", 0),
        }
        try:
            self.resolve_scheduled_actor(config)
            config["schedule_actor_status"] = "ACTIVE"
        except CoreError:
            config["schedule_actor_status"] = "BLOCKED"
        config["scheduler_limit"] = (
            "Lịch do backend kiểm tra mỗi 60 giây, không cần mở màn hình Báo cáo. "
            if registered
            else "Runtime chưa đăng ký lịch tự động; chỉ kiểm tra khi được yêu cầu. "
        ) + (
            "Máy ngủ/tắt hoặc backend dừng không chạy lịch; mở lại phục hồi bản đã lưu, "
            "ngày cũ thiếu snapshot cần xử lý thủ công."
        )
        return config

    def credential_ready(self, config):
        try:
            return bool(
                not suspended(config)
                and config["oa_id"]
                and config["group_id"]
                and self.secrets.has(self.secret_key(config))
            )
        except Exception:
            return False

    def secret_key(self, config):
        # Stable root identity survives move/restore, without a local path in credentials.
        marker = self.runtime.root.resolve_key(".cafe-fin-root.json")
        root_id = json.loads(marker.read_text(encoding="utf-8"))["root_id"]
        return f"cafe_fin/reporting/{root_id}/{config['oa_id']}"

    def update_settings(self, actor, command):
        value = command.model_dump(exclude={"request_key", "expected_version"})

        def operation(conn):
            if conn.execute(select(LOCKS.c.id).where(LOCKS.c.id == "sender")).first():
                raise CoreError("SENDER_BUSY", "Đợi bộ gửi hoàn tất trước khi đổi cấu hình.", 409)
            old = self.settings(conn)
            version = require_version(old["version"], command.expected_version)
            active = value["enabled"] and value["auto_generate_daily"]
            was_active = old["enabled"] and old["auto_generate_daily"]
            activated = old["auto_activated_on"]
            if active and not was_active:
                activated = self.clock().astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
                from .schedule_migrations import DAILY_CURSOR

                cursor = conn.execute(
                    select(DAILY_CURSOR).where(DAILY_CURSOR.c.profile_id == "delivery")
                ).first()
                cursor_values = dict(next_unchecked_on=activated, updated_at=utc_now())
                if cursor:
                    conn.execute(
                        DAILY_CURSOR.update()
                        .where(DAILY_CURSOR.c.profile_id == "delivery")
                        .values(**cursor_values)
                    )
                else:
                    conn.execute(
                        DAILY_CURSOR.insert().values(profile_id="delivery", **cursor_values)
                    )
            review = old.get("restore_review")
            if suspended(old) and value["enabled"]:
                review = {
                    **review,
                    "required": False,
                    "reviewed_at": utc_now(),
                    "reviewed_by": actor.id,
                }
            persisted = value | {
                "scheduled_actor_id": actor.id,
                "auto_activated_on": activated,
                "restore_review": review,
            }
            values = dict(
                version=version, config_json=canonical_json(persisted), updated_at=utc_now()
            )
            if old["version"]:
                conn.execute(SETTINGS.update().where(SETTINGS.c.id == "delivery").values(**values))
            else:
                conn.execute(SETTINGS.insert().values(id="delivery", **values))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_settings",
                entity_id="delivery",
                action="update",
                before=old,
                after={"version": version, **persisted},
            )
            return {"version": version, **persisted}

        self.command(
            actor,
            "settings",
            command.request_key,
            {"expected_version": command.expected_version, **value},
            operation,
            admin=True,
        )
        with self.runtime.reader() as conn:
            self.authorize(actor, "core.manage")(conn)
            return self.settings(conn)

    def restore_quarantine(self, actor, context):
        return apply_guard(self, actor, context)

    def repair_local_exports(self, actor, context):
        return repair_relocated_copies(self, actor, context)

    def require_delivery_review(self, conn=None):
        if self.runtime.maintenance.status()["state"] != "ACTIVE":
            raise CoreError("RUNTIME_NOT_ACTIVE", "Dữ liệu chưa hoàn tất kích hoạt.", 503)
        require_reviewed(self.settings(conn))

    def delivery_result(self, actor, identity):
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.authorize(actor)(conn)
            self.require_delivery_review(conn)
            row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one()
            return outbox_dto(row)

    def set_credentials(self, actor, command):
        from .sender import sender_lock

        # Check current admin under the writer, then perform OS call outside it.
        self.runtime.writer.run(self.authorize(actor, "core.manage"))
        with sender_lock(self) as locked:
            if not locked:
                raise CoreError("SENDER_BUSY", "Đợi bộ gửi hoàn tất trước khi đổi credential.", 409)
            config = self.settings()
            if not config["oa_id"]:
                raise CoreError("ZALO_UNCONFIGURED", "Lưu OA trước khi lưu credential.", 409)
            try:
                self.secrets.put(self.secret_key(config), command.model_dump())
            except CoreError as exc:
                messages = {
                    "SECRET_VALUE_TOO_LARGE": (
                        "Credential vượt giới hạn 2.560 byte của kho bí mật Windows.",
                        400,
                    ),
                    "SECRET_STORE_BUSY": ("Kho bí mật đang bận; vui lòng thử lại.", 503),
                }
                message, status = messages.get(
                    exc.code, ("Không lưu được credential trong kho bí mật Windows.", 503)
                )
                code = exc.code if exc.code in messages else "SECRET_STORE_UNAVAILABLE"
                raise CoreError(code, message, status) from None
            except Exception:
                raise CoreError(
                    "SECRET_STORE_UNAVAILABLE",
                    "Không lưu được credential trong kho bí mật Windows.",
                    503,
                ) from None
        return {"configured": True}

    def _enqueue(self, conn, report, config, attachment=None, *, credential_ready=False):
        snapshot = json.loads(report.snapshot_json)
        if snapshot["period"].get("date_range_contract") != DATE_RANGE_CONTRACT:
            raise CoreError(
                "REPORT_PERIOD_CONTRACT_REQUIRED",
                "Kỳ báo cáo cũ chưa định danh. Tạo bản điều chỉnh với ngày cuối được bao gồm.",
                409,
            )
        existing = (
            conn.execute(
                select(OUTBOX).where(
                    OUTBOX.c.report_id == report.id,
                    OUTBOX.c.destination == config["group_id"],
                    OUTBOX.c.oa_id == config["oa_id"],
                )
            )
            .mappings()
            .first()
        )
        if existing:
            if attachment != existing.attachment_export_id:
                raise CoreError(
                    "DELIVERY_PAYLOAD_CONFLICT", "Bản gửi đã khóa nội dung/đính kèm.", 409
                )
            return outbox_dto(existing)
        if attachment:
            if not config["attachments_enabled"]:
                raise CoreError("ATTACHMENT_DISABLED", "Admin chưa bật đính kèm tổng hợp.", 409)
            match = (
                conn.execute(
                    select(EXPORTS).where(
                        EXPORTS.c.id == attachment, EXPORTS.c.report_id == report.id
                    )
                )
                .mappings()
                .first()
            )
            if not match:
                raise CoreError("ATTACHMENT_INVALID", "Chỉ chọn bản tổng hợp của báo cáo này.", 409)
        # No file ID or local path is included in the transport payload.
        payload = {
            "date_range_contract": DATE_RANGE_CONTRACT,
            "text": exports.short_message(snapshot, report.version, report.sha256),
        }
        now = utc_now()
        row = dict(
            id=new_id(),
            report_id=report.id,
            destination=config["group_id"],
            oa_id=config["oa_id"],
            config_version=config["version"],
            payload_json=canonical_json(payload),
            attachment_export_id=attachment,
            state="WAITING"
            if config["group_id"] and config["oa_id"] and credential_ready
            else "UNCONFIGURED",
            phase="text",
            version=1,
            attempts=0,
            message_id=None,
            file_message_id=None,
            error_code=None,
            created_at=now,
            updated_at=now,
        )
        conn.execute(OUTBOX.insert().values(**row))
        return outbox_dto(row)

    def enqueue(self, actor, identity, command, *, expected_config_version=None):
        configured = self.settings()
        ready = self.credential_ready(configured)  # OS access stays outside writer.

        def operation(conn):
            row = self.report(conn, identity)
            if row.state != "SAVED":
                raise CoreError("REPORT_NOT_SAVED", "Lưu báo cáo trước khi xếp gửi.", 409)
            current = self.settings(conn)
            if (
                expected_config_version is not None
                and current["version"] != expected_config_version
            ):
                raise CoreError("SCHEDULE_CONFIG_CHANGED", "Cấu hình lịch đã đổi.", 409)
            if current["version"] != configured["version"]:
                raise CoreError(
                    "DELIVERY_CONFIG_CHANGED",
                    "Cấu hình gửi vừa đổi; kiểm tra đích rồi thử lại.",
                    409,
                )
            result = self._enqueue(
                conn, row, current, command.attachment_export_id, credential_ready=ready
            )
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_outbox",
                entity_id=result["id"],
                action="enqueue",
                after=result,
            )
            return result

        result = self.command(
            actor,
            "enqueue",
            command.request_key,
            {"report_id": identity, "attachment": command.attachment_export_id},
            operation,
        )
        return self.delivery_result(actor, result["id"])

    def list(self, kind, *, page=1, page_size=25, search="", sort="created_at:desc", state=None):
        table = {"reports": REPORTS, "deliveries": OUTBOX}[kind]
        sort_field, _, direction = sort.partition(":")
        allowed = {"created_at", "state", "version"} | (
            {"from_on"} if kind == "reports" else {"attempts"}
        )
        valid_states = (
            {"PREVIEW", "SAVED"}
            if kind == "reports"
            else {"WAITING", "SENDING", "SENT", "FAILED", "UNKNOWN", "UNCONFIGURED"}
        )
        if (
            sort_field not in allowed
            or direction not in {"asc", "desc"}
            or state is not None
            and state not in valid_states
        ):
            raise CoreError("REPORT_FILTER_INVALID", "Bộ lọc/sắp xếp không hợp lệ.")
        clauses = []
        if state:
            clauses.append(table.c.state == state)
        if search:
            # Literal substring search; wildcard characters are not user SQL syntax.
            column = table.c.from_on if kind == "reports" else table.c.destination
            clauses.append(
                column.contains(search, autoescape=True)
                | table.c.id.contains(search, autoescape=True)
            )
        ordering = table.c[sort_field].asc() if direction == "asc" else table.c[sort_field].desc()
        with self.runtime.reader() as conn:
            count = conn.execute(
                select(func.count()).select_from(table).where(*clauses)
            ).scalar_one()
            rows = conn.execute(
                select(table)
                .where(*clauses)
                .order_by(ordering, table.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            items = [
                report_dto(x, detail=False) if kind == "reports" else outbox_dto(x) for x in rows
            ]
        return {"items": items, "total": count, "page": page, "page_size": page_size}

    def attempts(self, identity, page, page_size):
        with self.runtime.reader() as conn:
            clauses = ATTEMPTS.c.outbox_id == identity
            total = conn.execute(
                select(func.count()).select_from(ATTEMPTS).where(clauses)
            ).scalar_one()
            rows = conn.execute(
                select(ATTEMPTS)
                .where(clauses)
                .order_by(ATTEMPTS.c.created_at.desc(), ATTEMPTS.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return {
                "items": [dict(x) for x in rows.mappings()],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def recover(self):
        def operation(conn):
            conn.execute(
                LOCAL_EXPORTS.update()
                .where(LOCAL_EXPORTS.c.state == "COPYING")
                .values(state="PENDING", error_code="PROCESS_INTERRUPTED", updated_at=utc_now())
            )
            # A persisted text receipt with no attachment already proves completion.
            conn.execute(
                OUTBOX.update()
                .where(
                    OUTBOX.c.state.in_(("SENDING", "UNKNOWN")),
                    OUTBOX.c.message_id.is_not(None),
                    OUTBOX.c.attachment_export_id.is_(None),
                    (OUTBOX.c.error_code.is_(None) | (OUTBOX.c.error_code != REVIEW_CODE)),
                )
                .values(
                    state="SENT",
                    phase="complete",
                    error_code=None,
                    version=OUTBOX.c.version + 1,
                    updated_at=utc_now(),
                )
            )
            # Process crashed anywhere during outbound operation: never retry blindly.
            conn.execute(
                OUTBOX.update()
                .where(OUTBOX.c.state == "SENDING")
                .values(
                    state="UNKNOWN",
                    error_code="PROCESS_INTERRUPTED",
                    version=OUTBOX.c.version + 1,
                    updated_at=utc_now(),
                )
            )
            conn.execute(LOCKS.delete())
            from .schedule_migrations import DAILY_RUNS

            conn.execute(
                DAILY_RUNS.update()
                .where(DAILY_RUNS.c.state == "RUNNING")
                .values(state="PENDING", error_code="PROCESS_INTERRUPTED", updated_at=utc_now())
            )

        self.runtime.writer.run(operation)

    def catch_up(self, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Aware scheduler time required")
        configured = self.settings()
        if suspended(configured) or self.runtime.maintenance.status()["state"] != "ACTIVE":
            return 0
        if configured["enabled"]:
            try:
                scheduled_actor = self.resolve_scheduled_actor(configured)
            except CoreError:
                return 0
        ready = self.credential_ready(configured)

        def operation(conn):
            config = self.settings(conn)
            if config["version"] != configured["version"]:
                return 0
            if not config["enabled"] or not config["send_at"]:
                return 0
            self.guard_schedule(conn, configured, scheduled_actor)
            if ready:
                # Safe to resume only entries that never entered a send because
                # credentials were absent. UNKNOWN/FAILED are never auto-retried.
                conn.execute(
                    OUTBOX.update()
                    .where(
                        OUTBOX.c.state == "UNCONFIGURED",
                        ~select(REPORTS.c.id)
                        .where(
                            REPORTS.c.id == OUTBOX.c.report_id,
                            held_series(REPORTS.c.series_key),
                        )
                        .exists(),
                        func.json_extract(OUTBOX.c.payload_json, "$.date_range_contract")
                        == DATE_RANGE_CONTRACT,
                        OUTBOX.c.destination == config["group_id"],
                        OUTBOX.c.oa_id == config["oa_id"],
                    )
                    .values(
                        state="WAITING",
                        error_code=None,
                        version=OUTBOX.c.version + 1,
                        updated_at=utc_now(),
                    )
                )
            if config["auto_generate_daily"]:
                # Daily orchestrator owns selected-series creation/export/queue.
                # Do not bypass a failed export or queue another manual version.
                return 0
            local_now = now.astimezone(ZoneInfo(config["timezone"]))
            clock = time.fromisoformat(config["send_at"])
            # SQL selects only unscheduled latest saved versions, bounded to 100
            # per tick. No all-history scan/materialization inside the writer.
            newer = REPORTS.alias("newer")
            rows = conn.execute(
                select(REPORTS)
                .where(
                    REPORTS.c.state == "SAVED",
                    ~held_series(REPORTS.c.series_key),
                    func.json_extract(REPORTS.c.snapshot_json, "$.period.date_range_contract")
                    == DATE_RANGE_CONTRACT,
                    REPORTS.c.through_on <= local_now.date().isoformat(),
                    ~select(newer.c.id)
                    .where(
                        newer.c.series_key == REPORTS.c.series_key,
                        newer.c.state == "SAVED",
                        newer.c.version > REPORTS.c.version,
                    )
                    .exists(),
                    ~select(OUTBOX.c.id)
                    .where(
                        OUTBOX.c.report_id == REPORTS.c.id,
                        OUTBOX.c.destination == config["group_id"],
                        OUTBOX.c.oa_id == config["oa_id"],
                    )
                    .exists(),
                )
                .order_by(REPORTS.c.created_at, REPORTS.c.id)
                .limit(100)
            )
            count = 0
            for report in rows.mappings():
                # through_on IS the final included business date, not the following day.
                # send_at applies to that date in the configured scheduler timezone.
                last = datetime.fromisoformat(report.through_on).date()
                due = datetime.combine(last, clock, ZoneInfo(config["timezone"]))
                if local_now < due:
                    continue
                # Only the latest saved version of a series may be newly scheduled.
                self._enqueue(
                    conn, report, config, credential_ready=ready
                )  # schedules never choose attachments
                count += 1
            return count

        return self.runtime.writer.run(operation)

    def tick(self, now=None):
        from .schedule import generate_daily
        from .sender import dispatch_one

        now = now or self.clock()
        if self.runtime.maintenance.status()["state"] != "ACTIVE":
            return {
                "generation": {"state": "BLOCKED"},
                "queued": 0,
                "delivery": {"state": "BLOCKED", "code": "RUNTIME_NOT_ACTIVE"},
            }
        if suspended(self.settings()):
            return {
                "generation": {"state": "RESTORE_SUSPENDED"},
                "queued": 0,
                "delivery": {"state": "SUSPENDED", "code": REVIEW_CODE},
            }
        generation = generate_daily(self, now)
        if generation["state"] in {"FAILED", "BLOCKED", "NEEDS_MANUAL", "BUSY"}:
            return {"generation": generation, "queued": 0, "delivery": {"state": "BLOCKED"}}
        queued = self.catch_up(now)
        return {"generation": generation, "queued": queued, "delivery": dispatch_one(self)}

    def retry(self, actor, identity, command):
        configured = self.settings()
        ready = self.credential_ready(configured)  # OS access stays outside writer.

        def operation(conn):
            row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().first()
            if not row:
                raise CoreError("DELIVERY_NOT_FOUND", "Không tìm thấy lượt gửi.", 404)
            require_version(row.version, command.expected_version)
            if row.state not in {"FAILED", "UNCONFIGURED"}:
                raise CoreError(
                    "DELIVERY_RETRY_UNSAFE",
                    "Chỉ thử lại lỗi đã xác định chưa gửi; bản chưa rõ cần đối chiếu.",
                    409,
                )
            config = self.settings(conn)
            if config["version"] != configured["version"]:
                raise CoreError(
                    "SCHEDULE_CONFIG_CHANGED", "Cấu hình lịch đã đổi; hãy thử lại.", 409
                )
            if row.destination != config["group_id"] or row.oa_id != config["oa_id"]:
                raise CoreError(
                    "DESTINATION_CHANGED", "Đích đã đổi; xếp một bản gửi cho đích mới.", 409
                )
            next_state = "WAITING" if ready else "UNCONFIGURED"
            conn.execute(
                OUTBOX.update()
                .where(OUTBOX.c.id == identity)
                .values(
                    state=next_state,
                    error_code=None if ready else "ZALO_UNCONFIGURED",
                    version=row.version + 1,
                    updated_at=utc_now(),
                )
            )
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_outbox",
                entity_id=identity,
                action="retry",
                before={"state": row.state, "version": row.version},
                after={"state": next_state, "version": row.version + 1},
            )
            return {"id": identity, "state": next_state}

        result = self.command(
            actor,
            "retry",
            command.request_key,
            {"id": identity, "version": command.expected_version},
            operation,
        )
        return self.delivery_result(actor, result["id"])
