"""Real Windows disk aliases: shared identity without UNC/device/reparse escapes."""

import hashlib
import io
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from cafe_fin.core.activation import canonical_location, location_fingerprint
from cafe_fin.core.backup import BackupService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_operations import MaintenanceOperations
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService

from tests.core.test_maintenance_protocol import TOKEN, Child, login

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Actual Windows filesystem semantics")


def verbatim(path):
    return "\\\\?\\" + str(path.absolute())


def legacy_fingerprint(path):
    return hashlib.sha256(os.path.normcase(str(path.resolve())).encode("utf-8")).hexdigest()


def test_normal_and_verbatim_disk_have_same_existing_identity_fingerprint_and_lock(tmp_path):
    normal = tmp_path / "Dữ liệu Café có dấu"
    runtime = Runtime(normal, initialize=True, modules=ModuleRegistry(()))
    try:
        normal_marker = (normal / ".cafe-fin-root.json").read_bytes()
        assert DataRootService(verbatim(normal)).path == normal.absolute()
        assert canonical_location(normal) == canonical_location(verbatim(normal))
        assert (
            location_fingerprint(normal)
            == location_fingerprint(verbatim(normal))
            == legacy_fingerprint(normal)
        )
        assert (normal / ".cafe-fin-root.json").read_bytes() == normal_marker
        with pytest.raises(CoreError, match="DATA_ROOT_LOCKED"):
            DataRootService(verbatim(normal)).acquire_lock()
    finally:
        runtime.close()
    reopened = Runtime(verbatim(normal), modules=ModuleRegistry(()))
    try:
        assert reopened.root.path == normal.absolute()
        with reopened.reader() as conn:
            assert conn.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "path,code",
    [
        (r"\\server\share\root", "DATA_ROOT_REMOTE"),
        (r"\\?\UNC\server\share\root", "DATA_ROOT_REMOTE"),
        (r"\\?\unc\server\share\root", "DATA_ROOT_REMOTE"),
        (r"\\.\C:\root", "DATA_ROOT_PATH_INVALID"),
        (r"\\.\pipe\root", "DATA_ROOT_PATH_INVALID"),
        (r"\??\C:\root", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\GLOBALROOT\Device\HarddiskVolume1\root", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\Volume{00000000-0000-0000-0000-000000000000}\root", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:/root", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\child/other", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\..\other", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\.\other", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\child.", "DATA_ROOT_PATH_INVALID"),
        ("\\\\?\\C:\\safe\\child ", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\child:stream", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\CON.txt", "DATA_ROOT_PATH_INVALID"),
        (r"\\?\C:\safe\COM¹", "DATA_ROOT_PATH_INVALID"),
        (r"C:\safe\..\other", "DATA_ROOT_PATH_INVALID"),
        (r"C:\safe\child.", "DATA_ROOT_PATH_INVALID"),
        (r"C:relative", "DATA_ROOT_PATH_INVALID"),
    ],
)
def test_remote_device_and_ambiguous_names_are_rejected_before_filesystem_resolution(path, code):
    with pytest.raises(CoreError, match=code):
        DataRootService(path).preflight_location()


def test_aliases_do_not_bypass_cloud_or_real_junction_guards(tmp_path, monkeypatch):
    cloud = tmp_path / "synthetic OneDrive"
    cloud.mkdir()
    for cloud_env, candidate in (
        (str(cloud), verbatim(cloud / "data")),
        (verbatim(cloud), cloud / "data"),
    ):
        monkeypatch.setenv("OneDrive", cloud_env)
        with pytest.raises(CoreError, match="DATA_ROOT_SYNCED"):
            DataRootService(candidate).preflight_location()
    actual, junction = tmp_path / "actual", tmp_path / "junction"
    actual.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(actual)], capture_output=True, check=False
    )
    assert result.returncode == 0
    for candidate in (junction / "data", verbatim(junction / "data")):
        with pytest.raises(CoreError, match="DATA_ROOT_LINK"):
            DataRootService(candidate).preflight_location()


def test_file_key_reparse_is_rejected_before_any_resolve(tmp_path, monkeypatch):
    import cafe_fin.core.storage as storage_module

    root = DataRootService(tmp_path / "source").initialize()
    alias = DataRootService(verbatim(root.path))
    actual, junction = tmp_path / "actual local target", root.path / "reports" / "linked"
    actual.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(actual)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    calls = []
    resolved, path_resolve = storage_module.resolved_local_path, Path.resolve

    def spy_resolved(path):
        calls.append("resolved_local_path")
        return resolved(path)

    def spy_path(path, *args, **kwargs):
        calls.append("Path.resolve")
        return path_resolve(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage_module, "resolved_local_path", spy_resolved)
        patch.setattr(Path, "resolve", spy_path)
        for service in (root, alias):
            for key in ("reports/linked", "reports/linked/missing.txt"):
                with pytest.raises(CoreError, match="FILE_KEY_INVALID"):
                    service.resolve_key(key)
        assert calls == []


def test_long_local_unicode_root_and_mixed_alias_backup_restore_move_overlaps(tmp_path):
    normal = (
        tmp_path
        / ("long-a-" + "a" * 70)
        / ("long-b-" + "b" * 70)
        / ("long-c-" + "c" * 70)
        / "Dữ liệu dài"
    )
    assert len(str(normal)) > 260
    runtime = Runtime(verbatim(normal), initialize=True, modules=ModuleRegistry(()))
    try:
        stored = runtime.files.put(
            io.BytesIO(b"synthetic original bytes"),
            category="workbooks",
            original_name="Nguồn dài.csv",
            actor="synthetic",
            request_key="original",
        )
        assert (
            location_fingerprint(normal)
            == location_fingerprint(verbatim(normal))
            == legacy_fingerprint(normal)
        )
        copy = normal / "reports" / "Bản gốc dài.csv"
        runtime.files.export(stored.id, verbatim(copy))
        assert copy.read_bytes() == b"synthetic original bytes"
        backup = tmp_path / "Bản sao lưu dài"
        runtime.backups.create(verbatim(backup))
        assert BackupService.verify(verbatim(backup))["referenced_file_count"] == 1
        with pytest.raises(CoreError, match="RESTORE_LOCATION_INVALID"):
            BackupService.restore(backup, verbatim(backup / "nested-new"))
        with pytest.raises(CoreError, match="MOVE_LOCATION_INVALID"):
            runtime.backups.move(verbatim(normal / "nested-new"))
        session = runtime.auth.setup("alias-admin", "synthetic-alias-admin-password")
        generation, operation_id = str(uuid4()), str(uuid4())
        with pytest.raises(CoreError, match="MAINTENANCE_LOCATION_INVALID"):
            MaintenanceOperations(runtime, generation=generation).prepare(
                operation_id,
                "backup",
                access_token=session["access_token"],
                origin_generation=generation,
                destination=verbatim(normal / ("CafeFinBackup-" + operation_id)),
            )
        restored = BackupService.restore(verbatim(backup), verbatim(tmp_path / "Khôi phục dài"))
        assert restored.resolve_key(stored.relative_key).read_bytes() == b"synthetic original bytes"
        moved = runtime.backups.move(verbatim(tmp_path / "Chuyển dài"))
        assert moved.resolve_key(stored.relative_key).read_bytes() == b"synthetic original bytes"
        assert normal.is_dir() and runtime.root.database_path.is_file()
    finally:
        runtime.close()


def test_real_child_verbatim_boot_backup_move_and_restore_share_plain_fingerprints(tmp_path):
    source_root = tmp_path / "Nguồn Rust canonicalize"
    source = Child(verbatim(source_root))
    moved = restored = None
    try:
        assert source.boot["status"] == "ready" and source.boot["runtime_state"] == "ACTIVE"
        with httpx.Client(trust_env=False, timeout=15) as client:
            token = login(client, source, setup=True)
            identity = source.control("maintenance.source_identity", token)
            assert identity["source_fingerprint"] == legacy_fingerprint(source_root)
            backup_id = str(uuid4())
            backup = tmp_path / ("CafeFinBackup-" + backup_id)
            result = source.control(
                "maintenance.prepare",
                token,
                operation_id=backup_id,
                kind="backup",
                destination=verbatim(backup),
            )
            assert result["status"] == "ok" and result["state"] == "PREPARED", result
            # Retry uses the other spelling, not a different immutable destination.
            replay = source.control(
                "maintenance.prepare",
                token,
                operation_id=backup_id,
                kind="backup",
                destination=str(backup),
            )
            assert replay["manifest_sha256"] == result["manifest_sha256"]
            move_id = str(uuid4())
            move_root = tmp_path / ("CafeFinData-" + move_id)
            assert (
                source.control("maintenance.quiesce", token, operation_id=move_id)["state"]
                == "QUIESCED"
            )
            prepared = source.control(
                "maintenance.prepare",
                token,
                operation_id=move_id,
                kind="move",
                destination=verbatim(move_root),
            )
            assert prepared["status"] == "ok" and prepared[
                "candidate_fingerprint"
            ] == legacy_fingerprint(move_root), prepared
            assert (
                source.control("maintenance.close", token, operation_id=move_id)["state"]
                == "CLOSED"
            )
            assert source.process.wait(timeout=10) == 0
            moved = Child(verbatim(move_root), initialize=False, mode="dormant")
            assert moved.boot["status"] == "ready" and moved.boot["runtime_state"] == "DORMANT"
            moved_token = login(client, moved)
            active = moved.control(
                "maintenance.activate",
                moved_token,
                operation_id=move_id,
                origin_generation=source.generation,
            )
            assert active["status"] == "ok" and active["state"] == "ACTIVE", active
            restore_id = str(uuid4())
            restored_root = tmp_path / ("CafeFinData-" + restore_id)
            assert (
                moved.control("maintenance.quiesce", moved_token, operation_id=restore_id)["state"]
                == "QUIESCED"
            )
            prepared = moved.control(
                "maintenance.prepare",
                moved_token,
                operation_id=restore_id,
                kind="restore",
                destination=verbatim(restored_root),
                backup_source=verbatim(backup),
            )
            assert prepared["status"] == "ok" and prepared["state"] == "PREPARED", prepared
            assert prepared["candidate_fingerprint"] == legacy_fingerprint(restored_root)
            assert (
                moved.control("maintenance.close", moved_token, operation_id=restore_id)["state"]
                == "CLOSED"
            )
            assert moved.process.wait(timeout=10) == 0
            restored = Child(verbatim(restored_root), initialize=False, mode="dormant")
            assert (
                restored.boot["status"] == "ready" and restored.boot["runtime_state"] == "DORMANT"
            )
            restored_token = login(client, restored)
            active = restored.control(
                "maintenance.activate",
                restored_token,
                operation_id=restore_id,
                origin_generation=moved.generation,
            )
            assert active["status"] == "ok" and active["state"] == "ACTIVE", active
            settings = client.get(
                restored.base + "/reporting/settings",
                headers={
                    "X-App-Session": TOKEN,
                    "Authorization": "Bearer " + restored_token,
                },
            )
            assert settings.status_code == 200 and settings.json()["restore_review_required"]
            assert (
                restored.control(
                    "maintenance.close",
                    restored_token,
                    operation_id=restore_id,
                    origin_generation=moved.generation,
                )["state"]
                == "CLOSED"
            )
            assert restored.process.wait(timeout=10) == 0
    finally:
        for child in (source, moved, restored):
            if child is not None:
                child.finish()
