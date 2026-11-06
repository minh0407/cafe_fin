"""Activation markers, pre-start public hooks and conservative interrupted recovery."""

import json
import shutil
from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from cafe_fin.core.activation import (
    ACTIVATION_COMPLETED,
    ACTIVATION_INTENT,
    ACTIVATION_MARKER,
    OPERATION_MARKER,
    ActivationContext,
    receipt,
)
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JOBS
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.storage import atomic_json
from sqlalchemy import select

from tests.core.test_maintenance_operations import make_env as make_env
from tests.core.test_maintenance_operations import prepare


def seed(runtime, actor):
    runtime.writer.run(
        lambda conn: conn.exec_driver_sql(
            "CREATE TABLE reporting_activation_probe(quarantined INTEGER NOT NULL, calls INTEGER NOT NULL)"
        )
    )
    runtime.writer.run(
        lambda conn: conn.exec_driver_sql("INSERT INTO reporting_activation_probe VALUES (0,0)")
    )
    job_id = runtime.jobs.submit(actor.id, "foundation.sample", {}, "running-before-copy")["job_id"]
    runtime.writer.run(
        lambda conn: conn.execute(
            JOBS.update().where(JOBS.c.id == job_id).values(state="RUNNING", phase="source-cutoff")
        )
    )
    return job_id


def probe(runtime):
    with runtime.reader() as conn:
        return conn.exec_driver_sql(
            "SELECT quarantined,calls FROM reporting_activation_probe"
        ).one()


def test_restore_public_hook_runs_before_recovery_and_threads_then_receipt_prevents_requarantine(
    make_env,
    tmp_path,
):
    observed = []
    job_id = None

    def restore_guard(runtime, principal, context):
        assert isinstance(context, ActivationContext) and context.kind == "restore"
        assert runtime.maintenance.status()["state"] == "ACTIVATING"
        assert runtime.runner.thread.ident is None and runtime.periodic.thread.ident is None
        with runtime.reader() as conn:
            assert (
                conn.execute(select(JOBS.c.state).where(JOBS.c.id == job_id)).scalar_one()
                == "RUNNING"
            )
            assert receipt(conn, ACTIVATION_INTENT, context.activation_id) is not None

        def quarantine(conn):
            runtime.auth.authorize(conn, principal, "core.manage")
            conn.exec_driver_sql(
                "UPDATE reporting_activation_probe SET quarantined=1,calls=calls+1"
            )

        runtime.writer.run(quarantine)
        observed.append(("guard", context.activation_id, principal.id))
        with pytest.raises(FrozenInstanceError):
            context.kind = "move"

    def startup(runtime):
        assert probe(runtime)[0] in (0, 1)
        with runtime.reader() as conn:
            assert (
                conn.execute(select(JOBS.c.state).where(JOBS.c.id == job_id)).scalar_one()
                == "RECOVERABLE"
            )
        observed.append(("startup",))

    manifest = ModuleManifest(
        "reporting", "/reporting", on_activate=restore_guard, on_startup=startup
    )
    foreign = make_env(modules=(manifest,))
    job_id = seed(foreign.runtime, foreign.actor)
    _, backup, _ = prepare(foreign, tmp_path)
    old = make_env(modules=(manifest,))
    operation_id, target, _ = prepare(old, tmp_path, "restore", backup=backup)
    target_env = make_env(modules=(manifest,), path=target, initialize=False)
    assert observed == [] and probe(target_env.runtime) == (0, 0)
    assert target_env.runtime.maintenance.status()["state"] == "DORMANT"
    target_env.ops.activate(
        operation_id, access_token=target_env.token, origin_generation=old.generation
    )
    assert observed[0] == ("guard", operation_id, target_env.actor.id)
    assert observed[1] == ("startup",) and probe(target_env.runtime) == (1, 1)
    with target_env.runtime.reader() as conn:
        assert receipt(conn, ACTIVATION_COMPLETED, operation_id) is not None
    target_env.ops.activate(
        operation_id, access_token=target_env.token, origin_generation=old.generation
    )
    assert len(observed) == 2
    # A later explicit Admin choice must survive ordinary restart without re-quarantine.
    target_env.runtime.writer.run(
        lambda conn: conn.exec_driver_sql("UPDATE reporting_activation_probe SET quarantined=0")
    )
    target_env.runtime.close()
    reopened = make_env(modules=(manifest,), path=target, initialize=False)
    assert reopened.runtime.maintenance.status()["state"] == "ACTIVE"
    reopened.runtime.start()
    assert probe(reopened.runtime) == (0, 1)
    assert observed == [("guard", operation_id, target_env.actor.id), ("startup",), ("startup",)]


@pytest.mark.parametrize("failure", ["hook", "completion"])
def test_interrupted_activation_is_held_and_new_dormant_runtime_requires_explicit_recovery(
    make_env,
    tmp_path,
    monkeypatch,
    failure,
):
    calls = []

    def hook(runtime, actor, context):
        calls.append(context.activation_id)
        runtime.writer.run(
            lambda conn: conn.exec_driver_sql(
                "UPDATE reporting_activation_probe SET quarantined=1,calls=calls+1"
            )
        )
        if failure == "hook":
            raise RuntimeError("synthetic-private-hook-error")

    manifest = ModuleManifest("sample", "/sample", on_activate=hook)
    source = make_env(modules=(manifest,))
    seed(source.runtime, source.actor)
    operation_id, target, _ = prepare(source, tmp_path, "move")
    candidate = make_env(modules=(manifest,), path=target, initialize=False)
    if failure == "completion":
        import cafe_fin.core.runtime as runtime_module

        def lost_completion(*args):
            raise CoreError("SYNTHETIC_COMPLETION_FAILURE", "synthetic completion gap")

        monkeypatch.setattr(runtime_module, "complete_activation", lost_completion)
    with pytest.raises(CoreError, match="MAINTENANCE_ACTIVATION_FAILED"):
        candidate.ops.activate(
            operation_id, access_token=candidate.token, origin_generation=source.generation
        )
    assert candidate.runtime.maintenance.status()["state"] == "FAILED_HELD"
    assert candidate.runtime.root._lock is not None and probe(candidate.runtime) == (1, 1)
    assert calls == [operation_id]
    assert (
        candidate.ops.authorize_close(
            operation_id, access_token=candidate.token, origin_generation=source.generation
        )["state"]
        == "CLOSE_AUTHORIZED"
    )
    candidate.runtime.close()
    reopened = make_env(modules=(manifest,), path=target, initialize=False)
    assert reopened.runtime.maintenance.status()["state"] == "DORMANT"
    assert (
        reopened.ops.status(
            operation_id, access_token=reopened.token, origin_generation=source.generation
        )["state"]
        == "REPLAY_REQUIRED"
    )
    with pytest.raises(CoreError, match="ACTIVATION_REPLAY_REQUIRED"):
        reopened.ops.activate(
            operation_id, access_token=reopened.token, origin_generation=source.generation
        )
    assert calls == [operation_id] and probe(reopened.runtime) == (1, 1)
    assert reopened.runtime.runner.thread.ident is None


def test_same_lineage_marker_cannot_authorize_another_physical_location(make_env, tmp_path):
    env = make_env()
    operation_id, target, _ = prepare(env, tmp_path, "move")
    other = tmp_path / "Copied to another physical location"
    shutil.copytree(target, other)
    with pytest.raises(CoreError, match="ACTIVATION_BINDING_INVALID"):
        make_env(path=other, initialize=False)
    candidate = make_env(path=target, initialize=False)
    with pytest.raises(CoreError, match="ACTIVATION_BINDING_INVALID"):
        candidate.ops.activate(
            str(uuid4()), access_token=candidate.token, origin_generation=env.generation
        )
    assert candidate.runtime.runner.thread.ident is None


def test_completed_activation_receipt_must_match_marker_before_normal_boot(make_env, tmp_path):
    env = make_env()
    operation_id, target, _ = prepare(env, tmp_path, "move")
    candidate = make_env(path=target, initialize=False)
    candidate.ops.activate(
        operation_id, access_token=candidate.token, origin_generation=env.generation
    )
    candidate.runtime.close()
    path = target / ACTIVATION_MARKER
    marker = json.loads(path.read_text(encoding="utf-8"))
    marker["kind"] = "restore"
    atomic_json(path, marker)
    provenance_path = target / OPERATION_MARKER
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["binding"]["kind"] = "restore"
    provenance["binding"]["backup_manifest_sha256"] = marker["manifest_sha256"]
    atomic_json(provenance_path, provenance)
    with pytest.raises(CoreError, match="ACTIVATION_BINDING_INVALID"):
        make_env(path=target, initialize=False)


def test_public_activation_hook_registration_requires_callable():
    with pytest.raises(CoreError, match="INVALID_MODULE_HOOK"):
        ModuleRegistry((ModuleManifest("sample", "/sample", on_activate="invalid"),))


def test_candidate_original_hash_change_cannot_start_any_worker(make_env, tmp_path):
    import io

    env = make_env()
    original = env.runtime.files.put(
        io.BytesIO(b"original bytes"),
        category="workbooks",
        original_name="source.xlsm",
        actor=env.actor.id,
        request_key="original",
    )
    operation_id, target, _ = prepare(env, tmp_path, "move")
    (target / original.relative_key).write_bytes(b"tampered bytes")
    candidate = make_env(path=target, initialize=False)
    with pytest.raises(CoreError, match="BACKUP_HASH_MISMATCH"):
        candidate.ops.activate(
            operation_id, access_token=candidate.token, origin_generation=env.generation
        )
    assert candidate.runtime.runner.thread.ident is None
    assert candidate.runtime.periodic.thread.ident is None
    assert env.runtime.maintenance.status()["state"] == "QUIESCED"
