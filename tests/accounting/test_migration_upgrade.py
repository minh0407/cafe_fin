"""Append module schema to a real foundation root without resetting any core data."""

import io
from dataclasses import replace

import pytest
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.schema import books, entries
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.db import AUDIT, SCHEMA
from cafe_fin.core.errors import CoreError
from cafe_fin.core.example import NOTES
from cafe_fin.core.example import module_manifest as example_manifest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import func, insert, select


def registry(accounting=True):
    return ModuleRegistry(
        (example_manifest(), module_manifest()) if accounting else (example_manifest(),)
    )


def test_additive_upgrade_preserves_core_and_old_application_refuses_newer_schema(tmp_path):
    root = tmp_path / "upgrade-synthetic"
    with_runtime = Runtime(root, initialize=True, modules=registry(False))
    try:
        with_runtime.writer.run(
            lambda conn: conn.execute(
                insert(NOTES).values(
                    id="existing-foundation-note",
                    text="Dữ liệu tổng hợp giữ nguyên",
                    version=7,
                    created_at="2026-01-01T00:00:00+00:00",
                    updated_at="2026-01-01T00:00:00+00:00",
                )
            )
        )
    finally:
        with_runtime.close()
    upgraded = Runtime(root, modules=registry())
    try:
        with upgraded.reader() as conn:
            assert conn.execute(select(func.count()).select_from(books)).scalar_one() == 0
            assert conn.execute(select(NOTES.c.version)).scalar_one() == 7
            assert conn.execute(select(NOTES.c.text)).scalar_one() == "Dữ liệu tổng hợp giữ nguyên"
            assert (
                conn.execute(
                    select(func.max(SCHEMA.c.version)).where(SCHEMA.c.namespace == "accounting")
                ).scalar_one()
                == 2
            )
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
    finally:
        upgraded.close()
    with pytest.raises(CoreError, match="SCHEMA_NEWER_THAN_APP"):
        Runtime(root, modules=registry(False))
    restored_app = Runtime(root, modules=registry())
    try:
        with restored_app.reader() as conn:
            assert conn.execute(select(NOTES.c.version)).scalar_one() == 7
    finally:
        restored_app.close()


def test_changed_applied_accounting_checksum_refused_without_mutating_root(tmp_path):
    root = tmp_path / "checksum-synthetic"
    runtime = Runtime(root, initialize=True, modules=registry())
    runtime.close()
    module = module_manifest()
    changed = replace(
        module,
        migrations=(replace(module.migrations[0], checksum="0" * 64),) + module.migrations[1:],
    )
    with pytest.raises(CoreError, match="MIGRATION_CHANGED"):
        Runtime(root, modules=ModuleRegistry((example_manifest(), changed)))
    runtime = Runtime(root, modules=registry())
    runtime.close()


def test_accounting_migration_one_to_two_preserves_rows_files_audit_and_checksum(tmp_path):
    root = tmp_path / "accounting-v1-to-v2"
    module = module_manifest()
    legacy = replace(module, migrations=module.migrations[:1])
    old_registry = ModuleRegistry((example_manifest(), legacy))
    runtime = Runtime(root, initialize=True, modules=old_registry)
    try:
        session = runtime.auth.setup("migration-admin", "synthetic-migration-password")
        actor = runtime.auth.authenticate(session["access_token"])
        service = AccountingService(runtime)
        created = service.create_book(
            actor,
            "Synthetic migration book",
            [{"id": "code", "name": "Code", "kind": "text", "required": True}],
            {"duplicate_columns": ["code"]},
            "migration-book",
        )
        row = service.create_row(actor, created["id"], {"code": "000007"}, "migration-row")
        stored = runtime.files.put(
            io.BytesIO(b"synthetic immutable original"),
            category="imports",
            original_name="synthetic-migration.csv",
            actor=actor.id,
            request_key="migration-file",
            authorize=service.authorize(actor),
        )
        with runtime.reader() as conn:
            before_row = dict(
                conn.execute(select(entries).where(entries.c.id == row["id"])).mappings().one()
            )
            before_audit = conn.execute(select(func.count()).select_from(AUDIT)).scalar_one()
            before_checksum = conn.execute(
                select(SCHEMA.c.checksum).where(
                    SCHEMA.c.namespace == "accounting", SCHEMA.c.version == 1
                )
            ).scalar_one()
            assert conn.execute(
                select(SCHEMA.c.version).where(SCHEMA.c.namespace == "accounting")
            ).scalars().all() == [1]
            assert not conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='index' AND name IN ('accounting_stage_business_fp','accounting_entry_business_fp')"
            ).all()
    finally:
        runtime.close()
    upgraded = Runtime(root, modules=registry())
    try:
        with upgraded.reader() as conn:
            assert conn.execute(
                select(SCHEMA.c.version)
                .where(SCHEMA.c.namespace == "accounting")
                .order_by(SCHEMA.c.version)
            ).scalars().all() == [1, 2]
            assert (
                conn.execute(
                    select(SCHEMA.c.checksum).where(
                        SCHEMA.c.namespace == "accounting", SCHEMA.c.version == 1
                    )
                ).scalar_one()
                == before_checksum
            )
            assert (
                dict(
                    conn.execute(select(entries).where(entries.c.id == row["id"])).mappings().one()
                )
                == before_row
            )
            assert (
                conn.execute(select(func.count()).select_from(AUDIT)).scalar_one() == before_audit
            )
            for name, columns in (
                ("accounting_stage_business_fp", ["batch_id", "business_key", "fingerprint"]),
                ("accounting_entry_business_fp", ["book_id", "business_key", "fingerprint"]),
            ):
                assert [
                    record[2]
                    for record in conn.exec_driver_sql(f"PRAGMA index_info('{name}')").all()
                ] == columns
                table = "accounting_staged_rows" if "stage" in name else "accounting_entries"
                index = next(
                    record
                    for record in conn.exec_driver_sql(f"PRAGMA index_list('{table}')").all()
                    if record[1] == name
                )
                assert index[2] == 0  # Supporting index, never an invented business UNIQUE.
            assert conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
        with upgraded.files.read(stored.id) as source:
            assert source.read() == b"synthetic immutable original"
        assert upgraded.files.get(stored.id).sha256 == stored.sha256
        upgraded.auth.login("migration-admin", "synthetic-migration-password")
    finally:
        upgraded.close()
    with pytest.raises(CoreError, match="SCHEMA_NEWER_THAN_APP"):
        Runtime(root, modules=old_registry)
    reopened = Runtime(root, modules=registry())
    reopened.close()
