"""Private maintenance controller with actual SQLite snapshots and immutable files."""

import io
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.accounting.module import module_manifest as accounting_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.activation import (
    ACTIVATION_MARKER,
    INTENT,
    OPERATION_MARKER,
    PREPARED,
    ActivationContext,
    activation_context,
    receipt,
)
from cafe_fin.core.backup import BackupService
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_operations import MaintenanceOperations
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService, sha256_file
from sqlalchemy import select

PASSWORD = "synthetic-maintenance-operations-password"


@pytest.fixture
def make_env(tmp_path):
    runtimes = []

    def make(*, modules=(), path=None, initialize=True):
        runtime = Runtime(
            path or tmp_path / ("Dữ liệu nguồn " + str(uuid4())),
            initialize=initialize,
            modules=ModuleRegistry(tuple(modules)),
        )
        runtimes.append(runtime)
        if initialize:
            session = runtime.auth.setup("operations-admin", PASSWORD)
            actor = runtime.auth.authenticate(session["access_token"])
            runtime.auth.create_user(
                actor,
                username="other-admin",
                password=PASSWORD,
                role="admin",
                request_key="second-admin",
            )
            runtime.auth.create_user(
                actor,
                username="operations-operator",
                password=PASSWORD,
                role="operator",
                request_key="operator",
            )
        else:
            session = runtime.auth.login("operations-admin", PASSWORD)
            actor = runtime.auth.authenticate(session["access_token"])
        generation = str(uuid4())
        return SimpleNamespace(
            runtime=runtime,
            token=session["access_token"],
            actor=actor,
            generation=generation,
            ops=MaintenanceOperations(runtime, generation=generation),
        )

    yield make
    for runtime in reversed(runtimes):
        runtime.close()


def destination(tmp_path, operation_id, kind):
    parent = tmp_path / "Nơi lưu riêng có dấu"
    parent.mkdir(exist_ok=True)
    return parent / (("CafeFinBackup-" if kind == "backup" else "CafeFinData-") + operation_id)


def prepare(env, tmp_path, kind="backup", *, operation_id=None, backup=None):
    operation_id = operation_id or str(uuid4())
    target = destination(tmp_path, operation_id, kind)
    if kind != "backup":
        env.runtime.quiesce(operation_id, access_token=env.token)
    result = env.ops.prepare(
        operation_id,
        kind,
        access_token=env.token,
        origin_generation=env.generation,
        destination=target,
        backup_source=backup,
    )
    return operation_id, target, result


def original(env):
    return env.runtime.files.put(
        io.BytesIO(b"synthetic immutable original\x00\xff"),
        category="workbooks",
        original_name="Nguồn tổng hợp.xlsm",
        actor=env.actor.id,
        request_key=str(uuid4()),
    )


def test_online_backup_replays_across_admins_and_copies_intent_original_and_hashes(
    make_env, tmp_path
):
    env = make_env()
    source = original(env)
    operation_id, target, result = prepare(env, tmp_path)
    assert result["state"] == "PREPARED" and env.runtime.maintenance.status()["state"] == "ACTIVE"
    assert result["manifest_sha256"] == sha256_file(target / "backup-manifest.json")
    with (target / source.relative_key).open("rb") as stream:
        assert stream.read() == b"synthetic immutable original\x00\xff"
    assert BackupService.verify(target)["referenced_file_count"] == 1
    assert not (target / ACTIVATION_MARKER).exists()
    other = env.runtime.auth.login("other-admin", PASSWORD)["access_token"]
    replay = env.ops.prepare(
        operation_id,
        "backup",
        access_token=other,
        origin_generation=env.generation,
        destination=target,
    )
    assert replay == result
    assert (
        env.ops.status(operation_id, access_token=other, origin_generation=env.generation) == result
    )
    assert (
        env.ops.authorize_close(operation_id, access_token=other, origin_generation=env.generation)[
            "state"
        ]
        == "CLOSE_AUTHORIZED"
    )
    with env.runtime.reader() as conn:
        assert receipt(conn, INTENT, operation_id)["intent"]["destination"] == str(target.resolve())
        assert len(conn.execute(select(AUDIT).where(AUDIT.c.entity_id == operation_id)).all()) == 2
        persisted = " ".join(conn.execute(select(REQUESTS.c.result_json)).scalars())
        assert env.token not in persisted and other not in persisted
    with pytest.raises(CoreError, match="BACKUP_ARCHIVE_NOT_ACTIVE"):
        Runtime(target, modules=env.runtime.modules)


def test_copy_does_not_stop_live_writer_and_unpublished_retry_can_take_fresh_snapshot(
    make_env,
    tmp_path,
    monkeypatch,
):
    env = make_env()
    original(env)
    import cafe_fin.core.backup as backup_module

    copyfile = backup_module.shutil.copyfile
    copying, release = threading.Event(), threading.Event()

    # Filestore paths use generated suffixes, so block the immutable workbook category.
    def slow(source, target):
        if "workbooks" in Path(source).parts:
            copying.set()
            assert release.wait(5)
        return copyfile(source, target)

    monkeypatch.setattr(backup_module.shutil, "copyfile", slow)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(prepare, env, tmp_path)
        try:
            assert copying.wait(3)
            assert env.runtime.maintenance.status()["state"] == "ACTIVE"
            extra = env.runtime.files.put(
                io.BytesIO(b"later original"),
                category="reports",
                original_name="later.txt",
                actor=env.actor.id,
                request_key="during-copy",
            )
            assert env.runtime.files.get(extra.id).size == 14
        finally:
            release.set()
        _, target, _ = pending.result(timeout=3)
    assert BackupService.verify(target)["referenced_file_count"] == 1


def test_copy_failure_retains_partial_and_retry_keeps_operation_and_fixed_destination(
    make_env,
    tmp_path,
    monkeypatch,
):
    env = make_env()
    original(env)
    copy = env.runtime.database.backup_to
    operation_id = str(uuid4())
    target = destination(tmp_path, operation_id, "backup")

    def fail(path):
        raise CoreError("SYNTHETIC_COPY_FAILURE", "synthetic copy failure")

    monkeypatch.setattr(env.runtime.database, "backup_to", fail)
    with pytest.raises(CoreError, match="SYNTHETIC_COPY_FAILURE"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
        )
    partials = list(target.parent.glob(target.name + ".partial-*"))
    assert len(partials) == 1 and not target.exists()
    assert (
        env.ops.status(operation_id, access_token=env.token, origin_generation=env.generation)[
            "state"
        ]
        == "REPLAY_REQUIRED"
    )
    monkeypatch.setattr(env.runtime.database, "backup_to", copy)
    result = env.ops.prepare(
        operation_id,
        "backup",
        access_token=env.token,
        origin_generation=env.generation,
        destination=target,
    )
    assert result["state"] == "PREPARED" and partials[0].exists()


def test_crash_after_copy_before_receipt_reuses_only_operation_bound_artifact(
    make_env, tmp_path, monkeypatch
):
    env = make_env()
    original(env)
    operation_id = str(uuid4())
    target = destination(tmp_path, operation_id, "backup")
    prepared = env.ops._prepared

    def lost_ack(*args):
        raise CoreError("SYNTHETIC_LOST_ACK", "synthetic ACK gap")

    monkeypatch.setattr(env.ops, "_prepared", lost_ack)
    with pytest.raises(CoreError, match="SYNTHETIC_LOST_ACK"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
        )
    first_hash = sha256_file(target / "backup-manifest.json")
    assert (target / OPERATION_MARKER).is_file()
    with env.runtime.reader() as conn:
        assert receipt(conn, PREPARED, operation_id) is None
    monkeypatch.setattr(env.ops, "_prepared", prepared)
    recovered = MaintenanceOperations(env.runtime, generation=str(uuid4()))
    result = recovered.prepare(
        operation_id,
        "backup",
        access_token=env.token,
        origin_generation=env.generation,
        destination=target,
    )
    assert result["manifest_sha256"] == first_hash
    assert len(list(target.parent.glob("CafeFinBackup-*"))) == 1


def test_changed_destination_generation_original_or_unknown_existing_target_conflicts(
    make_env, tmp_path
):
    env = make_env()
    operation_id, target, _ = prepare(env, tmp_path)
    elsewhere = tmp_path / "another parent"
    elsewhere.mkdir()
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=elsewhere / target.name,
        )
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        env.ops.status(operation_id, access_token=env.token, origin_generation=str(uuid4()))
    unknown_id = str(uuid4())
    unknown = destination(tmp_path, unknown_id, "backup")
    unknown.mkdir()
    (unknown / "keep.txt").write_text("untouched")
    with pytest.raises(CoreError, match="MAINTENANCE_DESTINATION_EXISTS"):
        env.ops.prepare(
            unknown_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=unknown,
        )
    assert (unknown / "keep.txt").read_text() == "untouched"
    (target / "backup-manifest.json").write_text("{}")
    assert (
        env.ops.status(operation_id, access_token=env.token, origin_generation=env.generation)[
            "state"
        ]
        == "FAILED_HELD"
    )


def test_move_copies_real_pending_accounting_job_and_forces_both_source_and_target_dormant(
    make_env,
    tmp_path,
):
    env = make_env(modules=(accounting_manifest(),))
    service = AccountingService(env.runtime)
    book = service.create_book(
        env.actor,
        "Sổ đang chờ",
        [{"id": "code", "name": "Mã", "kind": "text", "required": True}],
        {},
        str(uuid4()),
    )
    file = env.runtime.files.put(
        io.BytesIO(b"Code\n001\n"),
        category="workbooks",
        original_name="pending.csv",
        actor=env.actor.id,
        request_key="pending-source",
    )
    batch = service.create_batch(env.actor, book["id"], file.id, {}, str(uuid4()))
    job = service.get_batch(env.actor, batch["id"])["job"]
    assert job["state"] == "WAITING"
    operation_id, target, result = prepare(env, tmp_path, "move")
    assert env.runtime.maintenance.status()["state"] == "QUIESCED"
    assert env.runtime.root._lock is not None and not env.runtime.writer._closed
    context = activation_context(DataRootService(target))
    assert isinstance(context, ActivationContext) and context.activation_id == operation_id
    assert result["source_root_id"] == result["candidate_root_id"]
    assert result["source_fingerprint"] != result["candidate_fingerprint"]
    candidate = make_env(modules=(accounting_manifest(),), path=target, initialize=False)
    assert candidate.runtime.maintenance.status()["state"] == "DORMANT"
    candidate.runtime.start()
    assert candidate.runtime.runner.thread.ident is None
    assert (
        AccountingService(candidate.runtime).get_batch(candidate.actor, batch["id"])["job"] == job
    )
    with candidate.runtime.files.read(file.id) as stream:
        assert stream.read() == b"Code\n001\n"
    old_path = env.runtime.root.path
    env.runtime.close()
    reopened = make_env(modules=(accounting_manifest(),), path=old_path, initialize=False)
    assert reopened.runtime.maintenance.status()["state"] == "DORMANT"
    with pytest.raises(CoreError, match="MAINTENANCE_REPLAY_REQUIRED"):
        reopened.runtime.activate(operation_id, access_token=reopened.token)


def test_private_open_reports_operator_allowed_but_maintenance_admin_only_and_revocation_checked(
    make_env,
    tmp_path,
):
    env = make_env()
    operator = env.runtime.auth.login("operations-operator", PASSWORD)["access_token"]
    assert env.ops.authorize_open_reports(operator) == {
        "allowed": True,
        "root_id": env.ops._source()[2],
    }
    operation_id = str(uuid4())
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=operator,
            origin_generation=env.generation,
            destination=destination(tmp_path, operation_id, "backup"),
        )
    other = env.runtime.auth.authenticate(
        env.runtime.auth.login("other-admin", PASSWORD)["access_token"]
    )
    env.runtime.auth.update_user(
        other,
        env.actor.id,
        role="operator",
        active=True,
        expected_version=1,
        request_key="revoke-before-operation",
    )
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.ops.authorize_open_reports(env.token)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.ops.status(operation_id, access_token=env.token, origin_generation=env.generation)


def test_location_preflight_rejects_nested_synced_relative_and_junction_before_intent(
    make_env,
    tmp_path,
    monkeypatch,
):
    env = make_env()
    operation_id = str(uuid4())
    nested = env.runtime.root.path / ("CafeFinBackup-" + operation_id)
    with pytest.raises(CoreError, match="MAINTENANCE_LOCATION_INVALID"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=nested,
        )
    with pytest.raises(CoreError, match="MAINTENANCE_PATH_INVALID"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination="relative",
        )
    synced = tmp_path / "synthetic synced folder"
    synced.mkdir()
    monkeypatch.setenv("OneDrive", str(synced))
    with pytest.raises(CoreError, match="DATA_ROOT_SYNCED"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=synced / ("CafeFinBackup-" + operation_id),
        )
    if os.name == "nt":
        actual, junction = tmp_path / "actual", tmp_path / "junction"
        actual.mkdir()
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(actual)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0
        with pytest.raises(CoreError, match="DATA_ROOT_LINK"):
            env.ops.prepare(
                operation_id,
                "backup",
                access_token=env.token,
                origin_generation=env.generation,
                destination=junction / ("CafeFinBackup-" + operation_id),
            )
    with env.runtime.reader() as conn:
        assert receipt(conn, INTENT, operation_id) is None


def test_restore_pins_foreign_backup_source_and_guard_hook_is_mandatory(make_env, tmp_path):
    foreign = make_env()
    source_file = original(foreign)
    _, backup, _ = prepare(foreign, tmp_path)
    env = make_env(
        modules=(ModuleManifest("reporting", "/reporting", on_activate=lambda *args: None),)
    )
    operation_id, target, result = prepare(env, tmp_path, "restore", backup=backup)
    assert result["source_root_id"] != result["candidate_root_id"]
    candidate = make_env(path=target, initialize=False)
    assert candidate.runtime.maintenance.status()["state"] == "DORMANT"
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        candidate.ops.activate(
            operation_id, access_token=env.token, origin_generation=env.generation
        )
    with pytest.raises(CoreError, match="RESTORE_GUARD_UNAVAILABLE"):
        candidate.ops.activate(
            operation_id, access_token=candidate.token, origin_generation=env.generation
        )
    assert candidate.runtime.runner.thread.ident is None
    assert sha256_file(backup / source_file.relative_key) == source_file.sha256
    # A different valid backup cannot replace the source pinned by this operation.
    _, another, _ = prepare(foreign, tmp_path)
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        env.ops.prepare(
            operation_id,
            "restore",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
            backup_source=another,
        )


def test_revocation_after_copy_blocks_completion_then_current_other_admin_can_reconcile(
    make_env,
    tmp_path,
    monkeypatch,
):
    env = make_env()
    other_token = env.runtime.auth.login("other-admin", PASSWORD)["access_token"]
    other = env.runtime.auth.authenticate(other_token)
    create = env.runtime.backups.create
    operation_id = str(uuid4())
    target = destination(tmp_path, operation_id, "backup")

    def copy_then_revoke(*args, **kwargs):
        result = create(*args, **kwargs)
        env.runtime.auth.update_user(
            other,
            env.actor.id,
            role="operator",
            active=True,
            expected_version=1,
            request_key="revoked-during-copy",
        )
        return result

    monkeypatch.setattr(env.runtime.backups, "create", copy_then_revoke)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.ops.prepare(
            operation_id,
            "backup",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
        )
    published_hash = sha256_file(target / "backup-manifest.json")
    assert (
        env.ops.status(operation_id, access_token=other_token, origin_generation=env.generation)[
            "state"
        ]
        == "REPLAY_REQUIRED"
    )
    result = env.ops.prepare(
        operation_id,
        "backup",
        access_token=other_token,
        origin_generation=env.generation,
        destination=target,
    )
    assert result["manifest_sha256"] == published_hash


def test_completed_move_marker_is_rechecked_before_status_or_prepare_replay(make_env, tmp_path):
    env = make_env()
    operation_id, target, _ = prepare(env, tmp_path, "move")
    (target / ACTIVATION_MARKER).write_text("{}", encoding="utf-8")
    assert (
        env.ops.status(operation_id, access_token=env.token, origin_generation=env.generation)[
            "state"
        ]
        == "FAILED_HELD"
    )
    with pytest.raises(CoreError):
        env.ops.prepare(
            operation_id,
            "move",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
        )
    assert env.runtime.maintenance.status()["state"] == "QUIESCED"


def test_restore_without_owner_guard_is_rejected_before_intent_or_copy(make_env, tmp_path):
    foreign = make_env()
    _, backup, _ = prepare(foreign, tmp_path)
    env = make_env()
    operation_id = str(uuid4())
    target = destination(tmp_path, operation_id, "restore")
    env.runtime.quiesce(operation_id, access_token=env.token)
    with pytest.raises(CoreError, match="RESTORE_GUARD_UNAVAILABLE"):
        env.ops.prepare(
            operation_id,
            "restore",
            access_token=env.token,
            origin_generation=env.generation,
            destination=target,
            backup_source=backup,
        )
    assert not target.exists()
    with env.runtime.reader() as conn:
        assert receipt(conn, INTENT, operation_id) is None
