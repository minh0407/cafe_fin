"""Additive market settings, daily claims and immutable evidence (records v2)."""

from sqlalchemy import Column, Integer, MetaData, String, Table, Text

from cafe_fin.core.modules import Migration, schema_checksum

metadata = MetaData()
SETTINGS = Table(
    "records_market_settings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("enabled", Integer, nullable=False),
    Column("version", Integer, nullable=False),
)
DAYS = Table(
    "records_market_days",
    metadata,
    Column("price_date", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("last_checked_at", String),
    Column("next_attempt_at", String),
    Column("lease_token", String),
    Column("lease_expires_at", String),
    Column("settings_version", Integer),
    Column("detail", Text),
)
EVIDENCE = Table(
    "records_market_evidence",
    metadata,
    Column("price_date", String, primary_key=True),
    Column("board_id", String, nullable=False, unique=True),
    Column("snapshot_json", Text, nullable=False),
)
SQL = (
    "INSERT INTO records_market_settings(id,enabled,version) VALUES(1,1,1)",
    "CREATE TRIGGER records_market_evidence_update BEFORE UPDATE ON records_market_evidence "
    "BEGIN SELECT RAISE(ABORT, 'market evidence is immutable'); END",
    "CREATE TRIGGER records_market_evidence_delete BEFORE DELETE ON records_market_evidence "
    "BEGIN SELECT RAISE(ABORT, 'market evidence is immutable'); END",
)


def apply(conn):
    metadata.create_all(conn)
    for sql in SQL:
        conn.exec_driver_sql(sql)


MIGRATION = Migration(
    "records", 2, "automatic_processed_market", apply, checksum=schema_checksum(metadata, SQL)
)
