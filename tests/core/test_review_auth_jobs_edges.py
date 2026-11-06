import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cafe_fin.core import auth, jobs
from cafe_fin.core.auth import AuthService
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import MIGRATIONS as IMPORT_MIGRATIONS
from cafe_fin.core.imports import ImportAttemptService, ManifestRow, manifest_rows, manifests
from cafe_fin.core.jobs import JobContext, JobHandler, JobInterrupted, JobRunner, JobService
from sqlalchemy import Column, Integer, MetaData, Table, insert, select
from sqlalchemy.exc import IntegrityError


def environment(path, capacity=64):
    db = Database(path)
    db.migrate(auth.MIGRATIONS + jobs.MIGRATIONS)
    writer = WriteCoordinator(db, capacity=capacity)
    return db, writer


def test_runner_survives_normal_writer_backpressure(tmp_path):
    db, writer = environment(tmp_path / "busy.db", capacity=1)
    handler_entered, handler_release = threading.Event(), threading.Event()
    writer_entered, writer_release = threading.Event(), threading.Event()
    thread_errors = []
    old_hook = threading.excepthook
    threading.excepthook = lambda args: thread_errors.append(args.exc_value)

    def handler(context, payload):
        handler_entered.set()
        assert handler_release.wait(5)

    service = JobService(db, writer, {"sample": JobHandler(handler, True)})
    first = service.submit("actor", "sample", {}, "first")["job_id"]
    second = service.submit("actor", "sample", {}, "second")["job_id"]
    runner = JobRunner(service)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        runner.start()
        assert handler_entered.wait(5)

        def foreground(conn):
            writer_entered.set()
            assert writer_release.wait(5)

        future = pool.submit(writer.run, foreground)
        assert writer_entered.wait(5)
        handler_release.set()
        deadline = time.monotonic() + 2
        while runner.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        writer_release.set()
        future.result(timeout=5)
        assert runner.thread.is_alive(), {
            "thread_errors": [str(e) for e in thread_errors],
            "first": service.status(first),
            "second": service.status(second),
        }
    finally:
        handler_release.set()
        writer_release.set()
        runner.close()
        pool.shutdown(wait=True)
        threading.excepthook = old_hook
        writer.close()
        db.close()


def test_context_from_old_run_cannot_publish_after_recovery_and_resume(tmp_path):
    db, writer = environment(tmp_path / "fence.db")
    effects = Table("review_effects", MetaData(), Column("id", Integer, primary_key=True))
    writer.run(lambda conn: effects.create(conn))
    service = JobService(db, writer, {"sample": JobHandler(lambda c, p: None, True)})
    job_id = service.submit("actor", "sample", {}, "submit")["job_id"]
    runner = JobRunner(service)
    try:
        first_claim = writer.run(runner._claim)
        stale = JobContext(service, job_id, threading.Event())
        service.cancel(job_id)
        service.recover_interrupted()
        writer.run(lambda conn: runner._finish_claim(conn, first_claim, "COMPLETED", None))
        assert service.status(job_id)["state"] == "RECOVERABLE"
        service.resume(job_id)
        second_claim = writer.run(runner._claim)
        assert service.status(job_id)["attempts"] == 2
        assert second_claim["generation"] == first_claim["generation"] + 1
        with pytest.raises(JobInterrupted):
            stale.check_cancelled()
        with pytest.raises(JobInterrupted):
            stale.checkpoint()
        with pytest.raises(JobInterrupted):
            stale.commit_chunk(
                "stale",
                {},
                checkpoint={"done": 1},
                counts={"done": 1},
                phase="stale",
                effect=lambda conn: conn.execute(insert(effects).values(id=98)),
            )
        with pytest.raises(JobInterrupted):
            stale.finalize(
                lambda conn: (conn.execute(insert(effects).values(id=99)), {"published": True})[1]
            )
        writer.run(lambda conn: runner._finish_claim(conn, first_claim, "FAILED", "STALE_WORKER"))
        assert service.status(job_id)["state"] == "RUNNING"
        assert service.status(job_id)["generation"] == second_claim["generation"]
        with db.read() as conn:
            assert conn.execute(select(effects)).all() == []
        current = JobContext(
            service, job_id, threading.Event(), generation=second_claim["generation"]
        )
        current.finalize(lambda conn: {"published": True})
        assert service.status(job_id)["state"] == "COMPLETED"
    finally:
        writer.close()
        db.close()


def test_revocation_applies_to_inflight_user_creation(tmp_path):
    db, writer = environment(tmp_path / "auth.db")
    service = AuthService(db, writer)
    first_session = service.setup("firstadmin", "synthetic-password")
    first = service.authenticate(first_session["access_token"])
    service.create_user(
        first, username="secondadmin", password="other-password", role="admin", request_key="second"
    )
    second = service.authenticate(service.login("secondadmin", "other-password")["access_token"])
    entered, release = threading.Event(), threading.Event()
    old_hash = service._hasher.hash

    def gated_hash(password, *args, **kwargs):
        if password == "inflight-password":
            entered.set()
            assert release.wait(5)
        return old_hash(password, *args, **kwargs)

    service._hasher = SimpleNamespace(hash=gated_hash, verify=service._hasher.verify)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(
            service.create_user,
            first,
            username="createdafterrevoke",
            password="inflight-password",
            role="admin",
            request_key="inflight",
        )
        assert entered.wait(5)
        service.update_user(
            second,
            first.id,
            role="operator",
            active=False,
            expected_version=1,
            request_key="revoke-first",
        )
        release.set()
        with pytest.raises(CoreError, match="PERMISSION_DENIED|SESSION_EXPIRED"):
            future.result(timeout=5)
    finally:
        release.set()
        pool.shutdown(wait=True)
        writer.close()
        db.close()


def test_transaction_authorizer_runs_before_cached_retry_and_job_controls(tmp_path):
    db, writer = environment(tmp_path / "cached-authorization.db")
    service = AuthService(db, writer)
    first = service.authenticate(service.setup("firstadmin", "synthetic-password")["access_token"])
    service.create_user(
        first, username="secondadmin", password="other-password", role="admin", request_key="second"
    )
    second = service.authenticate(service.login("secondadmin", "other-password")["access_token"])
    job_service = JobService(
        db, writer, {"sample": JobHandler(lambda context, payload: None, True)}
    )

    def authorize(conn):
        return service.authorize(conn, first, "jobs.write")

    submitted = job_service.submit(first.id, "sample", {}, "cached-submit", authorize=authorize)
    service.update_user(
        second, first.id, role="operator", active=False, expected_version=1, request_key="revoke"
    )
    try:
        for command in (
            lambda: job_service.submit(
                first.id, "sample", {}, "cached-submit", authorize=authorize
            ),
            lambda: job_service.cancel(submitted["job_id"], authorize=authorize),
            lambda: job_service.resume(submitted["job_id"], authorize=authorize),
        ):
            with pytest.raises(CoreError, match="SESSION_EXPIRED"):
                command()
        assert job_service.status(submitted["job_id"])["state"] == "WAITING"
    finally:
        writer.close()
        db.close()


@pytest.mark.parametrize("target", ["sealed-manifest", "sealed-row", "building-row"])
def test_insert_or_replace_cannot_bypass_immutable_snapshot_triggers(tmp_path, target):
    db = Database(tmp_path / f"replace-{target}.db")
    db.migrate(IMPORT_MIGRATIONS)
    writer = WriteCoordinator(db)
    service = ImportAttemptService()
    pins = {
        "staging_revision": 1,
        "mapping_revision": 1,
        "decision_revision": 1,
        "validation_token": "synthetic",
        "mapping_snapshot": {},
        "duplicate_decisions": {},
        "mode": "valid_rows_only",
    }
    manifest = writer.run(
        lambda conn: service.create_manifest(conn, job_id="synthetic", pins=pins, expected_count=1)
    )
    source = ManifestRow(
        "source-1",
        {
            "source_sheet": "Sổ",
            "source_row": 2,
            "revision": 1,
            "raw_values": {"A": "001"},
            "edited_values": {},
            "typed_values": {"code": "001"},
        },
    )
    writer.run(
        lambda conn: service.append_manifest_chunk(conn, manifest, expected_start=0, rows=[source])
    )
    if target != "building-row":
        writer.run(lambda conn: service.seal_manifest(conn, manifest))
    try:
        with db.read() as conn:
            assert conn.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
            table = manifests if target == "sealed-manifest" else manifest_rows
            original = dict(conn.execute(select(table)).mappings().one())
        replacement = dict(original)
        if target == "sealed-manifest":
            replacement["state"] = "BUILDING"
            replacement["pins_json"] = "{}"
        else:
            replacement["snapshot_json"] = json.dumps({"tampered": True})
        with pytest.raises(IntegrityError, match="immutable import snapshot"):
            writer.run(
                lambda conn: conn.execute(
                    insert(table).prefix_with("OR REPLACE").values(**replacement)
                )
            )
        with db.read() as conn:
            assert dict(conn.execute(select(table)).mappings().one()) == original
    finally:
        writer.close()
        db.close()
