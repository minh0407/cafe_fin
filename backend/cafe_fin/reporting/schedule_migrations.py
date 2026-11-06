"""Reporting migration 2 only; v1 DDL/checksum stays untouched."""

from sqlalchemy import (
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

from .migrations import OUTBOX, REPORTS

metadata = MetaData()
DAILY_RUNS = Table(
    "reporting_daily_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("profile_id", String, nullable=False),
    Column("business_on", String, nullable=False),
    Column("state", String, nullable=False),
    Column("phase", String, nullable=False),
    Column("pins_json", Text, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("config_version", Integer, nullable=False),
    Column("report_id", ForeignKey(REPORTS.c.id)),
    Column("outbox_id", ForeignKey(OUTBOX.c.id)),
    Column("policy", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("error_code", String),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    UniqueConstraint("profile_id", "business_on"),
    Index("reporting_daily_pending_idx", "state", "business_on"),
)
DAILY_CURSOR = Table(
    "reporting_daily_cursor",
    metadata,
    Column("profile_id", String, primary_key=True),
    Column("next_unchecked_on", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
TRIGGERS = (
    """CREATE TRIGGER reporting_daily_pins_immutable BEFORE UPDATE OF
    id,profile_id,business_on,pins_json,actor_id,config_version,created_at ON reporting_daily_runs
    BEGIN SELECT RAISE(ABORT,'immutable daily schedule pins'); END""",
    """CREATE TRIGGER reporting_daily_report_pinned BEFORE UPDATE OF report_id ON reporting_daily_runs
    WHEN OLD.report_id IS NOT NULL AND NOT (NEW.report_id IS OLD.report_id)
    BEGIN SELECT RAISE(ABORT,'immutable daily report reference'); END""",
)


def migrate(conn):
    metadata.create_all(conn)
    for statement in TRIGGERS:
        conn.exec_driver_sql(statement)


MIGRATIONS = (
    Migration(
        "reporting",
        2,
        "durable_daily_generation",
        migrate,
        checksum=schema_checksum(metadata, TRIGGERS),
    ),
)
