"""Borrowed job reads retain the caller's real SQLite WAL snapshot and lifetime."""

import pytest
from cafe_fin.core.db import Database
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime


@pytest.fixture
def runtime(tmp_path):
    runtime = Runtime(tmp_path / "job-snapshot", initialize=True, modules=ModuleRegistry(()))
    try:
        yield runtime
    finally:
        runtime.close()


def submit(runtime):
    return runtime.jobs.submit(
        "synthetic-owner", "foundation.sample", {"private_payload": "not-in-status"}, "job"
    )["job_id"]


def test_borrowed_snapshot_survives_second_connection_change_and_fresh_read_sees_change(runtime):
    job_id = submit(runtime)
    original = runtime.jobs.status(job_id)
    assert original["state"] == "WAITING"
    assert set(original) == {
        "id",
        "kind",
        "actor",
        "state",
        "phase",
        "attempts",
        "generation",
        "error_code",
        "created_at",
        "updated_at",
        "counts",
        "checkpoint",
        "cancel_requested",
    }
    with runtime.reader() as connection:
        connection.exec_driver_sql("BEGIN")
        transaction = connection.get_transaction()
        physical = connection.connection.driver_connection
        assert runtime.jobs.status(job_id, connection=connection) == original
        writer_physical = runtime.writer.run(lambda conn: conn.connection.driver_connection)
        assert writer_physical is not physical
        changed = runtime.jobs.cancel(job_id)
        assert changed["state"] == "CANCELLED" and changed["cancel_requested"]
        assert runtime.jobs.status(job_id, connection=connection) == original
        assert runtime.jobs.status(job_id) == changed
        assert not connection.closed and connection.get_transaction() is transaction
        assert connection.connection.driver_connection is physical and physical.in_transaction
        assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    with runtime.reader() as fresh:
        fresh.exec_driver_sql("BEGIN")
        assert runtime.jobs.status(job_id, connection=fresh) == changed


def test_missing_job_keeps_existing_404_and_borrowed_transaction_alive(runtime):
    with pytest.raises(CoreError) as absent:
        runtime.jobs.status("missing")
    assert absent.value.code == "JOB_NOT_FOUND" and absent.value.status == 404
    with runtime.reader() as connection:
        connection.exec_driver_sql("BEGIN")
        transaction = connection.get_transaction()
        with pytest.raises(CoreError) as borrowed:
            runtime.jobs.status("missing", connection=connection)
        assert borrowed.value.code == "JOB_NOT_FOUND" and borrowed.value.status == 404
        assert connection.get_transaction() is transaction
        assert connection.connection.driver_connection.in_transaction
        assert not connection.closed
        assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1


@pytest.mark.parametrize("mode", ["implicit", "sqlalchemy_begin", "closed", "invalidated"])
def test_requires_live_explicit_sqlite_read_only_transaction(runtime, mode):
    job_id = submit(runtime)
    with runtime.reader() as connection:
        if mode == "sqlalchemy_begin":
            connection.commit()
            connection.begin()
        elif mode in {"closed", "invalidated"}:
            connection.exec_driver_sql("BEGIN")
            if mode == "closed":
                connection.close()
            else:
                connection.invalidate()
        with pytest.raises(CoreError) as error:
            runtime.jobs.status(job_id, connection=connection)
        assert error.value.code == "READ_ONLY_SNAPSHOT_REQUIRED"
        assert error.value.status == 409


def test_write_enabled_connection_is_rejected_without_ending_transaction(runtime):
    job_id = submit(runtime)
    with runtime.database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        transaction = connection.get_transaction()
        with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
            runtime.jobs.status(job_id, connection=connection)
        assert connection.get_transaction() is transaction
        assert connection.connection.driver_connection.in_transaction
        assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 0


def test_foreign_engine_and_non_connection_are_rejected(runtime, tmp_path):
    job_id = submit(runtime)
    # No jobs schema in this other database: rejection must precede any job SELECT.
    foreign = Database(tmp_path / "foreign.db")
    try:
        with foreign.read() as connection:
            connection.exec_driver_sql("BEGIN")
            transaction = connection.get_transaction()
            with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
                runtime.jobs.status(job_id, connection=connection)
            assert connection.get_transaction() is transaction
            assert connection.connection.driver_connection.in_transaction
    finally:
        foreign.close()
    with pytest.raises(CoreError, match="READ_ONLY_SNAPSHOT_REQUIRED"):
        runtime.jobs.status(job_id, connection="untrusted-path")
