"""Initial module-owned schema. Never mutate after integration."""

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

from cafe_fin.core.modules import Migration, schema_checksum

metadata = MetaData()
DRAFTS = Table(
    "contracts_drafts",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("number", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("occurred_on", String, nullable=False),
    Column("party_name", String, nullable=False),
    Column("data_json", String, nullable=False),
    Column("totals_json", String, nullable=False),
    Column("quantity_milli", Integer, nullable=False),
    Column("subtotal_cents", Integer, nullable=False),
    Column("net_cents", Integer),
    Column("tax_cents", Integer),
    Column("total_cents", Integer),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("created_by", String, nullable=False),
    Column("updated_by", String, nullable=False),
    Column("deleted_at", String),
)
Index("contracts_drafts_date", DRAFTS.c.occurred_on, DRAFTS.c.id)
LINES = Table(
    "contracts_lines",
    metadata,
    Column("contract_id", String, ForeignKey("contracts_drafts.id"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("quantity_milli", Integer, nullable=False),
    Column("unit_price_cents", Integer, nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("gross_milli", Integer),
    Column("tare_milli", Integer),
    Column("net_milli", Integer),
    Column("source_json", String),
)
TEMPLATES = Table(
    "contracts_templates",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("kind", String, nullable=False),
    Column("payload_json", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("created_by", String, nullable=False),
)
VERSIONS = Table(
    "contracts_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("contract_id", String, ForeignKey("contracts_drafts.id"), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("contract_version", Integer, nullable=False),
    Column("snapshot_json", String, nullable=False),
    Column("snapshot_sha256", String, nullable=False),
    Column("template_id", String, nullable=False),
    Column("template_version", Integer, nullable=False),
    Column("template_sha256", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("created_by", String, nullable=False),
    UniqueConstraint("contract_id", "sequence"),
)
OUTPUTS = Table(
    "contracts_outputs",
    metadata,
    Column("version_id", String, ForeignKey("contracts_versions.id"), primary_key=True),
    Column("format", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("file_id", String),
    Column("sha256", String),
    Column("size", Integer),
    # Durable transient bytes bridge the two independent core/domain transactions.
    # Retried FileStore.put always receives the exact same bytes after a crash.
    Column("rendered_bytes", LargeBinary),
    Column("error_code", String),
    Column("error_message", String),
    Column("updated_at", String, nullable=False),
)
ATTACHMENTS = Table(
    "contracts_attachments",
    metadata,
    Column("id", String, primary_key=True),
    Column("contract_id", String, ForeignKey("contracts_drafts.id"), nullable=False),
    Column("version_id", String, ForeignKey("contracts_versions.id")),
    Column("file_id", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("original_name", String, nullable=False),
    Column("note", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("created_by", String, nullable=False),
)

MIGRATIONS = (
    Migration(
        "contracts",
        1,
        "drafts_templates_snapshots_outputs_attachments",
        metadata.create_all,
        checksum=schema_checksum(metadata),
    ),
)
