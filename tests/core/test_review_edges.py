"""Regression cases found by independent foundation review; use real SQLite/writer."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cafe_fin.core import auth, jobs
from cafe_fin.core.auth import AuthService
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler, JobRunner, JobService
from cafe_fin.core.modules import Migration, ModuleManifest, ModuleRegistry, schema_checksum
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, insert, select
from sqlalchemy.exc import OperationalError


def test_reader_connection_rejects_writes_outside_serialized_writer(tmp_path):
    database = Database(tmp_path / "reader.db")
    database.migrate()
    writer = WriteCoordinator(database)
    table = Table("review_reader_guard", MetaData(), Column("id", Integer, primary_key=True))
    try:
        writer.run(lambda conn: table.create(conn))
        with database.read() as conn, pytest.raises(OperationalError, match="readonly"):
            conn.execute(insert(table).values(id=1))
            conn.commit()
    finally:
        writer.close()
        database.close()


def test_job_runner_survives_writer_backpressure_when_finishing(tmp_path):
    database = Database(tmp_path / "backpressure.db")
    database.migrate(jobs.MIGRATIONS)
    writer = WriteCoordinator(database, capacity=1)
    handler_entered, release_handler = threading.Event(), threading.Event()
    blocker_entered, release_blocker = threading.Event(), threading.Event()

    def handler(context, payload):
        handler_entered.set()
        assert release_handler.wait(5)

    service = JobService(database, writer, {"review": JobHandler(handler)})
    job_id = service.submit("synthetic", "review", {}, "backpressure")["job_id"]
    runner = JobRunner(service)
    runner.start()
    try:
        assert handler_entered.wait(5)

        def block(conn):
            blocker_entered.set()
            assert release_blocker.wait(5)

        with ThreadPoolExecutor(max_workers=1) as pool:
            blocker = pool.submit(writer.run, block)
            try:
                assert blocker_entered.wait(5)
                release_handler.set()
                # Runner now reaches its finish transaction while the only slot is occupied.
                time.sleep(0.15)
                assert runner.thread.is_alive(), "WRITER_BUSY killed the persistent job runner"
            finally:
                release_blocker.set()
                blocker.result(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and service.status(job_id)["state"] != "COMPLETED":
            time.sleep(0.01)
        assert service.status(job_id)["state"] == "COMPLETED"
    finally:
        release_handler.set()
        release_blocker.set()
        runner.close()
        writer.close()
        database.close()


def test_successful_logins_do_not_consume_failed_login_budget(tmp_path):
    database = Database(tmp_path / "success-logins.db")
    database.migrate(auth.MIGRATIONS)
    writer = WriteCoordinator(database)
    try:
        service = AuthService(database, writer)
        service.setup("review-admin", "synthetic-review-password")
        for _ in range(9):
            token = service.login("review-admin", "synthetic-review-password")["access_token"]
            service.logout(token)
    finally:
        writer.close()
        database.close()


def test_job_runner_survives_writer_backpressure_before_claim(tmp_path):
    database = Database(tmp_path / "claim-backpressure.db")
    database.migrate(jobs.MIGRATIONS)
    writer = WriteCoordinator(database, capacity=1)
    blocker_entered, release_blocker = threading.Event(), threading.Event()
    service = JobService(database, writer, {"review": JobHandler(lambda context, payload: None)})
    runner = JobRunner(service)
    runner.start()
    try:

        def block(conn):
            blocker_entered.set()
            assert release_blocker.wait(5)

        def occupy_writer():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    return writer.run(block)
                except CoreError as error:
                    if error.code != "WRITER_BUSY":
                        raise
                    time.sleep(0.001)
            pytest.fail("could not occupy writer")

        with ThreadPoolExecutor(max_workers=1) as pool:
            blocker = pool.submit(occupy_writer)
            try:
                assert blocker_entered.wait(5)
                service.wake.set()
                time.sleep(0.15)
                assert runner.thread.is_alive()
                assert runner.error_code is None
            finally:
                release_blocker.set()
                blocker.result(timeout=5)
        job_id = service.submit("synthetic", "review", {}, "after-backpressure")["job_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and service.status(job_id)["state"] != "COMPLETED":
            time.sleep(0.01)
        assert service.status(job_id)["state"] == "COMPLETED"
    finally:
        release_blocker.set()
        runner.close()
        writer.close()
        database.close()


def test_job_runner_exposes_sanitized_fatal_error_instead_of_retrying_programming_fault(tmp_path):
    database = Database(tmp_path / "fatal-runner.db")
    database.migrate(jobs.MIGRATIONS)
    writer = WriteCoordinator(database)
    service = JobService(database, writer)
    runner = JobRunner(service)
    runner.start()
    try:
        writer.run(lambda conn: conn.exec_driver_sql("DROP TABLE core_jobs"))
        service.wake.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and runner.thread.is_alive():
            time.sleep(0.01)
        assert not runner.thread.is_alive()
        assert runner.error_code == "JOB_RUNNER_FAILED"
    finally:
        runner.close()
        writer.close()
        database.close()


def test_same_name_migration_detects_changed_schema_with_explicit_checksum(tmp_path):
    database = Database(tmp_path / "schema-signature.db")
    before = MetaData()
    Table("review_schema", before, Column("id", Integer, primary_key=True))
    after = MetaData()
    Table("review_schema", after, Column("id", Integer, primary_key=True), Column("label", String))
    first = Migration("review", 1, "unchanged-name", before.create_all, schema_checksum(before))
    changed = Migration("review", 1, "unchanged-name", after.create_all, schema_checksum(after))
    try:
        database.migrate((first,))
        with pytest.raises(CoreError, match="MIGRATION_CHANGED"):
            database.migrate((changed,))
        with database.read() as conn:
            assert [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(review_schema)")] == [
                "id"
            ]
    finally:
        database.close()


def test_signature_covers_indexes_and_triggers_and_is_stable_across_table_order():
    first, second = MetaData(), MetaData()
    Table("review_b", first, Column("id", Integer, primary_key=True))
    a = Table("review_a", first, Column("id", Integer, primary_key=True))
    Table("review_a", second, Column("id", Integer, primary_key=True))
    Table("review_b", second, Column("id", Integer, primary_key=True))
    original = schema_checksum(first)
    assert original == schema_checksum(second)
    Index("ix_review_a_id", a.c.id)
    assert original != schema_checksum(first)
    trigger = "CREATE TRIGGER review_trigger BEFORE DELETE ON review_a BEGIN SELECT RAISE(ABORT,'retain'); END"
    assert schema_checksum(first) != schema_checksum(first, (trigger,))
    assert schema_checksum(first, (trigger,)) != schema_checksum(
        first, (trigger.replace("retain", "changed"),)
    )


def test_module_registry_rejects_missing_or_malformed_migration_checksum():
    for checksum in ("", "not-a-sha256"):
        migration = Migration("review", 1, "sample", lambda conn: None, checksum)
        with pytest.raises(CoreError, match="MIGRATION_CHECKSUM_REQUIRED"):
            ModuleRegistry((ModuleManifest("review", "/review", migrations=(migration,)),))
    migration = Migration("review", 1, "sample", lambda conn: None, schema_checksum(MetaData()))
    assert ModuleRegistry((ModuleManifest("review", "/review", migrations=(migration,)),)).ordered()


def test_reversed_migration_versions_preserve_namespace_dependency_order(tmp_path):
    database = Database(tmp_path / "migration-order.db")
    applied = []

    def migration(namespace, version, statements):
        def apply(conn):
            for statement in statements:
                conn.exec_driver_sql(statement)
            applied.append((namespace, version))

        return Migration(
            namespace, version, f"step-{version}", apply, schema_checksum(MetaData(), statements)
        )

    parent1 = migration(
        "review_parent", 1, ("CREATE TABLE review_parent (id INTEGER PRIMARY KEY)",)
    )
    parent2 = migration(
        "review_parent",
        2,
        (
            "ALTER TABLE review_parent ADD COLUMN label TEXT NOT NULL DEFAULT 'first'",
            "INSERT INTO review_parent VALUES (1, 'ready')",
        ),
    )
    child1 = migration(
        "review_child",
        1,
        (
            "CREATE TABLE review_child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES review_parent(id))",
        ),
    )
    child2 = migration("review_child", 2, ("INSERT INTO review_child VALUES (1, 1)",))
    try:
        database.migrate((parent2, parent1, child2, child1))
        assert applied == [
            ("review_parent", 1),
            ("review_parent", 2),
            ("review_child", 1),
            ("review_child", 2),
        ]
        database.migrate((parent1, parent2, child1, child2))
        assert len(applied) == 4
        with database.read() as conn:
            assert (
                conn.exec_driver_sql(
                    "SELECT p.label FROM review_child c JOIN review_parent p ON p.id=c.parent_id"
                ).scalar_one()
                == "ready"
            )
    finally:
        database.close()


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_lost_database_never_recreated_and_uri_handles_unicode_spaces_and_metacharacters(
    tmp_path, operation
):
    directory = tmp_path / "Dữ liệu cà phê %23 # &"
    directory.mkdir()
    path = directory / "Sổ có khoảng trắng %23 # &.db"
    database = Database(path)
    database.migrate()
    writer = WriteCoordinator(database)
    table = Table("review_persisted", MetaData(), Column("id", Integer, primary_key=True))
    writer.run(lambda conn: table.create(conn))
    writer.run(lambda conn: conn.execute(insert(table).values(id=7)))
    writer.close()
    moved = path.with_name("Đã chuyển % # &.db")
    if operation == "rename":
        path.rename(moved)
    else:
        path.unlink()
    try:
        with pytest.raises(OperationalError):
            with database.read() as conn:
                conn.execute(select(table))
        assert not path.exists()
        with pytest.raises(CoreError, match="DATABASE_MISSING"):
            Database(path, create=False)
        assert not path.exists()
        if operation == "rename":
            restored = Database(moved, create=False)
            try:
                restored.migrate()
                with restored.read() as conn:
                    assert conn.execute(select(table.c.id)).scalar_one() == 7
            finally:
                restored.close()
    finally:
        database.close()


def test_existing_empty_database_is_not_silently_initialized(tmp_path):
    path = tmp_path / "empty.db"
    path.touch()
    with pytest.raises(CoreError, match="DATABASE_INVALID"):
        Database(path, create=False)
    assert path.stat().st_size == 0


def test_existing_unrecognized_database_is_not_bootstrapped(tmp_path):
    path = tmp_path / "other-database.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated_data (id INTEGER PRIMARY KEY)")
    database = Database(path, create=False)
    try:
        with pytest.raises(CoreError, match="DATABASE_INVALID"):
            database.migrate()
        with database.read() as conn:
            assert (
                conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE name LIKE 'core_%'"
                ).all()
                == []
            )
    finally:
        database.close()


def test_backup_source_missing_cannot_create_empty_database(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "snapshot.db"
    database = Database(source)
    database.migrate()
    source.unlink()
    try:
        with pytest.raises(sqlite3.OperationalError):
            database.backup_to(target)
        assert not source.exists()
        assert not target.exists()
    finally:
        database.close()


def test_actual_core_migration_signatures_are_explicit_and_stable_across_processes():
    from cafe_fin.core import imports, storage

    local = [
        migration.checksum
        for migration in auth.MIGRATIONS + jobs.MIGRATIONS + imports.MIGRATIONS + storage.MIGRATIONS
    ]
    assert all(len(checksum) == 64 for checksum in local)
    script = """
import json
from cafe_fin.core import auth, jobs, imports, storage
print(json.dumps([m.checksum for m in auth.MIGRATIONS+jobs.MIGRATIONS+imports.MIGRATIONS+storage.MIGRATIONS]))
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "backend"))
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert json.loads(result.stdout) == local
