"""Actual os._exit probes: uncommitted rollback, durable checkpoints and publication."""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.db import AUDIT, canonical_json
from cafe_fin.core.imports import claims, manifest_rows, receipts
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import func, select

ROWS = 1001
MODES = [
    "pending_before",
    "pending_precommit",
    "pending_after_commit",
    "published_before_ack",
    "parse_precommit",
    "parse_after_commit",
    "parse_failure",
    "validation_precommit",
    "validation_after_commit",
    "validation_failure",
]


def wait(service, actor, batch_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch = service.get_batch(actor, batch_id)
        state = batch.get("job", {}).get("state")
        if state == "COMPLETED" and batch["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "RECOVERABLE", "CANCELLED"}:
            assert state == "COMPLETED", batch.get("error_code")
            return batch
        time.sleep(0.01)
    pytest.fail("restarted process fixture timed out")


def confirm(service, actor, batch):
    service.confirm(
        actor,
        batch["id"],
        {
            "expected_version": batch["version"],
            "staging_revision": batch["revision"],
            "mapping_revision": batch["mapping_revision"],
            "decision_revision": batch["decision_revision"],
            "validation_token": batch["validation_token"],
            "mode": "valid_rows_only",
            "request_key": str(uuid4()),
        },
    )


@pytest.mark.parametrize("mode", MODES)
def test_process_death_recovery_preserves_counts_hash_receipts_and_lineage(tmp_path, mode):
    repository = Path(__file__).resolve().parents[2]
    config_path, metadata_path = tmp_path / "command.json", tmp_path / "safe-metadata.json"
    root = tmp_path / "synthetic-data-root"
    config_path.write_text(
        json.dumps({"root": str(root), "metadata": str(metadata_path), "mode": mode, "rows": ROWS}),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "backend")
    # The child prints no row values, source contents or application logs.
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("crash_worker.py")), str(config_path)],
        cwd=repository,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=False,
    )
    assert completed.returncode == 86, "synthetic child did not reach its selected crash point"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    runtime = Runtime(root, modules=ModuleRegistry((module_manifest(),)))
    try:
        session = runtime.auth.login("synthetic-crash-admin", "synthetic-crash-password")
        actor = runtime.auth.authenticate(session["access_token"])
        service = AccountingService(runtime)
        runtime.start()
        batch = service.get_batch(actor, metadata["batch_id"])
        assert batch["job"]["state"] == (
            "COMPLETED"
            if mode == "published_before_ack"
            else "FAILED"
            if mode.endswith("failure")
            else "RECOVERABLE"
        )
        with runtime.reader() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
            initial_entries = connection.execute(
                select(func.count()).select_from(s.entries)
            ).scalar_one()
            initial_stage = connection.execute(
                select(func.count()).select_from(s.stage)
            ).scalar_one()
            initial_receipts = connection.execute(
                select(func.count()).select_from(receipts)
            ).scalar_one()
            initial_normalized = connection.execute(
                select(func.count())
                .select_from(s.stage)
                .where(s.stage.c.validation_revision.is_not(None))
            ).scalar_one()
        expected_entries = (
            ROWS if mode == "published_before_ack" else 500 if mode == "pending_after_commit" else 0
        )
        assert initial_entries == expected_entries
        assert initial_receipts == (
            3 if mode == "published_before_ack" else 1 if mode == "pending_after_commit" else 0
        )
        if mode.startswith("parse_"):
            assert initial_stage == (0 if mode.endswith("precommit") else 500)
        else:
            assert initial_stage == ROWS
        if mode.startswith("validation_"):
            assert initial_normalized == (0 if mode.endswith("precommit") else 500)
        visible = service.list_rows(actor, metadata["book_id"])
        assert visible["total"] == (ROWS if mode == "published_before_ack" else 0)
        if mode != "published_before_ack":
            service.cancel_resume(actor, batch["id"], "resume")
            batch = wait(service, actor, batch["id"])
            if mode.startswith("parse_"):
                batch = service.mapping(
                    actor,
                    batch["id"],
                    batch["version"],
                    {"code": "A", "day": "B", "amount": "C"},
                    {},
                    str(uuid4()),
                )
                service.validate(actor, batch["id"], batch["version"], str(uuid4()))
                batch = wait(service, actor, batch["id"])
            if mode.startswith(("parse_", "validation_")):
                confirm(service, actor, batch)
                batch = wait(service, actor, batch["id"])
        else:
            # Crash after atomic finalization but before returning ACK must replay safely.
            service.confirm(actor, batch["id"], metadata["confirm_command"])
            batch = service.get_batch(actor, batch["id"])
        assert batch["state"] == "COMPLETED"
        assert batch["counts"]["published_rows"] == ROWS
        assert batch["counts"]["pending"] == 0
        with runtime.files.read(metadata["file_id"]) as source:
            assert hashlib.sha256(source.read()).hexdigest() == metadata["source_sha256"]
        with runtime.reader() as connection:
            data = connection.execute(select(s.entries.c.values_json)).scalars().all()
            decoded = sorted((json.loads(value) for value in data), key=lambda value: value["code"])
            expected = [
                {"code": f"{index:07d}", "day": "2026-02-01", "amount": "1.01"}
                for index in range(ROWS)
            ]
            assert (
                hashlib.sha256(canonical_json(decoded).encode()).digest()
                == hashlib.sha256(canonical_json(expected).encode()).digest()
            )
            assert len(data) == ROWS
            assert connection.execute(select(func.count()).select_from(claims)).scalar_one() == ROWS
            assert (
                connection.execute(
                    select(func.count(func.distinct(s.entries.c.source_row_id)))
                ).scalar_one()
                == ROWS
            )
            committed = (
                connection.execute(select(receipts).order_by(receipts.c.start)).mappings().all()
            )
            assert [(row.start, row.count) for row in committed] == [
                (0, 500),
                (500, 500),
                (1000, 1),
            ]
            for receipt in committed:
                row_hashes = connection.execute(
                    select(manifest_rows.c.row_hash)
                    .where(
                        manifest_rows.c.manifest_id == batch["manifest_id"],
                        manifest_rows.c.ordinal >= receipt.start,
                        manifest_rows.c.ordinal < receipt.start + receipt.count,
                    )
                    .order_by(manifest_rows.c.ordinal)
                ).scalars()
                assert hashlib.sha256("".join(row_hashes).encode()).hexdigest() == receipt.digest
            assert (
                connection.execute(
                    select(func.count())
                    .select_from(AUDIT)
                    .where(AUDIT.c.entity == "accounting_attempt", AUDIT.c.action == "publish")
                ).scalar_one()
                == 1
            )
        assert (
            service.summary(actor, metadata["book_id"], "2026-02-01", "2026-02-02")["totals"][
                "VND"
            ]["income"]
            == "1011.01"
        )
    finally:
        runtime.close()
