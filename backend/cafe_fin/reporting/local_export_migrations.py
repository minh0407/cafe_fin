"""Append-only reporting migration 3; prior checksums remain unchanged."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, String, Table

from cafe_fin.core.modules import Migration, schema_checksum

from .migrations import EXPORTS

metadata = MetaData()
LOCAL_EXPORTS = Table(
    "reporting_local_exports",
    metadata,
    Column("export_id", ForeignKey(EXPORTS.c.id), primary_key=True),
    Column("relative_key", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("size", Integer, nullable=False),
    Column("state", String, nullable=False),
    Column("error_code", String),
    Column("attempts", Integer, nullable=False),
    Column("verified_at", String),
    Column("updated_at", String, nullable=False),
    CheckConstraint("state IN ('COPYING','PENDING','READY','FAILED','CONFLICT')"),
    Index("reporting_local_state_idx", "state"),
)
TRIGGERS = (
    """CREATE TRIGGER reporting_local_pins_immutable BEFORE UPDATE OF
    export_id,relative_key,sha256,size ON reporting_local_exports
    BEGIN SELECT RAISE(ABORT,'immutable local export reference'); END""",
    """CREATE TRIGGER reporting_local_no_delete BEFORE DELETE ON reporting_local_exports
    BEGIN SELECT RAISE(ABORT,'durable local export state'); END""",
)


def migrate(conn):
    metadata.create_all(conn)
    for statement in TRIGGERS:
        conn.exec_driver_sql(statement)


MIGRATIONS = (
    Migration(
        "reporting",
        3,
        "human_readable_local_exports",
        migrate,
        checksum=schema_checksum(metadata, TRIGGERS),
    ),
)
