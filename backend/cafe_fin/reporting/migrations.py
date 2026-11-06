"""Append-only reporting schema, registered via the public module manifest."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from cafe_fin.core.modules import Migration, schema_checksum

metadata = MetaData()
REPORTS = Table(
    "reporting_reports",
    metadata,
    Column("id", String, primary_key=True),
    Column("series_key", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("from_on", String, nullable=False),
    Column("through_on", String, nullable=False),
    Column("state", String, nullable=False),
    Column("snapshot_json", Text, nullable=False),
    Column("sha256", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("command_key", String, nullable=False),
    Column("saved_at", String),
    UniqueConstraint("series_key", "version"),
    UniqueConstraint("created_by", "command_key"),
    CheckConstraint("state IN ('PREVIEW','SAVED')"),
    Index("reporting_period_idx", "from_on", "created_at"),
)
EXPORTS = Table(
    "reporting_exports",
    metadata,
    Column("id", String, primary_key=True),
    Column("report_id", ForeignKey("reporting_reports.id"), nullable=False),
    Column("format", String, nullable=False),
    Column("file_id", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("size", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint("report_id", "format"),
)
SETTINGS = Table(
    "reporting_settings",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("config_json", Text, nullable=False),
    Column("updated_at", String, nullable=False),
)
OUTBOX = Table(
    "reporting_outbox",
    metadata,
    Column("id", String, primary_key=True),
    Column("report_id", ForeignKey("reporting_reports.id"), nullable=False),
    Column("destination", String, nullable=False),
    Column("oa_id", String, nullable=False),
    Column("config_version", Integer, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("attachment_export_id", ForeignKey("reporting_exports.id")),
    Column("state", String, nullable=False),
    Column("phase", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("message_id", String),
    Column("file_message_id", String),
    Column("error_code", String),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint("report_id", "destination", "oa_id"),
    CheckConstraint("state IN ('WAITING','SENDING','SENT','FAILED','UNKNOWN','UNCONFIGURED')"),
    Index("reporting_queue_idx", "state", "created_at"),
)
ATTEMPTS = Table(
    "reporting_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("outbox_id", ForeignKey("reporting_outbox.id"), nullable=False),
    Column("phase", String, nullable=False),
    Column("outcome", String, nullable=False),
    Column("code", String),
    Column("message_id", String),
    Column("created_at", String, nullable=False),
    Index("reporting_attempt_idx", "outbox_id", "created_at"),
)
LOCKS = Table(
    "reporting_locks",
    metadata,
    Column("id", String, primary_key=True),
    Column("owner", String, nullable=False),
)

TRIGGERS = (
    """CREATE TRIGGER reporting_snapshot_immutable BEFORE UPDATE OF
    id,series_key,version,from_on,through_on,snapshot_json,sha256,reason,created_at,created_by,command_key
    ON reporting_reports BEGIN SELECT RAISE(ABORT,'immutable report snapshot'); END""",
    """CREATE TRIGGER reporting_snapshot_no_delete BEFORE DELETE ON reporting_reports
    BEGIN SELECT RAISE(ABORT,'immutable report snapshot'); END""",
    """CREATE TRIGGER reporting_saved_no_revert BEFORE UPDATE OF state ON reporting_reports
    WHEN OLD.state='SAVED' AND NEW.state!='SAVED'
    BEGIN SELECT RAISE(ABORT,'saved report cannot revert'); END""",
    """CREATE TRIGGER reporting_payload_immutable BEFORE UPDATE OF
    report_id,destination,oa_id,config_version,payload_json,attachment_export_id ON reporting_outbox
    BEGIN SELECT RAISE(ABORT,'immutable delivery payload'); END""",
    """CREATE TRIGGER reporting_exports_immutable BEFORE UPDATE ON reporting_exports
    BEGIN SELECT RAISE(ABORT,'immutable export'); END""",
    """CREATE TRIGGER reporting_exports_no_delete BEFORE DELETE ON reporting_exports
    BEGIN SELECT RAISE(ABORT,'immutable export'); END""",
)


def migrate(conn):
    metadata.create_all(conn)
    for statement in TRIGGERS:
        conn.exec_driver_sql(statement)


MIGRATIONS = (
    Migration(
        "reporting",
        1,
        "immutable_reports_and_outbox",
        migrate,
        checksum=schema_checksum(metadata, TRIGGERS),
    ),
)
