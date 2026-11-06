"""Owner restore quarantine, before any recovery/startup/worker; no secret IO."""

from sqlalchemy import case, func, select

from cafe_fin.core.activation import ActivationContext, activation_context
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from .local_exports import invalidate_relocated_copies
from .migrations import OUTBOX, REPORTS, SETTINGS
from .schedule_migrations import DAILY_RUNS

REVIEW_CODE = "RESTORE_REVIEW_REQUIRED"
GUARD_ACTOR = "reporting.activation"
GUARD_ACTION = "reporting.activation_guard"


def suspended(config):
    review = config.get("restore_review")
    return isinstance(review, dict) and review.get("required") is True


def require_reviewed(config):
    if suspended(config):
        raise CoreError(
            REVIEW_CODE,
            "Dữ liệu vừa khôi phục; Admin cần kiểm tra và bật lại lịch trong Cấu hình Admin trước khi gửi/đối chiếu.",
            409,
        )


def held_report(report_id):
    # Applies across destinations: a restored UNKNOWN cannot become automatic
    # work merely because a later Admin chooses another OA/group.
    hold = OUTBOX.alias("restore_hold")
    return (
        select(hold.c.id)
        .where(
            hold.c.report_id == report_id,
            hold.c.state == "UNKNOWN",
            hold.c.error_code == REVIEW_CODE,
        )
        .exists()
    )


def held_series(series_key):
    # Any restored uncertain version holds automatic work for the whole day/book
    # series, including an already-saved newer version and another destination.
    report = REPORTS.alias("restore_held_series")
    return (
        select(report.c.id)
        .where(report.c.series_key == series_key, held_report(report.c.id))
        .exists()
    )


def positive(column):
    return func.length(column).between(1, 256) & ~column.bool_op("GLOB")("*[^A-Za-z0-9_-]*")


def apply_guard(service, actor, context):
    if not isinstance(context, ActivationContext) or context.kind not in {"move", "restore"}:
        raise CoreError("RESTORE_CONTEXT_INVALID", "Thiếu thông tin kích hoạt đã xác minh.", 409)
    service.runtime.writer.run(service.authorize(actor, "core.manage"))
    if activation_context(service.runtime.root) != context:
        raise CoreError("RESTORE_CONTEXT_INVALID", "Thông tin kích hoạt không khớp dữ liệu.", 409)

    def operation(conn):
        if service.runtime.maintenance.status()["state"] != "ACTIVATING":
            raise CoreError(
                "RESTORE_CONTEXT_INVALID", "Bộ chặn phải chạy trong lần kích hoạt dữ liệu.", 409
            )
        if context.kind == "move":
            result = {"activation_id": context.activation_id, "kind": "move", "quarantined": 0}
        else:
            old = service.settings(conn)
            now = utc_now()
            eligible = OUTBOX.c.state.in_(
                ("WAITING", "FAILED", "UNCONFIGURED", "SENDING", "UNKNOWN")
            )
            proof = positive(OUTBOX.c.message_id) & (
                OUTBOX.c.attachment_export_id.is_(None) | positive(OUTBOX.c.file_message_id)
            )
            total = conn.execute(
                select(func.count()).select_from(OUTBOX).where(eligible)
            ).scalar_one()
            confirmed = conn.execute(
                select(func.count()).select_from(OUTBOX).where(eligible, proof)
            ).scalar_one()
            conn.execute(
                OUTBOX.update()
                .where(eligible)
                .values(
                    state=case((proof, "SENT"), else_="UNKNOWN"),
                    phase=case((proof, "complete"), else_=OUTBOX.c.phase),
                    error_code=case((proof, None), else_=REVIEW_CODE),
                    version=OUTBOX.c.version + 1,
                    updated_at=now,
                )
            )
            runs = conn.execute(
                DAILY_RUNS.update()
                .where(DAILY_RUNS.c.state.in_(("PENDING", "RUNNING", "FAILED", "BLOCKED")))
                .values(state="NEEDS_MANUAL", error_code=REVIEW_CODE, updated_at=now)
            ).rowcount
            review = {
                "activation_id": context.activation_id,
                "required": True,
                "quarantined_at": now,
                "quarantined_count": total - confirmed,
                "confirmed_count": confirmed,
                "daily_runs_held": runs,
                "reviewed_at": None,
                "reviewed_by": None,
            }
            persisted = {key: value for key, value in old.items() if key != "version"}
            persisted.update(
                enabled=False,
                auto_generate_daily=False,
                auto_activated_on=None,
                scheduled_actor_id=None,
                restore_review=review,
            )
            version = old["version"] + 1
            values = dict(version=version, config_json=canonical_json(persisted), updated_at=now)
            if old["version"]:
                conn.execute(SETTINGS.update().where(SETTINGS.c.id == "delivery").values(**values))
            else:
                conn.execute(SETTINGS.insert().values(id="delivery", **values))
            result = {
                "activation_id": context.activation_id,
                "kind": "restore",
                "quarantined": total - confirmed,
                "confirmed": confirmed,
                "settings_version": version,
            }
            AuditService.record(
                conn,
                actor=actor.id,
                entity="reporting_settings",
                entity_id="delivery",
                action="restore_suspend",
                before=old,
                after={"version": version, **persisted},
            )
        result["local_exports_pending"] = invalidate_relocated_copies(
            conn, actor, context.activation_id
        )
        AuditService.record(
            conn,
            actor=actor.id,
            entity="reporting_activation",
            entity_id=context.activation_id,
            action="restore_quarantine" if context.kind == "restore" else "move_keep",
            after=result,
        )
        return result

    return service.runtime.writer.execute(
        GUARD_ACTOR,
        GUARD_ACTION,
        context.activation_id,
        context.marker(),
        operation,
        authorize=service.authorize(actor, "core.manage"),
    )
