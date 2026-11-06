"""Accounting-owned versioned schema. All writes go through the foundation writer."""

from sqlalchemy import (
    CheckConstraint,
    Column,
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

books = Table(
    "accounting_books",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("schema_revision", Integer, nullable=False),
    Column("data_revision", Integer, nullable=False),
    Column("next_logical_row", Integer, nullable=False),
    Column("columns_json", Text, nullable=False),
    Column("semantics_json", Text, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
schemas = Table(
    "accounting_schema_revisions",
    metadata,
    Column("book_id", String, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("columns_json", Text, nullable=False),
    Column("semantics_json", Text, nullable=False),
    Column("created_by", String, nullable=False),
    Column("created_at", String, nullable=False),
)
profiles = Table(
    "accounting_mapping_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("book_id", String, nullable=False),
    Column("name", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("schema_revision", Integer, nullable=False),
    Column("mapping_json", Text, nullable=False),
    Column("profile_json", Text, nullable=False),
    Column("created_by", String, nullable=False),
)
batches = Table(
    "accounting_batches",
    metadata,
    Column("id", String, primary_key=True),
    Column("book_id", String, nullable=False, index=True),
    Column("file_id", String, nullable=False),
    Column("file_hash", String, nullable=False, index=True),
    Column("actor_id", String, nullable=False),
    Column("actor_json", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("mapping_revision", Integer, nullable=False),
    Column("decision_revision", Integer, nullable=False),
    Column("duplicate_default", String),
    Column("schema_revision", Integer, nullable=False),
    Column("validation_token", String),
    Column("validated_revision", Integer),
    Column("profile_json", Text, nullable=False),
    Column("mapping_json", Text, nullable=False),
    Column("source_manifest_json", Text, nullable=False),
    Column("counts_json", Text, nullable=False),
    Column("job_id", String),
    Column("active_task_id", String),
    Column("manifest_id", String),
    Column("attempt_id", String),
    Column("error_code", String),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
stage = Table(
    "accounting_staged_rows",
    metadata,
    Column("batch_id", String, primary_key=True),
    Column("row_id", String, primary_key=True),
    Column("source_sheet", String, nullable=False),
    Column("sheet_name", String, nullable=False),
    Column("source_row", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("raw_json", Text, nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("formulas_json", Text, nullable=False),
    Column("edited_json", Text, nullable=False),
    Column("typed_json", Text, nullable=False),
    Column("issues_json", Text, nullable=False),
    Column("valid", Integer, nullable=False),
    Column("fingerprint", String),
    Column("candidate_key", String),
    Column("business_key", String),
    Column("duplicate_count", Integer, nullable=False),
    Column("decision", String),
    Column("target_id", String),
    Column("validation_revision", Integer),
    UniqueConstraint("batch_id", "source_sheet", "source_row"),
)
Index("accounting_stage_order", stage.c.batch_id, stage.c.source_row, stage.c.row_id)
Index("accounting_stage_fingerprint", stage.c.batch_id, stage.c.fingerprint)
Index("accounting_stage_candidate", stage.c.batch_id, stage.c.candidate_key)
Index("accounting_stage_duplicates", stage.c.batch_id, stage.c.duplicate_count)
Index(
    "accounting_stage_selection",
    stage.c.batch_id,
    stage.c.valid,
    stage.c.target_id,
    stage.c.decision,
)
patches = Table(
    "accounting_cell_patches",
    metadata,
    Column("id", String, primary_key=True),
    Column("batch_id", String, nullable=False),
    Column("row_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("values_json", Text, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("created_at", String, nullable=False),
)
issues = Table(
    "accounting_validation_issues",
    metadata,
    Column("id", String, primary_key=True),
    Column("batch_id", String, nullable=False),
    Column("row_id", String, nullable=False),
    Column("column_id", String, nullable=False),
    Column("validation_revision", Integer, nullable=False),
    Column("resolved", Integer, nullable=False),
    Column("issue_json", Text, nullable=False),
)
Index("accounting_issue_page", issues.c.batch_id, issues.c.resolved, issues.c.row_id)
entries = Table(
    "accounting_entries",
    metadata,
    Column("id", String, primary_key=True),
    Column("book_id", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("logical_row", Integer, nullable=False),
    Column("schema_revision", Integer, nullable=False),
    Column("values_json", Text, nullable=False),
    Column("formulas_json", Text, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("candidate_key", String),
    Column("business_key", String),
    Column("import_attempt_id", String),
    Column("batch_id", String),
    Column("source_row_id", String),
    Column("created_by", String, nullable=False),
    Column("updated_by", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("deleted_at", String),
    UniqueConstraint("book_id", "logical_row"),
    UniqueConstraint("batch_id", "source_row_id"),
    CheckConstraint("version >= 1"),
)
Index("accounting_entry_book", entries.c.book_id, entries.c.logical_row, entries.c.id)
Index("accounting_entry_fp", entries.c.book_id, entries.c.fingerprint)
Index("accounting_entry_candidate", entries.c.book_id, entries.c.candidate_key)
Index("accounting_entry_business", entries.c.book_id, entries.c.business_key)
Index("accounting_entry_attempt", entries.c.import_attempt_id)
cells = Table(
    "accounting_cells",
    metadata,
    Column("row_id", String, primary_key=True),
    Column("column_id", String, primary_key=True),
    Column("book_id", String, nullable=False),
    Column("text_value", Text),
    Column("scaled_value", Integer),
)
Index("accounting_cells_text", cells.c.book_id, cells.c.column_id, cells.c.text_value)
Index("accounting_cells_number", cells.c.book_id, cells.c.column_id, cells.c.scaled_value)
exports = Table(
    "accounting_exports",
    metadata,
    Column("id", String, primary_key=True),
    Column("book_id", String, nullable=False),
    Column("actor_json", Text, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("format", String, nullable=False),
    Column("data_revision", Integer, nullable=False),
    Column("schema_revision", Integer, nullable=False),
    Column("file_id", String),
    Column("job_id", String),
    Column("created_at", String, nullable=False),
)
tasks = Table(
    "accounting_task_outbox",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("actor_json", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("job_id", String),
    Column("dispatch_error", String),
    Column("created_at", String, nullable=False),
)

MIGRATIONS = (
    Migration(
        "accounting",
        1,
        "independent_books_staging_lineage",
        metadata.create_all,
        checksum=schema_checksum(metadata),
    ),
)
