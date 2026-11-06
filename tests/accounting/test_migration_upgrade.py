"""Append module schema to a real foundation root without resetting any core data."""

from dataclasses import replace

import pytest
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.schema import books
from cafe_fin.core.db import SCHEMA
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
                    select(SCHEMA.c.version).where(SCHEMA.c.namespace == "accounting")
                ).scalar_one()
                == 1
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
    changed = replace(module, migrations=(replace(module.migrations[0], checksum="0" * 64),))
    with pytest.raises(CoreError, match="MIGRATION_CHANGED"):
        Runtime(root, modules=ModuleRegistry((example_manifest(), changed)))
    runtime = Runtime(root, modules=registry())
    runtime.close()
