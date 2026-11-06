import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from cafe_fin.core import auth, jobs
from cafe_fin.core.auth import AuthService
from cafe_fin.core.db import AUDIT, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobContext, JobHandler, JobRunner, JobService
from sqlalchemy import Column, Integer, MetaData, Table, insert, select


def environment(path):
    db = Database(path)
    db.migrate(auth.MIGRATIONS + jobs.MIGRATIONS)
    writer = WriteCoordinator(db)
    return db, writer


def wait_state(service, job_id, expected):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = service.status(job_id)
        if result["state"] == expected:
            return result
        time.sleep(0.02)
    pytest.fail(f"job did not reach {expected}: {service.status(job_id)}")


def test_local_roles_logout_restart_and_no_credentials_in_audit(tmp_path):
    db, writer = environment(tmp_path / "auth.db")
    service = AuthService(db, writer)
    assert service.setup_required()
    admin_session = service.setup("quantri", "synthetic-password")
    admin = service.authenticate(admin_session["access_token"])
    assert admin.role == "admin"
    with pytest.raises(CoreError, match="SETUP_COMPLETE"):
        service.setup("another", "synthetic-password")
    user = service.create_user(
        admin,
        username="operator",
        password="other-password",
        role="operator",
        request_key="create-operator",
    )
    assert (
        service.create_user(
            admin,
            username="operator",
            password="other-password",
            role="operator",
            request_key="create-operator",
        )
        == user
    )
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        service.create_user(
            admin,
            username="operator",
            password="different-password",
            role="operator",
            request_key="create-operator",
        )
    operator_session = service.login("operator", "other-password")
    operator = service.authenticate(operator_session["access_token"])
    operator.require("core.write")
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        operator.require("core.manage")
    with pytest.raises(CoreError, match="LAST_ADMIN"):
        service.update_user(
            admin,
            admin.id,
            role="operator",
            active=True,
            expected_version=1,
            request_key="disable-admin",
        )
    service.update_user(
        admin,
        user["id"],
        role="operator",
        active=False,
        expected_version=1,
        request_key="disable-operator",
    )
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        service.authenticate(operator_session["access_token"])
    service.logout(admin_session["access_token"])
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        service.authenticate(admin_session["access_token"])
    token = service.login("quantri", "synthetic-password")["access_token"]
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        AuthService(db, writer).authenticate(token)
    with db.read() as conn:
        rows = str(conn.execute(select(AUDIT)).all())
        assert "password" not in rows
        assert "$argon2" not in rows
    writer.close()
    db.close()


def test_job_receipts_rollback_cancel_and_finalization(tmp_path):
    db, writer = environment(tmp_path / "jobs.db")
    table = Table("sample_effects", MetaData(), Column("id", Integer, primary_key=True))
    writer.run(lambda conn: table.create(conn))
    service = JobService(db, writer, {"sample": JobHandler(lambda context, payload: None, True)})
    job_id = service.submit("synthetic", "sample", {}, "submit")["job_id"]
    assert service.submit("synthetic", "sample", {}, "submit")["job_id"] == job_id
    writer.run(
        lambda conn: conn.execute(
            jobs.JOBS.update().where(jobs.JOBS.c.id == job_id).values(state="RUNNING")
        )
    )
    context = JobContext(service, job_id, threading.Event())

    def effect(conn):
        conn.execute(insert(table).values(id=1))
        return {"id": 1}

    kwargs = {"checkpoint": {"next": 1}, "counts": {"done": 1}, "phase": "sample", "effect": effect}
    assert context.commit_chunk("first", {}, **kwargs) == {"id": 1}
    assert context.commit_chunk("first", {}, **kwargs) == {"id": 1}
    with pytest.raises(CoreError, match="JOB_CHUNK_CONFLICT"):
        context.commit_chunk("first", {"different": True}, **kwargs)

    def fail(conn):
        conn.execute(insert(table).values(id=2))
        raise RuntimeError("synthetic crash")

    with pytest.raises(RuntimeError):
        context.commit_chunk(
            "second", {}, checkpoint={"next": 2}, counts={"done": 2}, phase="sample", effect=fail
        )
    assert context.checkpoint() == {"next": 1}
    with db.read() as conn:
        assert conn.execute(select(table.c.id)).scalars().all() == [1]
    service.cancel(job_id)
    with pytest.raises(jobs.JobInterrupted):
        context.finalize(lambda conn: pytest.fail("cancelled job published"))
    service.recover_interrupted()
    service.resume(job_id)
    writer.run(
        lambda conn: conn.execute(
            jobs.JOBS.update().where(jobs.JOBS.c.id == job_id).values(state="RUNNING")
        )
    )
    context.finalize(lambda conn: {"published": True})
    assert service.status(job_id)["state"] == "COMPLETED"
    with pytest.raises(CoreError, match="JOB_ALREADY_COMPLETED"):
        service.cancel(job_id)
    writer.close()
    db.close()


def test_actual_process_exit_recovers_without_replaying_committed_effect(tmp_path):
    path = tmp_path / "crash.db"
    script = r"""
import os, sys, threading
from sqlalchemy import Column,Integer,MetaData,Table,insert
from cafe_fin.core import auth,jobs
from cafe_fin.core.db import Database,WriteCoordinator
from cafe_fin.core.jobs import JobService,JobHandler,JobContext
db=Database(sys.argv[1]); db.migrate(auth.MIGRATIONS+jobs.MIGRATIONS); w=WriteCoordinator(db)
t=Table('sample_effects',MetaData(),Column('id',Integer,primary_key=True)); w.run(lambda c:t.create(c))
s=JobService(db,w,{'sample':JobHandler(lambda c,p:None,True)})
j=s.submit('synthetic','sample',{},'submit')['job_id']
w.run(lambda c:c.execute(jobs.JOBS.update().where(jobs.JOBS.c.id==j).values(state='RUNNING',attempts=1)))
ctx=JobContext(s,j,threading.Event())
ctx.commit_chunk('first',{},checkpoint={'next':1},counts={'done':1},phase='sample',effect=lambda c:(c.execute(insert(t).values(id=1)), {'id':1})[1])
os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        timeout=20,
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[2] / "backend")},
    )
    assert result.returncode == 23
    db, writer = environment(path)
    table = Table("sample_effects", MetaData(), Column("id", Integer, primary_key=True))

    def handler(context, payload):
        assert context.checkpoint() == {"next": 1}
        context.commit_chunk(
            "first",
            {},
            checkpoint={"next": 1},
            counts={"done": 1},
            phase="sample",
            effect=lambda conn: pytest.fail("replayed committed effect"),
        )
        context.commit_chunk(
            "second",
            {},
            checkpoint={"next": 2},
            counts={"done": 2},
            phase="sample",
            effect=lambda conn: (conn.execute(insert(table).values(id=2)), {"id": 2})[1],
        )

    service = JobService(db, writer, {"sample": JobHandler(handler, True)})
    runner = JobRunner(service)
    runner.start()
    job_id = service.submit("synthetic", "sample", {}, "submit")["job_id"]
    assert service.status(job_id)["state"] == "RECOVERABLE"
    service.resume(job_id)
    final = wait_state(service, job_id, "COMPLETED")
    assert final["counts"] == {"done": 2}
    with db.read() as conn:
        assert conn.execute(select(table.c.id).order_by(table.c.id)).scalars().all() == [1, 2]
    runner.close()
    writer.close()
    db.close()
