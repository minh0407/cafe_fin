"""Durable Telegram sender; uncertain POST outcomes never auto-retry."""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from .downloads import reference
from .migrations import LOCKS
from .models import DATE_RANGE_CONTRACT
from .restore import REVIEW_CODE, suspended
from .service import new_id, outbox_dto
from .telegram import (
    MAX_DOCUMENT_BYTES,
    MAX_RETRY_AFTER,
    PROVIDER,
    DeliveryError,
    access_token,
    receipt_valid,
    stored_receipt,
    valid_chat,
)
from .telegram_migrations import ATTEMPTS, OUTBOX

SAFE_CODES = frozenset(
    {
        "TELEGRAM_NETWORK_ERROR",
        "TELEGRAM_HTTP_ERROR",
        "TELEGRAM_REDIRECT",
        "TELEGRAM_API_REJECTED",
        "TELEGRAM_UNAUTHORIZED",
        "TELEGRAM_FORBIDDEN",
        "TELEGRAM_RESPONSE_INVALID",
        "TELEGRAM_BOT_MISMATCH",
        "TELEGRAM_CHAT_INVALID",
        "TELEGRAM_MEMBERSHIP_DENIED",
        "TELEGRAM_SEND_DENIED",
        "TELEGRAM_CONFIG_CHANGED",
        "TELEGRAM_UNCONFIGURED",
        "TELEGRAM_RECEIPT_INVALID",
        "TELEGRAM_RATE_LIMITED",
        "TELEGRAM_RETRY_REVIEW_REQUIRED",
        "TELEGRAM_TEXT_INVALID",
        "TELEGRAM_ATTACHMENT_INVALID",
        "ATTACHMENT_DISABLED",
        "SENDER_INTERRUPTED",
        "REPORT_PERIOD_CONTRACT_REQUIRED",
    }
)


def safe_code(value):
    return value if value is None or value in SAFE_CODES else "TELEGRAM_TRANSPORT_ERROR"


@contextmanager
def sender_lock(service):
    owner = new_id()

    def acquire(conn):
        if conn.execute(select(LOCKS).where(LOCKS.c.id == "sender")).first():
            return False
        conn.execute(LOCKS.insert().values(id="sender", owner=owner))
        return True

    locked = service.runtime.writer.run(acquire)
    try:
        yield locked
    finally:
        if locked:
            service.runtime.writer.run(
                lambda conn: conn.execute(
                    LOCKS.delete().where(LOCKS.c.id == "sender", LOCKS.c.owner == owner)
                )
            )


def complete_proof(row):
    return (
        row.provider == PROVIDER
        and stored_receipt(row.message_id, row.message_chat_id, row.chat_id)
        and (
            row.attachment_export_id is None
            or stored_receipt(row.file_message_id, row.file_message_chat_id, row.chat_id)
        )
    )


def attempt(conn, row, phase, outcome, *, code=None, receipt=None, retry_after=None):
    conn.execute(
        ATTEMPTS.insert().values(
            id=new_id(),
            outbox_id=row.id,
            provider=row.provider,
            bot_id=row.bot_id,
            chat_id=row.chat_id,
            phase=phase,
            outcome=outcome,
            code=code,
            message_id=str(receipt.message_id) if receipt else None,
            retry_after_seconds=retry_after,
            created_at=utc_now(),
        )
    )


def finish(
    service,
    identity,
    state,
    phase,
    *,
    code=None,
    message_id=None,
    file_message_id=None,
    retry_after=None,
    authorize=None,
    expected_version=None,
    expected_state=None,
):
    code = safe_code(code)
    if retry_after is not None and (
        type(retry_after) is not int or not 1 <= retry_after <= MAX_RETRY_AFTER
    ):
        code, retry_after = "TELEGRAM_RETRY_REVIEW_REQUIRED", None

    def operation(conn):
        nonlocal state, phase, code
        if authorize is not None:
            authorize(conn)
        row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one()
        if row.provider != PROVIDER:
            raise CoreError("LEGACY_DELIVERY_READ_ONLY", "Lượt kênh cũ chỉ để tra cứu.", 409)
        if expected_version is not None:
            require_version(row.version, expected_version)
        if expected_state is not None and row.state != expected_state:
            raise CoreError("DELIVERY_RECONCILE_CONFLICT", "Trạng thái lượt gửi đã đổi.", 409)
        if row.state == "SENT":
            return outbox_dto(row)
        if state == "UNKNOWN" and complete_proof(row):
            state, phase, code = "SENT", "complete", None
        values = dict(
            state=state,
            phase=phase,
            error_code=code,
            version=row.version + 1,
            updated_at=utc_now(),
            retry_not_before=(
                service.clock().astimezone(timezone.utc) + timedelta(seconds=retry_after)
            ).isoformat()
            if retry_after
            else None,
        )
        for receipt, message_field, chat_field in (
            (message_id, "message_id", "message_chat_id"),
            (file_message_id, "file_message_id", "file_message_chat_id"),
        ):
            if receipt is not None:
                if not receipt_valid(receipt, row.chat_id):
                    raise DeliveryError("TELEGRAM_RECEIPT_INVALID", unknown=True)
                values[message_field], values[chat_field] = str(receipt.message_id), receipt.chat_id
        conn.execute(OUTBOX.update().where(OUTBOX.c.id == identity).values(**values))
        receipt = file_message_id or message_id
        AuditService.record(
            conn,
            actor="reporting.sender",
            entity="reporting_outbox",
            entity_id=identity,
            action="transition",
            before={"state": row.state, "phase": row.phase, "version": row.version},
            after={
                "state": state,
                "phase": phase,
                "code": code,
                "message_id": str(receipt.message_id) if receipt else None,
                "provider": PROVIDER,
                "chat_id": row.chat_id,
                "version": values["version"],
            },
        )
        attempt(conn, row, phase, state, code=code, receipt=receipt, retry_after=retry_after)
        return outbox_dto(
            conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one()
        )

    return service.runtime.writer.run(operation)


def document_content(service, actor, row):
    pinned = reference(service, actor, row["report_id"], row["attachment_export_id"])
    item = pinned[0]
    if item["format"] not in {"pdf", "xlsx"} or not 0 < item["size"] <= MAX_DOCUMENT_BYTES:
        raise DeliveryError("TELEGRAM_ATTACHMENT_INVALID")
    with service.runtime.files.read(item["file_id"]) as source:
        content = source.read(MAX_DOCUMENT_BYTES + 1)
    if (
        len(content) != item["size"]
        or hashlib.sha256(content).hexdigest() != item["sha256"]
        or reference(service, actor, row["report_id"], item["id"]) != pinned
    ):
        raise DeliveryError("TELEGRAM_ATTACHMENT_INVALID")
    return content, "CafeFin-summary." + item["format"]


def bot_cooldown(service, config):
    if not config.get("bot_id"):
        return None
    with service.runtime.reader() as conn:
        review = conn.execute(
            select(ATTEMPTS.c.id)
            .where(
                ATTEMPTS.c.provider == PROVIDER,
                ATTEMPTS.c.bot_id == config["bot_id"],
                ATTEMPTS.c.code == "TELEGRAM_RETRY_REVIEW_REQUIRED",
            )
            .limit(1)
        ).first()
        until = conn.execute(
            select(func.max(OUTBOX.c.retry_not_before)).where(
                OUTBOX.c.provider == PROVIDER, OUTBOX.c.bot_id == config["bot_id"]
            )
        ).scalar_one()
    if review:
        return {"state": "BLOCKED", "code": "TELEGRAM_RETRY_REVIEW_REQUIRED"}
    if until:
        try:
            deadline = datetime.fromisoformat(until)
            if deadline.tzinfo is None:
                raise ValueError()
            if service.clock().astimezone(timezone.utc) < deadline:
                return {
                    "state": "COOLDOWN",
                    "code": "TELEGRAM_RATE_LIMITED",
                    "retry_not_before": until,
                }
        except (ValueError, TypeError):
            return {"state": "BLOCKED", "code": "TELEGRAM_RETRY_REVIEW_REQUIRED"}
    return None


def dispatch_one(service):
    if service.runtime.maintenance.status()["state"] != "ACTIVE":
        return {"state": "BLOCKED", "code": "RUNTIME_NOT_ACTIVE"}
    if suspended(service.settings()):
        return {"state": "SUSPENDED", "code": REVIEW_CODE}
    with sender_lock(service) as locked:
        if not locked:
            return {"state": "BUSY"}
        config = service.settings()
        if suspended(config):
            return {"state": "SUSPENDED", "code": REVIEW_CODE}
        if not config["enabled"]:
            return {"state": "DISABLED"}
        cooldown = bot_cooldown(service, config)
        if cooldown:
            return cooldown
        try:
            actor = service.resolve_scheduled_actor(config)
        except CoreError:
            return {"state": "BLOCKED", "code": "SCHEDULE_ACTOR_BLOCKED"}
        ready, token = service.credential_ready(config), None
        if ready:
            try:
                token = access_token(service, config)
            except DeliveryError:
                ready = False

        def claim(conn):
            service.guard_schedule(conn, config, actor)
            route = (OUTBOX.c.bot_id == config["bot_id"]) & (OUTBOX.c.chat_id == config["chat_id"])
            if not ready:
                route = route | (OUTBOX.c.bot_id.is_(None) & (OUTBOX.c.destination == ""))
            row = (
                conn.execute(
                    select(OUTBOX)
                    .where(
                        OUTBOX.c.provider == PROVIDER,
                        OUTBOX.c.state == "WAITING",
                        route,
                    )
                    .order_by(OUTBOX.c.created_at, OUTBOX.c.id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            if not ready or not row.bot_id or not valid_chat(row.chat_id):
                conn.execute(
                    OUTBOX.update()
                    .where(OUTBOX.c.id == row.id)
                    .values(
                        state="UNCONFIGURED",
                        error_code="TELEGRAM_UNCONFIGURED",
                        version=row.version + 1,
                        updated_at=utc_now(),
                    )
                )
                AuditService.record(
                    conn,
                    actor="reporting.sender",
                    entity="reporting_outbox",
                    entity_id=row.id,
                    action="unconfigured",
                    before={"state": row.state, "version": row.version},
                    after={"state": "UNCONFIGURED", "version": row.version + 1},
                )
                return outbox_dto(
                    conn.execute(select(OUTBOX).where(OUTBOX.c.id == row.id)).mappings().one()
                )
            conn.execute(
                OUTBOX.update()
                .where(OUTBOX.c.id == row.id)
                .values(
                    state="SENDING",
                    attempts=row.attempts + 1,
                    version=row.version + 1,
                    updated_at=utc_now(),
                )
            )
            attempt(conn, row, "preflight", "SENDING")
            return dict(row)

        row = service.runtime.writer.run(claim)
        if not row:
            return (
                {"state": "IDLE"}
                if ready
                else {"state": "UNCONFIGURED", "code": "TELEGRAM_UNCONFIGURED"}
            )
        if row["state"] == "UNCONFIGURED":
            return row
        identity, phase, confirmed_text, confirmed_file, content = (
            row["id"],
            "preflight",
            None,
            None,
            None,
        )
        try:
            payload = json.loads(row["payload_json"])
            if payload.get("date_range_contract") != DATE_RANGE_CONTRACT:
                raise DeliveryError("REPORT_PERIOD_CONTRACT_REQUIRED")
            if (
                row["chat_id"] != config["chat_id"]
                or row["bot_id"] != config["bot_id"]
                or payload.get("provider") != PROVIDER
                or payload.get("bot_id") != row["bot_id"]
                or payload.get("chat_id") != row["chat_id"]
            ):
                raise DeliveryError("TELEGRAM_CONFIG_CHANGED")
            if row["attachment_export_id"] and not config["attachments_enabled"]:
                raise DeliveryError("ATTACHMENT_DISABLED")
            content = document_content(service, actor, row) if row["attachment_export_id"] else None
            service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
            if (
                service.transport.verify(
                    token, row["chat_id"], row["bot_id"], documents=bool(content)
                )
                != row["bot_id"]
            ):
                raise DeliveryError("TELEGRAM_BOT_MISMATCH")
            if not stored_receipt(row["message_id"], row["message_chat_id"], row["chat_id"]):
                service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
                phase = "text"
                receipt = service.transport.send_text(
                    token, row["chat_id"], payload["text"], row["bot_id"]
                )
                if not receipt_valid(receipt, row["chat_id"]):
                    raise DeliveryError("TELEGRAM_RECEIPT_INVALID", unknown=True)
                confirmed_text = receipt
                if not content:
                    return finish(service, identity, "SENT", "complete", message_id=receipt)
                finish(service, identity, "SENDING", "attachment", message_id=receipt)
            if content:
                phase = "preflight_document"
                service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
                phase = "attachment"  # sendDocument itself sends; it is not an inert upload.
                receipt = service.transport.send_document(
                    token, row["chat_id"], *content, row["bot_id"]
                )
                if not receipt_valid(receipt, row["chat_id"]):
                    raise DeliveryError("TELEGRAM_RECEIPT_INVALID", unknown=True)
                confirmed_file = receipt
                return finish(service, identity, "SENT", "complete", file_message_id=receipt)
            return finish(service, identity, "SENT", "complete")
        except DeliveryError as exc:
            state = (
                "UNKNOWN"
                if exc.unknown and phase in {"text", "attachment"}
                else "UNCONFIGURED"
                if exc.code == "TELEGRAM_UNCONFIGURED"
                else "FAILED"
            )
            return finish(
                service, identity, state, phase, code=exc.code, retry_after=exc.retry_after
            )
        except Exception:
            if confirmed_file:
                return finish(service, identity, "SENT", "complete", file_message_id=confirmed_file)
            if confirmed_text and not content:
                return finish(service, identity, "SENT", "complete", message_id=confirmed_text)
            if confirmed_text and phase in {"text", "preflight_document"}:
                # Text was positively acknowledged; document has not been POSTed.
                # Retain proof even if its first persistence/ACK failed.
                return finish(
                    service,
                    identity,
                    "FAILED",
                    "preflight_document",
                    code="SENDER_INTERRUPTED",
                    message_id=confirmed_text,
                )
            return finish(
                service,
                identity,
                "UNKNOWN" if phase in {"text", "attachment"} else "FAILED",
                phase,
                code="SENDER_INTERRUPTED",
                message_id=confirmed_text,
            )


def check_connection(service, actor):
    def authorize(conn):
        service.authorize(actor, "core.manage")(conn)
        service.require_delivery_review(conn)

    service.runtime.writer.run(authorize)
    with sender_lock(service) as locked:
        if not locked:
            raise CoreError("SENDER_BUSY", "Bộ gửi đang bận.", 409)
        config = service.settings()
        if not valid_chat(config["chat_id"]) or not config["bot_id"]:
            return {"state": "UNCONFIGURED", "code": "TELEGRAM_UNCONFIGURED"}
        cooldown = bot_cooldown(service, config)
        if cooldown:
            return cooldown
        try:
            token = access_token(service, config)
            identity = service.transport.verify(
                token, config["chat_id"], config["bot_id"], documents=config["attachments_enabled"]
            )
            if identity != config["bot_id"]:
                raise DeliveryError("TELEGRAM_BOT_MISMATCH")
            updated = service.record_bot(
                actor, identity, verified=True, expected_version=config["version"]
            )
            return {
                "state": "CONNECTED",
                "code": None,
                "bot_id": identity,
                "version": updated["version"],
            }
        except DeliveryError as exc:
            return {
                "state": "UNCONFIGURED" if exc.code == "TELEGRAM_UNCONFIGURED" else "FAILED",
                "code": safe_code(exc.code),
            }
        except CoreError:
            raise
        except Exception:
            return {"state": "FAILED", "code": "TELEGRAM_TRANSPORT_ERROR"}


def reconcile(service, actor, identity, command):
    def operation(conn):
        row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().first()
        if not row or row.state != "UNKNOWN" or row.version != command.expected_version:
            raise CoreError(
                "DELIVERY_RECONCILE_CONFLICT", "Lượt gửi không ở phiên bản chưa rõ đã chọn.", 409
            )
        AuditService.record(
            conn,
            actor=actor.id,
            entity="reporting_outbox",
            entity_id=identity,
            action="manual_comparison_required",
            after={"provider": row.provider, "state": "UNKNOWN"},
        )
        return outbox_dto(row)

    result = service.command(
        actor,
        "reconcile",
        command.request_key,
        {"id": identity, "version": command.expected_version},
        operation,
        admin=True,
    )
    return service.delivery_result(actor, result["id"])
