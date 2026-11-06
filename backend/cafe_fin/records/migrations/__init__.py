"""Immutable records v1 schema; only this module owns these tables."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
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
DOCUMENTS = Table(
    "records_documents",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("id", String, nullable=False, unique=True),
    Column("kind", String, nullable=False),
    Column("code_key", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("created_by", String, nullable=False),
    UniqueConstraint("kind", "code_key"),
    CheckConstraint("version > 0"),
    sqlite_autoincrement=True,
)
REVISIONS = Table(
    "records_revisions",
    metadata,
    Column("document_id", String, ForeignKey("records_documents.id"), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("recorded_at", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("data_json", Text, nullable=False),
    Column("occurred_on", String),
    Column("status", String),
    Column("commercial_scaled", Integer),
    Column("deleted_at", String),
    CheckConstraint("version > 0"),
)
Index("records_revision_cutoff", REVISIONS.c.recorded_at, REVISIONS.c.document_id)
MOVEMENTS = Table(
    "records_movements",
    metadata,
    Column("id", String, primary_key=True),
    Column("entry_id", String, ForeignKey("records_documents.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("product_id", String, ForeignKey("records_documents.id"), nullable=False),
    Column("warehouse_id", String, ForeignKey("records_documents.id"), nullable=False),
    Column("direction", String, nullable=False),
    Column("delta_scaled", Integer, nullable=False),
    Column("occurred_on", String, nullable=False),
    Column("order_key", String, nullable=False),
    Column("entry_type", String, nullable=False),
    Column("line_numbers", Text, nullable=False),
    UniqueConstraint("entry_id", "version", "product_id", "warehouse_id", "direction"),
    ForeignKeyConstraint(
        ["entry_id", "version"], ["records_revisions.document_id", "records_revisions.version"]
    ),
    CheckConstraint("delta_scaled != 0"),
)
Index(
    "records_stock_scope",
    MOVEMENTS.c.product_id,
    MOVEMENTS.c.warehouse_id,
    MOVEMENTS.c.occurred_on,
    MOVEMENTS.c.order_key,
)
REFERENCES = Table(
    "records_references",
    metadata,
    Column("document_id", String, ForeignKey("records_documents.id"), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("target_id", String, ForeignKey("records_documents.id"), primary_key=True),
    ForeignKeyConstraint(
        ["document_id", "version"], ["records_revisions.document_id", "records_revisions.version"]
    ),
)
LINES = Table(
    "records_lines",
    metadata,
    Column("document_id", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("line_number", Integer, primary_key=True),
    Column("product_id", String, ForeignKey("records_documents.id")),
    Column("warehouse_id", String, ForeignKey("records_documents.id")),
    Column("quantity_scaled", Integer),
    Column("gross_scaled", Integer),
    Column("tare_scaled", Integer),
    Column("net_scaled", Integer),
    Column("quantity_source", String),
    Column("direction", String),
    ForeignKeyConstraint(
        ["document_id", "version"], ["records_revisions.document_id", "records_revisions.version"]
    ),
    CheckConstraint("line_number > 0"),
    CheckConstraint("quantity_scaled IS NULL OR quantity_scaled > 0"),
    CheckConstraint("gross_scaled IS NULL OR gross_scaled >= 0"),
    CheckConstraint("tare_scaled IS NULL OR tare_scaled >= 0"),
    CheckConstraint("net_scaled IS NULL OR net_scaled >= 0"),
)
TRIGGERS = tuple(
    f"CREATE TRIGGER records_{name}_{action.lower()} BEFORE {action} ON {table} "
    "BEGIN SELECT RAISE(ABORT, 'records history is immutable'); END"
    for name, table in (
        ("revision", "records_revisions"),
        ("movement", "records_movements"),
        ("reference", "records_references"),
        ("line", "records_lines"),
    )
    for action in ("UPDATE", "DELETE")
)


def apply(conn):
    metadata.create_all(conn)
    for sql in TRIGGERS:
        conn.exec_driver_sql(sql)


MIGRATIONS = (
    Migration(
        "records",
        1,
        "versioned_records_and_ledger",
        apply,
        checksum=schema_checksum(metadata, TRIGGERS),
    ),
)
