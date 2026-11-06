import time

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.auth import AuthService
from cafe_fin.core.db import WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler, JobService
from cafe_fin.core.modules import Migration, ModuleManifest, ModuleRegistry, schema_checksum
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import FileStore
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select


def wait_completed(runtime, identity):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = runtime.jobs.status(identity)
        if status["state"] == "COMPLETED":
            return status
        time.sleep(0.01)
    pytest.fail(f"custom job failed to complete: {runtime.jobs.status(identity)}")


def test_owned_module_registers_migration_router_job_and_recovery_hook_without_core_edits(tmp_path):
    metadata = MetaData()
    state = Table(
        "sample_state",
        metadata,
        Column("key", String, primary_key=True),
        Column("value", String, nullable=False),
    )
    effects = Table("sample_effects", metadata, Column("id", Integer, primary_key=True))
    startup_observations = []
    router = APIRouter()

    @router.get("/effects")
    def read_effects(request: Request):
        with request.app.state.runtime.reader() as conn:
            return {
                "items": list(conn.execute(select(effects.c.id).order_by(effects.c.id)).scalars())
            }

    def worker(context, payload):
        context.commit_chunk(
            "effect",
            payload,
            checkpoint={"next": 1},
            counts={"done": 1},
            phase="sample.work",
            effect=lambda conn: (
                conn.execute(insert(effects).values(id=payload["id"])),
                {"id": payload["id"]},
            )[1],
        )
        context.finalize(lambda conn: {"complete": True})

    def recover(runtime: Runtime):
        assert isinstance(runtime.writer, WriteCoordinator)
        assert isinstance(runtime.files, FileStore)
        assert isinstance(runtime.auth, AuthService)
        assert isinstance(runtime.jobs, JobService)
        assert not runtime.runner.thread.is_alive()
        assert not runtime.auth.setup_required()
        assert runtime.files.reconcile() == {
            "missing_file_ids": [],
            "mismatched_file_ids": [],
            "orphan_keys": [],
        }
        with runtime.reader() as conn:
            job_id = conn.execute(select(state.c.value).where(state.c.key == "job")).scalar_one()
        observed = runtime.jobs.status(job_id)
        startup_observations.append(observed["state"])
        assert observed["state"] == "RECOVERABLE"
        runtime.writer.run(
            lambda conn: conn.execute(insert(state).values(key="hook", value="restored"))
        )
        runtime.jobs.resume(job_id)

    manifest = ModuleManifest(
        "sample",
        "/sample",
        permissions=("sample.read", "sample.write"),
        migrations=(
            Migration(
                "sample",
                1,
                "sample owned tables",
                metadata.create_all,
                checksum=schema_checksum(metadata),
            ),
        ),
        router=router,
        job_handlers={"sample.work": JobHandler(worker, resumable=True)},
        on_startup=recover,
    )
    path = tmp_path / "Module đăng ký dữ liệu"
    # Constructor registration only: coordinator needs a manifest, not source edits in core.
    registry = ModuleRegistry((manifest,))
    initial = Runtime(path, initialize=True, modules=registry)
    try:
        initial.auth.setup("sampleadmin", "synthetic-module-password")
        job_id = initial.jobs.submit("synthetic", "sample.work", {"id": 7}, "sample-job")["job_id"]
        initial.writer.run(lambda conn: conn.execute(insert(state).values(key="job", value=job_id)))
        initial.writer.run(initial.runner._claim)
        assert initial.jobs.status(job_id)["state"] == "RUNNING"
    finally:
        # Simulate durable abandoned state; crash mechanics have separate subprocess tests.
        initial.close()

    recovered = Runtime(path, modules=registry)
    token, port = "synthetic-module-session-0123456789abcdef", 48952
    app = create_app(recovered, token, port=port)
    with TestClient(app, base_url=f"http://127.0.0.1:{port}") as client:
        assert startup_observations == ["RECOVERABLE"]
        assert "foundation.sample" in recovered.jobs.handlers
        assert "sample.work" in recovered.jobs.handlers
        final = wait_completed(recovered, job_id)
        assert final["counts"] == {"done": 1}
        assert final["generation"] == 2
        headers = {"X-App-Session": token, "Origin": "http://tauri.localhost"}
        login = client.post(
            "/api/v1/auth/login",
            headers=headers,
            json={"username": "sampleadmin", "password": "synthetic-module-password"},
        )
        assert login.status_code == 200
        headers["Authorization"] = "Bearer " + login.json()["access_token"]
        response = client.get("/api/v1/sample/effects", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"items": [7]}
        recovered.start()  # Idempotent start must not rerun recovery hooks.
        assert startup_observations == ["RECOVERABLE"]

    reopened = Runtime(path, modules=registry)
    try:
        assert reopened.jobs.status(job_id)["state"] == "COMPLETED"
        with reopened.reader() as conn:
            assert conn.execute(select(effects.c.id)).scalars().all() == [7]
            assert (
                conn.execute(select(state.c.value).where(state.c.key == "hook")).scalar_one()
                == "restored"
            )
    finally:
        reopened.close()


def test_job_registration_is_frozen_and_rejects_invalid_prefix_or_handler():
    handlers = {"sample.work": JobHandler(lambda context, payload: None)}
    manifest = ModuleManifest("sample", "/sample", job_handlers=handlers)
    handlers["foreign.work"] = JobHandler(lambda context, payload: None)
    assert tuple(manifest.job_handlers) == ("sample.work",)
    with pytest.raises(TypeError):
        manifest.job_handlers["sample.other"] = JobHandler(lambda context, payload: None)
    for kind in ("foreign.work", "sample.", "samplework"):
        with pytest.raises(CoreError, match="INVALID_JOB_NAMESPACE"):
            ModuleRegistry(
                (ModuleManifest("sample", "/sample", job_handlers={kind: handlers["sample.work"]}),)
            )
    with pytest.raises(CoreError, match="INVALID_JOB_HANDLER"):
        ModuleRegistry(
            (ModuleManifest("sample", "/sample", job_handlers={"sample.work": object()}),)
        )


def test_module_cannot_override_core_job_registration(tmp_path):
    manifest = ModuleManifest(
        "foundation",
        "/foundation",
        job_handlers={"foundation.sample": JobHandler(lambda context, payload: None)},
    )
    with pytest.raises(CoreError, match="DUPLICATE_JOB_KIND"):
        Runtime(tmp_path / "duplicate", initialize=True, modules=ModuleRegistry((manifest,)))


def test_startup_hooks_follow_dependency_order_and_fail_before_worker_start(tmp_path):
    observed = []

    def hook(name):
        def run(runtime):
            assert not runtime.runner.thread.is_alive()
            observed.append(name)

        return run

    registry = ModuleRegistry(
        (
            ModuleManifest("child", "/child", dependencies=("parent",), on_startup=hook("child")),
            ModuleManifest("parent", "/parent", on_startup=hook("parent")),
        )
    )
    runtime = Runtime(tmp_path / "dependency-order", initialize=True, modules=registry)
    try:
        runtime.start()
        assert observed == ["parent", "child"]
    finally:
        runtime.close()

    def fail(runtime):
        raise CoreError("SAMPLE_RECOVERY_FAILED", "Lỗi phục hồi tổng hợp.")

    runtime = Runtime(
        tmp_path / "failed-hook",
        initialize=True,
        modules=ModuleRegistry((ModuleManifest("sample", "/sample", on_startup=fail),)),
    )
    try:
        with pytest.raises(CoreError, match="SAMPLE_RECOVERY_FAILED"):
            runtime.start()
        assert not runtime.runner.thread.is_alive()
    finally:
        runtime.close()
