"""Additive provider transition; migrations 1/2/3 and historical payloads stay frozen."""

import json

from sqlalchemy import Column, Integer, MetaData, String, cast, func, select

from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import canonical_json
from cafe_fin.core.modules import Migration, schema_checksum
from cafe_fin.core.time import utc_now

from . import migrations as legacy
from .schedule_migrations import DAILY_RUNS

metadata = MetaData()
for table in legacy.metadata.sorted_tables:
    table.to_metadata(metadata)
OUTBOX = metadata.tables[legacy.OUTBOX.name]
ATTEMPTS = metadata.tables[legacy.ATTEMPTS.name]
for column in (
    Column("provider", String, nullable=False, server_default="zalo_legacy"),
    Column("bot_id", String),
    Column("chat_id", String),
    Column("message_chat_id", String),
    Column("file_message_chat_id", String),
    Column("retry_not_before", String),
):
    OUTBOX.append_column(column)
for column in (
    Column("provider", String, nullable=False, server_default="zalo_legacy"),
    Column("bot_id", String),
    Column("chat_id", String),
    Column("retry_after_seconds", Integer),
):
    ATTEMPTS.append_column(column)

STATEMENTS = (
    "ALTER TABLE reporting_outbox ADD COLUMN provider TEXT NOT NULL DEFAULT 'zalo_legacy' CHECK(provider IN ('telegram','zalo_legacy'))",
    "ALTER TABLE reporting_outbox ADD COLUMN bot_id TEXT",
    "ALTER TABLE reporting_outbox ADD COLUMN chat_id TEXT",
    "ALTER TABLE reporting_outbox ADD COLUMN message_chat_id TEXT",
    "ALTER TABLE reporting_outbox ADD COLUMN file_message_chat_id TEXT",
    "ALTER TABLE reporting_outbox ADD COLUMN retry_not_before TEXT",
    "ALTER TABLE reporting_attempts ADD COLUMN provider TEXT NOT NULL DEFAULT 'zalo_legacy' CHECK(provider IN ('telegram','zalo_legacy'))",
    "ALTER TABLE reporting_attempts ADD COLUMN bot_id TEXT",
    "ALTER TABLE reporting_attempts ADD COLUMN chat_id TEXT",
    "ALTER TABLE reporting_attempts ADD COLUMN retry_after_seconds INTEGER",
    "CREATE INDEX reporting_provider_queue_idx ON reporting_outbox(provider,state,created_at)",
    "CREATE INDEX reporting_bot_cooldown_idx ON reporting_outbox(provider,bot_id,retry_not_before)",
    "CREATE INDEX reporting_bot_review_idx ON reporting_attempts(provider,bot_id,code)",
    "DROP TRIGGER reporting_payload_immutable",
    """CREATE TRIGGER reporting_payload_immutable BEFORE UPDATE OF
    report_id,destination,oa_id,config_version,payload_json,attachment_export_id,provider,bot_id,chat_id
    ON reporting_outbox BEGIN SELECT RAISE(ABORT,'immutable delivery payload'); END""",
    """CREATE TRIGGER reporting_attempt_immutable BEFORE UPDATE ON reporting_attempts
    BEGIN SELECT RAISE(ABORT,'immutable delivery attempt'); END""",
    """CREATE TRIGGER reporting_attempt_no_delete BEFORE DELETE ON reporting_attempts
    BEGIN SELECT RAISE(ABORT,'immutable delivery attempt'); END""",
)
TRANSITION_CODE = "PROVIDER_TRANSITION_REVIEW_REQUIRED"


def receipt_proof(message_id, receipt_chat_id, chat_id):
    return (
        func.length(message_id).between(1, 16)
        & ~message_id.bool_op("GLOB")("*[^0-9]*")
        & (func.substr(message_id, 1, 1) != "0")
        & (cast(message_id, Integer) <= 2**52 - 1)
        & (receipt_chat_id == chat_id)
        & chat_id.is_not(None)
        & func.length(chat_id).between(2, 17)
        & (func.substr(chat_id, 1, 1) == "-")
        & (func.substr(chat_id, 2, 1) != "0")
        & ~func.substr(chat_id, 2).bool_op("GLOB")("*[^0-9]*")
        & cast(chat_id, Integer).between(-(2**52 - 1), -1)
    )


def migrate(conn):
    for statement in STATEMENTS:
        conn.exec_driver_sql(statement)
    now = utc_now()
    held = conn.execute(
        OUTBOX.update()
        .where(OUTBOX.c.state.in_(("WAITING", "SENDING", "FAILED", "UNKNOWN", "UNCONFIGURED")))
        .values(
            state="UNKNOWN",
            error_code=TRANSITION_CODE,
            version=OUTBOX.c.version + 1,
            updated_at=now,
        )
    ).rowcount
    runs = conn.execute(
        DAILY_RUNS.update()
        .where(DAILY_RUNS.c.state.in_(("PENDING", "RUNNING", "FAILED", "BLOCKED")))
        .values(state="NEEDS_MANUAL", error_code=TRANSITION_CODE, updated_at=now)
    ).rowcount
    old = (
        conn.execute(select(legacy.SETTINGS).where(legacy.SETTINGS.c.id == "delivery"))
        .mappings()
        .first()
    )
    if old:
        before = json.loads(old.config_json)
        config = {
            "provider": "telegram",
            "chat_id": "",
            "bot_id": None,
            "bot_verified_at": None,
            "enabled": False,
            "auto_generate_daily": False,
            "scheduled_actor_id": None,
            "auto_activated_on": None,
            "timezone": before.get("timezone", "Asia/Ho_Chi_Minh"),
            "send_at": before.get("send_at"),
            "attachments_enabled": before.get("attachments_enabled", False),
            "daily_book_ids": before.get("daily_book_ids", []),
            "daily_export_formats": before.get("daily_export_formats", ["pdf", "xlsx", "txt"]),
            "restore_review": before.get("restore_review"),
        }
        conn.execute(
            legacy.SETTINGS.update()
            .where(legacy.SETTINGS.c.id == "delivery")
            .values(
                version=old.version + 1,
                config_json=canonical_json(config),
                updated_at=now,
            )
        )
        AuditService.record(
            conn,
            actor="reporting.provider-transition",
            entity="reporting_settings",
            entity_id="delivery",
            action="provider_transition",
            before={"version": old.version, **before},
            after={"version": old.version + 1, **config},
        )
    if old or held or runs:
        AuditService.record(
            conn,
            actor="reporting.provider-transition",
            entity="reporting_provider",
            entity_id="telegram",
            action="quarantine_legacy",
            after={"held": held, "daily_runs_held": runs},
        )


MIGRATIONS = (
    Migration(
        "reporting",
        4,
        "telegram_provider_transition",
        migrate,
        # to_metadata clones constraint sets whose DDL ordering is not stable
        # across Python hash seeds. ALTER migrations fingerprint actual SQL only.
        checksum=schema_checksum(MetaData(), STATEMENTS),
    ),
)
