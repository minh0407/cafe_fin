"""Upgrade an actual v1 SQLite root without rerunning/changing its migration."""

from contextlib import closing
from dataclasses import replace
from uuid import uuid4

import pytest
from cafe_fin.contracts.migrations.v001 import MIGRATIONS as V1
from cafe_fin.contracts.migrations.v002 import OUTPUT_STORAGE
from cafe_fin.contracts.module import module_manifest
from cafe_fin.contracts.schemas import TEMPLATE_IDS, ContractData
from cafe_fin.contracts.service import ContractService, IndependentDocumentRenderer
from cafe_fin.core.db import SCHEMA
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import FILES
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError


def test_v1_upgrade_preserves_interrupted_file_and_historical_checksum(tmp_path, monkeypatch):
    root = tmp_path / "Contracts v1 chuyển v2"
    password = "synthetic-migration-password"
    legacy = replace(module_manifest(), migrations=V1)
    with closing(Runtime(root, initialize=True, modules=ModuleRegistry((legacy,)))) as runtime:
        actor = runtime.auth.authenticate(
            runtime.auth.setup("migrationadmin", password)["access_token"]
        )
        service = ContractService(runtime)
        data = ContractData.model_validate(
            {
                "kind": "purchase",
                "number": "MIGRATION-001",
                "occurred_on": "2026-11-06",
                "template_id": TEMPLATE_IDS["purchase"],
                "company": {"type": "company", "name": "Đơn vị tổng hợp"},
                "counterparty": {"type": "person", "name": "Đối tác tổng hợp"},
                "lines": [{"description": "Cà phê", "quantity_kg": "1", "unit_price": "10"}],
            }
        )
        draft = service.save(actor, "migration-create", data)
        # Model the v1 namespace behavior without creating any v2 table/owner row.
        service._output_storage_owner = lambda actor, *args: actor.id
        original_run = runtime.writer.run
        interrupted = False

        def fail_finish_once(effect, *args, **kwargs):
            nonlocal interrupted
            if effect.__name__ == "finish" and not interrupted:
                interrupted = True
                raise OSError("Synthetic v1 crash gap after FileStore.put")
            return original_run(effect, *args, **kwargs)

        runtime.writer.run = fail_finish_once
        partial = service.export(actor, "migration-export", draft["id"], 1, ["docx"])
        assert partial["files"]["docx"]["status"] == "failed"
        with runtime.reader() as conn:
            assert OUTPUT_STORAGE.name not in inspect(conn).get_table_names()
            old_migration = dict(
                conn.execute(
                    select(SCHEMA).where(SCHEMA.c.namespace == "contracts", SCHEMA.c.version == 1)
                )
                .mappings()
                .one()
            )
            original_file = dict(conn.execute(select(FILES)).mappings().one())
        assert (
            old_migration["checksum"]
            == "8bd034cc4b168aed91411c3e4fd8e280dff72f872455adb1e8b8c8ae9d0fa3d5"
        )
        with runtime.files.read(original_file["id"]) as source:
            original_bytes = source.read()

    with closing(Runtime(root, modules=ModuleRegistry((module_manifest(),)))) as runtime:
        actor = runtime.auth.authenticate(
            runtime.auth.login("migrationadmin", password)["access_token"]
        )

        def forbid_rerender(*args, **kwargs):
            raise AssertionError("Upgrade must use v1 staged bytes and the existing file receipt")

        monkeypatch.setattr(IndependentDocumentRenderer, "docx", forbid_rerender)
        recovered = ContractService(runtime).add_formats(
            actor, "migration-recover", draft["id"], partial["id"], ["docx"]
        )
        assert recovered["files"]["docx"]["status"] == "succeeded"
        assert recovered["files"]["docx"]["file_id"] == original_file["id"]
        assert recovered["snapshot"] == partial["snapshot"]
        with runtime.files.read(original_file["id"]) as source:
            assert source.read() == original_bytes
        with runtime.reader() as conn:
            versions = [
                dict(row)
                for row in conn.execute(
                    select(SCHEMA)
                    .where(SCHEMA.c.namespace == "contracts")
                    .order_by(SCHEMA.c.version)
                ).mappings()
            ]
            assert [row["version"] for row in versions] == [1, 2]
            assert versions[0] == old_migration
            assert len(conn.execute(select(FILES)).all()) == 1
            assert conn.execute(select(OUTPUT_STORAGE.c.owner_actor)).scalar_one() == actor.id
        # The appended table cannot reserve a receipt for a nonexistent output.
        with pytest.raises(IntegrityError):
            runtime.writer.run(
                lambda conn: conn.execute(
                    OUTPUT_STORAGE.insert().values(
                        version_id=str(uuid4()),
                        format="docx",
                        owner_actor=actor.id,
                        created_at="2026-11-06T00:00:00Z",
                    )
                )
            )
