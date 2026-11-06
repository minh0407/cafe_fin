"""Append-only storage owner reservation for actor-independent output retries."""

from sqlalchemy import Column, MetaData, String, Table

from cafe_fin.core.modules import Migration, schema_checksum

SQL = """CREATE TABLE contracts_output_storage (
    version_id TEXT NOT NULL,
    format TEXT NOT NULL CHECK (format IN ('docx', 'pdf')),
    owner_actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (version_id, format),
    FOREIGN KEY (version_id, format)
        REFERENCES contracts_outputs (version_id, format)
)"""

# This query definition deliberately does not modify v001's immutable metadata.
OUTPUT_STORAGE = Table(
    "contracts_output_storage",
    MetaData(),
    Column("version_id", String, primary_key=True),
    Column("format", String, primary_key=True),
    Column("owner_actor", String, nullable=False),
    Column("created_at", String, nullable=False),
)


def apply(conn):
    conn.exec_driver_sql(SQL)


MIGRATIONS = (
    Migration(
        "contracts",
        2,
        "pin_output_storage_owner",
        apply,
        checksum=schema_checksum(MetaData(), (SQL,)),
    ),
)
