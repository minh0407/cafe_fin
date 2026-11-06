import errno
import io
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from cafe_fin.core.backup import BackupService
from cafe_fin.core.db import AUDIT, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.storage import FILES, MIGRATIONS, DataRootService, FileStore, sha256_file
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def storage(tmp_path):
    root = DataRootService(tmp_path / "Dữ liệu cà phê có khoảng trắng").initialize()
    root.acquire_lock()
    database = Database(root.database_path)
    database.migrate(MIGRATIONS)
    writer = WriteCoordinator(database)
    yield root, database, writer, FileStore(root, database, writer)
    writer.close()
    database.close()
    root.release_lock()


def put(store, payload=b"synthetic-original\x00VBA-do-not-execute\xff", key="source-1"):
    return store.put(
        io.BytesIO(payload),
        category="workbooks",
        original_name="Tệp nguồn 0001.xlsm",
        actor="test-admin",
        request_key=key,
    )


def test_original_bytes_idempotency_and_export(storage, tmp_path):
    root, database, writer, store = storage
    first, second = put(store), put(store)
    assert first.id == second.id
    assert store.reconcile()["orphan_keys"] == []
    with store.read(first.id) as stream:
        assert stream.read() == b"synthetic-original\x00VBA-do-not-execute\xff"
    with database.read() as conn:
        assert len(conn.execute(select(FILES)).all()) == 1
        assert len(conn.execute(select(AUDIT).where(AUDIT.c.entity == "core_file")).all()) == 1
    export = tmp_path / "Bản gốc tải lại.xlsm"
    assert store.export(first.id, export)["sha256"] == first.sha256 == sha256_file(export)
    with pytest.raises(CoreError, match="EXPORT_EXISTS"):
        store.export(first.id, export)
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        put(store, b"different bytes")
    assert sha256_file(root.resolve_key(first.relative_key)) == first.sha256


def test_backup_file_copy_does_not_hold_the_writer(storage, tmp_path, monkeypatch):
    import cafe_fin.core.backup as backup_module

    root, database, writer, store = storage
    original = put(store)
    copying, release, done = threading.Event(), threading.Event(), threading.Event()
    copyfile = backup_module.shutil.copyfile
    errors = []

    def slow_copy(source, target):
        if Path(source) == root.resolve_key(original.relative_key):
            copying.set()
            assert release.wait(5), "test did not release the backup"
        return copyfile(source, target)

    monkeypatch.setattr(backup_module.shutil, "copyfile", slow_copy)

    def run_backup():
        try:
            BackupService(root, database, writer).create(tmp_path / "concurrent-backup")
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=run_backup)
    worker.start()
    try:
        assert copying.wait(5)
        # A real write completes while a backup source copy is deliberately blocked.
        second = put(store, b"new committed content", key="concurrent-source")
        assert second.id != original.id
    finally:
        release.set()
        worker.join(timeout=10)
    assert done.is_set() and not errors
    manifest = BackupService.verify(tmp_path / "concurrent-backup")
    assert manifest["referenced_file_count"] == 1


def test_traversal_and_missing_root_are_not_recreated(storage, tmp_path):
    root, *_ = storage
    for key in (
        "../outside",
        "/absolute",
        "C:/secret",
        "workbooks/../../secret",
        "workbooks\\secret",
        "workbooks//secret",
    ):
        with pytest.raises(CoreError, match="FILE_KEY_INVALID"):
            root.resolve_key(key)
    with pytest.raises(CoreError, match="DATA_ROOT_EXISTS"):
        DataRootService(root.path).initialize()
    absent = tmp_path / "ổ không còn sẵn"
    with pytest.raises(CoreError, match="DATA_ROOT_UNAVAILABLE"):
        DataRootService(absent).open_existing()
    assert not absent.exists()
    root_without_db = DataRootService(tmp_path / "marker but missing database").initialize()
    with pytest.raises(CoreError, match="DATABASE_MISSING"):
        root_without_db.open_existing()
    assert not root_without_db.database_path.exists()


def test_real_second_process_cannot_acquire_same_root(storage):
    root, *_ = storage
    program = "from cafe_fin.core.storage import DataRootService; from cafe_fin.core.errors import CoreError; import sys\ntry: DataRootService(sys.argv[1]).acquire_lock()\nexcept CoreError as error: print(error.code); sys.exit(23)\n"
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "backend"))
    process = subprocess.run(
        [sys.executable, "-c", program, str(root.path)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )
    assert process.returncode == 23, process.stderr
    assert "DATA_ROOT_LOCKED" in process.stdout


def test_stream_failure_never_registers_partial_file(storage):
    root, database, _, store = storage

    class BrokenStream:
        def read(self, _size):
            raise OSError(errno.ENOSPC, "injected storage-full error")

    with pytest.raises(CoreError, match="DISK_FULL"):
        store.put(
            BrokenStream(),
            category="workbooks",
            original_name="test.xlsm",
            actor="test-admin",
            request_key="broken",
        )
    with database.read() as conn:
        assert conn.execute(select(FILES)).all() == []
    assert not list((root.path / "imports").glob("*.upload-part"))


def test_limit_and_reconciliation_keep_unknown_files(storage):
    root, database, writer, store = storage
    limited = FileStore(root, database, writer, max_bytes=4)
    with pytest.raises(CoreError, match="FILE_TOO_LARGE"):
        put(limited, b"12345")
    stored = put(store)
    unknown = root.path / "documents" / "do-not-delete.bin"
    unknown.write_bytes(b"unknown")
    root.resolve_key(stored.relative_key).unlink()
    report = store.reconcile()
    assert report["missing_file_ids"] == [stored.id]
    assert "documents/do-not-delete.bin" in report["orphan_keys"]
    assert unknown.read_bytes() == b"unknown"


def test_database_rejection_rolls_back_metadata_and_audit_but_retains_orphan(storage):
    root, database, writer, store = storage
    writer.run(
        lambda conn: conn.exec_driver_sql(
            "CREATE TRIGGER test_reject_file_audit BEFORE INSERT ON core_audit "
            "WHEN NEW.entity = 'core_file' BEGIN SELECT RAISE(ABORT, 'synthetic audit failure'); END"
        )
    )
    with pytest.raises(IntegrityError):
        put(store)
    with database.read() as conn:
        assert conn.execute(select(FILES)).all() == []
        assert conn.execute(select(AUDIT)).all() == []
    report = store.reconcile()
    assert len(report["orphan_keys"]) == 1
    assert root.resolve_key(report["orphan_keys"][0]).is_file()


def test_live_wal_backup_restore_and_move_preserve_links(storage, tmp_path):
    root, database, writer, store = storage
    record = put(store)
    # A held reader makes the test exercise an actually open WAL database.
    with database.read() as reader:
        reader.execute(select(FILES)).all()
        put(store, b"second source", key="source-2")
        backup = tmp_path / "Bản sao lưu đã xác minh"
        service = BackupService(root, database, writer)
        assert service.create(backup)["status"] == "VERIFIED"
    restored = service.restore(backup, tmp_path / "Dữ liệu phục hồi mới")
    assert sha256_file(restored.resolve_key(record.relative_key)) == record.sha256
    restored_database = Database(restored.database_path)
    restored_database.migrate(MIGRATIONS)
    with restored_database.read() as conn:
        assert len(conn.execute(select(FILES)).all()) == 2
    restored_database.close()
    moved = service.move(tmp_path / "Dữ liệu chuyển nơi mới")
    assert moved.database_path.is_file() and root.database_path.is_file()
    assert sha256_file(moved.resolve_key(record.relative_key)) == record.sha256
    with pytest.raises(CoreError, match="RESTORE_DESTINATION_EXISTS"):
        service.restore(backup, restored.path)
    referenced = backup / record.relative_key
    referenced.write_bytes(b"tampered")
    with pytest.raises(CoreError, match="BACKUP_HASH_MISMATCH"):
        service.restore(backup, tmp_path / "must not exist")
    assert not (tmp_path / "must not exist").exists()
