"""Durable singleton sender; ambiguous post-send outcomes are never auto-retried."""

import json
import re
from contextlib import contextmanager

from sqlalchemy import select

from cafe_fin.core.audit import AuditService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from .migrations import ATTEMPTS, EXPORTS, LOCKS, OUTBOX
from .service import new_id, outbox_dto
from .zalo import DeliveryError, access_token

SAFE_CODES = frozenset(
    {
        "ZALO_NETWORK_ERROR",
        "ZALO_HTTP_ERROR",
        "ZALO_API_REJECTED",
        "ZALO_RESPONSE_INVALID",
        "ZALO_REFRESH_INVALID",
        "ZALO_GROUP_UNAVAILABLE",
        "ZALO_OA_MISMATCH",
        "ZALO_RECEIPT_INVALID",
        "ZALO_UNCONFIGURED",
        "ZALO_REAUTH_REQUIRED",
        "ZALO_CONFIG_CHANGED",
        "ATTACHMENT_DISABLED",
        "ZALO_UPLOAD_CAPABILITY_UNVERIFIED",
        "ZALO_ATTACHMENT_INVALID",
        "ZALO_UPLOAD_INVALID",
        "SENDER_INTERRUPTED",
    }
)


def safe_code(value):
    return value if value is None or value in SAFE_CODES else "ZALO_TRANSPORT_ERROR"


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


def finish(service, identity, state, phase, *, code=None, message_id=None, file_message_id=None):
    code = safe_code(code)

    def operation(conn):
        row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one()
        values = dict(
            state=state, phase=phase, error_code=code, version=row.version + 1, updated_at=utc_now()
        )
        if message_id:
            values["message_id"] = message_id
        if file_message_id:
            values["file_message_id"] = file_message_id
        conn.execute(OUTBOX.update().where(OUTBOX.c.id == identity).values(**values))
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
                "message_id": file_message_id or message_id,
                "version": values["version"],
            },
        )
        conn.execute(
            ATTEMPTS.insert().values(
                id=new_id(),
                outbox_id=identity,
                phase=phase,
                outcome=state,
                code=code,
                message_id=file_message_id or message_id,
                created_at=utc_now(),
            )
        )
        return outbox_dto(
            conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one()
        )

    return service.runtime.writer.run(operation)


def dispatch_one(service):
    with sender_lock(service) as locked:
        if not locked:
            return {"state": "BUSY"}
        config = service.settings()
        if not config["enabled"]:
            return {"state": "DISABLED"}

        def claim(conn):
            row = (
                conn.execute(
                    select(OUTBOX)
                    .where(OUTBOX.c.state == "WAITING")
                    .order_by(OUTBOX.c.created_at, OUTBOX.c.id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
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
            conn.execute(
                ATTEMPTS.insert().values(
                    id=new_id(),
                    outbox_id=row.id,
                    phase="preflight",
                    outcome="SENDING",
                    code=None,
                    message_id=None,
                    created_at=utc_now(),
                )
            )
            return dict(row)

        row = service.runtime.writer.run(claim)
        if not row:
            return {"state": "IDLE"}
        identity, phase = row["id"], "preflight"
        try:
            if row["destination"] != config["group_id"] or row["oa_id"] != config["oa_id"]:
                raise DeliveryError("ZALO_CONFIG_CHANGED")
            if row["attachment_export_id"] and not config["attachments_enabled"]:
                raise DeliveryError("ATTACHMENT_DISABLED")
            if row["attachment_export_id"] and not getattr(
                service.transport, "upload_verified", True
            ):
                raise DeliveryError("ZALO_UPLOAD_CAPABILITY_UNVERIFIED")
            token = access_token(service, config)
            service.transport.verify(token, row["oa_id"], row["destination"])
            if not row["message_id"]:
                phase = "text"
                receipt = service.transport.send_text(
                    token, row["destination"], json.loads(row["payload_json"])["text"]
                )
                if not isinstance(receipt, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,256}", receipt
                ):
                    raise DeliveryError("ZALO_RECEIPT_INVALID", unknown=True)
                # Save text receipt before any attachment work. Crash cannot resend text.
                finish(
                    service,
                    identity,
                    "SENDING",
                    "attachment" if row["attachment_export_id"] else "complete",
                    message_id=receipt,
                )
            if row["attachment_export_id"]:
                phase = "upload"
                with service.runtime.reader() as conn:
                    export = (
                        conn.execute(
                            select(EXPORTS).where(EXPORTS.c.id == row["attachment_export_id"])
                        )
                        .mappings()
                        .one()
                    )
                with service.runtime.files.read(export.file_id) as source:
                    content = source.read(5 * 1024 * 1024 + 1)
                upload = service.transport.upload(
                    token, content, "CafeFin-summary." + export.format
                )
                phase = "attachment"
                receipt = service.transport.send_file(token, row["destination"], upload)
                if not isinstance(receipt, str) or not re.fullmatch(
                    r"[A-Za-z0-9_-]{1,256}", receipt
                ):
                    raise DeliveryError("ZALO_RECEIPT_INVALID", unknown=True)
                return finish(service, identity, "SENT", "complete", file_message_id=receipt)
            return finish(service, identity, "SENT", "complete")
        except DeliveryError as exc:
            state = (
                "UNKNOWN"
                if exc.unknown and phase in {"text", "attachment"}
                else ("UNCONFIGURED" if exc.code == "ZALO_UNCONFIGURED" else "FAILED")
            )
            return finish(service, identity, state, phase, code=exc.code)
        except Exception:
            # Unknown implementation/IO error after entering send: keep ambiguous,
            # persist only a fixed code, never exception text or credential values.
            return finish(
                service,
                identity,
                "UNKNOWN" if phase in {"text", "attachment"} else "FAILED",
                phase,
                code="SENDER_INTERRUPTED",
            )


def check_connection(service, actor):
    service.runtime.writer.run(service.authorize(actor, "core.manage"))
    with sender_lock(service) as locked:
        if not locked:
            raise CoreError("SENDER_BUSY", "Bộ gửi đang bận.", 409)
        config = service.settings()
        if not config["group_id"] or not config["oa_id"]:
            return {"state": "UNCONFIGURED", "code": "ZALO_UNCONFIGURED"}
        try:
            token = access_token(service, config)
            service.transport.verify(token, config["oa_id"], config["group_id"])
            return {"state": "CONNECTED", "code": None}  # GET checks only; never a test send
        except DeliveryError as exc:
            return {
                "state": "UNCONFIGURED" if exc.code == "ZALO_UNCONFIGURED" else "FAILED",
                "code": safe_code(exc.code),
            }
        except Exception:
            return {"state": "FAILED", "code": "ZALO_TRANSPORT_ERROR"}


def reconcile(service, actor, identity, command):
    service.runtime.writer.run(service.authorize(actor, "core.manage"))
    with sender_lock(service) as locked:
        if not locked:
            raise CoreError("SENDER_BUSY", "Bộ gửi đang bận.", 409)
        with service.runtime.reader() as conn:
            row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().first()
        if not row or row.state != "UNKNOWN" or row.version != command.expected_version:
            raise CoreError(
                "DELIVERY_RECONCILE_CONFLICT", "Lượt gửi không ở phiên bản chưa rõ đã chọn.", 409
            )
        config = service.settings()
        if config["group_id"] != row.destination or config["oa_id"] != row.oa_id:
            raise CoreError(
                "DESTINATION_CHANGED", "Cấu hình hiện tại không khớp đích đã khóa.", 409
            )
        token = access_token(service, config)
        # Protocol must return a positively correlated receipt, never a text-only guess.
        receipt = service.transport.reconcile(
            token, row.destination, json.loads(row.payload_json)["text"]
        )
        if (
            isinstance(receipt, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", receipt)
            and row.phase == "text"
            and not row.attachment_export_id
        ):
            return finish(service, identity, "SENT", "complete", message_id=receipt)
        return outbox_dto(row)  # unresolved -> stays UNKNOWN, no retry or fabricated success
