"""Real ASGI request lifetimes, SQLite writer fencing and cooperative core shutdown."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.periodic import PeriodicTask
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import DataRootService
from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

PORT = 48963
TOKEN = "synthetic-maintenance-app-session-0123456789"
PASSWORD = "synthetic-maintenance-password"


@pytest.fixture
def make_runtime(tmp_path):
    runtimes = []

    def make(*, mode="active", manifest=None):
        runtime = Runtime(
            tmp_path / str(uuid4()),
            initialize=True,
            activation_mode=mode,
            modules=ModuleRegistry((manifest,) if manifest else ()),
        )
        runtimes.append(runtime)
        admin = runtime.auth.setup("maintenance-admin", PASSWORD)
        actor = runtime.auth.authenticate(admin["access_token"])
        guardian = runtime.auth.create_user(
            actor,
            username="guardian-admin",
            password=PASSWORD,
            role="admin",
            request_key="guardian",
        )
        operator = runtime.auth.create_user(
            actor,
            username="maintenance-operator",
            password=PASSWORD,
            role="operator",
            request_key="op",
        )
        runtime.writer.run(
            lambda conn: conn.exec_driver_sql("CREATE TABLE sample_probe(value INTEGER NOT NULL)")
        )
        runtime.writer.run(lambda conn: conn.exec_driver_sql("INSERT INTO sample_probe VALUES (0)"))
        return SimpleNamespace(
            runtime=runtime,
            admin=admin,
            actor=actor,
            guardian=guardian,
            operator=operator,
            app=create_app(runtime, TOKEN, port=PORT),
            headers={
                "X-App-Session": TOKEN,
                "Authorization": "Bearer " + admin["access_token"],
                "Origin": "http://tauri.localhost",
            },
        )

    yield make
    for runtime in runtimes:
        runtime.close()


def client_for(env):
    return TestClient(env.app, base_url=f"http://127.0.0.1:{PORT}", headers=env.headers)


def value(runtime):
    with runtime.reader() as conn:
        return conn.exec_driver_sql("SELECT value FROM sample_probe").scalar_one()


def write(runtime):
    runtime.writer.run(lambda conn: conn.exec_driver_sql("UPDATE sample_probe SET value=value+1"))


def observe_hold(runtime, monkeypatch):
    held, original = threading.Event(), runtime.maintenance.hold

    def hold(operation_id):
        original(operation_id)
        held.set()

    monkeypatch.setattr(runtime.maintenance, "hold", hold)
    return held


def assert_resources_held(runtime):
    assert not runtime._closed and not runtime.writer._closed
    assert runtime.root._lock is not None and runtime.log_handler.stream is not None
    with pytest.raises(CoreError, match="DATA_ROOT_LOCKED"):
        DataRootService(runtime.root.path).acquire_lock()
    with runtime.reader() as conn:
        assert conn.exec_driver_sql("SELECT 1").scalar_one() == 1


def test_dormant_lifespan_has_no_recovery_hooks_jobs_or_timer_until_current_admin_activation(
    make_runtime,
):
    hooks, ran = [], threading.Event()

    def startup(runtime):
        assert runtime.maintenance.status()["state"] == "ACTIVATING"
        hooks.append("hook")
        write(runtime)

    def job(context, payload):
        context.finalize(lambda conn: {"complete": True})
        ran.set()

    env = make_runtime(
        mode="dormant",
        manifest=ModuleManifest(
            "sample",
            "/sample",
            on_startup=startup,
            job_handlers={"sample.probe": JobHandler(job)},
            periodic_tasks={"sample.tick": PeriodicTask(lambda runtime: hooks.append("tick"), 300)},
        ),
    )
    runtime = env.runtime
    job_id = runtime.jobs.submit(env.actor.id, "sample.probe", {}, "before-activation")["job_id"]
    with client_for(env) as client:
        runtime.start()  # Public legacy start cannot bypass dormant admission.
        assert hooks == [] and value(runtime) == 0
        assert runtime.runner.thread.ident is None and runtime.periodic.thread.ident is None
        assert runtime.jobs.status(job_id)["state"] == "WAITING"
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health", headers={"X-App-Session": "wrong"}).status_code == 401
        for method, path in (
            ("get", "/api/v1/auth/me"),
            ("get", "/api/v1/users"),
            ("post", "/api/v1/auth/setup"),
            ("post", "/api/v1/users"),
            ("options", "/api/v1/users"),
            ("get", "/api/v1/jobs/unknown"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "MAINTENANCE_REQUIRED"
        assert client.post("/api/v1/auth/logout").status_code == 200
        with pytest.raises(CoreError, match="SESSION_EXPIRED"):
            runtime.activate(str(uuid4()), access_token=env.admin["access_token"])
        logged_in = client.post(
            "/api/v1/auth/login", json={"username": "maintenance-admin", "password": PASSWORD}
        ).json()["access_token"]
        operation_id = str(uuid4())
        assert runtime.activate(operation_id, access_token=logged_in)["state"] == "ACTIVE"
        assert ran.wait(3)
        assert hooks == ["hook"] and value(runtime) == 1
        assert runtime.activate(operation_id, access_token=logged_in)["state"] == "ACTIVE"
        assert hooks == ["hook"]
        client.headers["Authorization"] = "Bearer " + logged_in
        assert client.get("/api/v1/users").status_code == 200
        # Activation and later terminal quiescence are distinct native operations.
        assert runtime.quiesce(str(uuid4()), access_token=logged_in)["state"] == "QUIESCED"


def test_admitted_http_write_finishes_before_fence_and_later_requests_are_denied(
    make_runtime,
    monkeypatch,
):
    env = make_runtime()
    runtime = env.runtime
    entered, release = threading.Event(), threading.Event()

    @env.app.post("/api/v1/sample/write")
    def delayed(request: Request):
        entered.set()
        assert release.wait(5)

        def mutate(conn):
            runtime.auth.authorize(conn, request.state.principal, "records.write")
            conn.exec_driver_sql("UPDATE sample_probe SET value=value+1")

        runtime.writer.run(mutate)
        return {"written": True}

    held = observe_hold(runtime, monkeypatch)
    with client_for(env) as client, ThreadPoolExecutor(max_workers=2) as executor:
        request = executor.submit(client.post, "/api/v1/sample/write")
        assert entered.wait(3)
        operation_id = str(uuid4())
        quiesce = executor.submit(
            runtime.quiesce, operation_id, access_token=env.admin["access_token"]
        )
        try:
            assert held.wait(3)
            assert runtime.runner.stop_event.wait(1) and runtime.periodic.stop_event.is_set()
            assert runtime.maintenance.status()["business_requests"] == 1
            assert not quiesce.done() and value(runtime) == 0
            later = client.post("/api/v1/sample/write")
            assert later.status_code == 503
            assert later.headers["access-control-allow-origin"] == "http://tauri.localhost"
            assert client.get("/api/v1/health").status_code == 200
        finally:
            release.set()
        assert request.result(timeout=3).status_code == 200
        assert quiesce.result(timeout=3)["state"] == "QUIESCED"
        assert value(runtime) == 1
        assert (
            runtime.quiesce(operation_id, access_token=env.admin["access_token"])["state"]
            == "QUIESCED"
        )
        with pytest.raises(CoreError, match="RUNTIME_CLOSED"):
            runtime.start()


def test_streaming_response_lease_is_held_through_last_body_chunk(make_runtime, monkeypatch):
    env = make_runtime()
    entered, release = threading.Event(), threading.Event()

    @env.app.get("/api/v1/sample/stream")
    def stream():
        def chunks():
            yield b"first;"
            entered.set()
            assert release.wait(5)
            assert value(env.runtime) == 0
            yield b"last"

        return StreamingResponse(chunks(), media_type="application/octet-stream")

    held = observe_hold(env.runtime, monkeypatch)
    with client_for(env) as client, ThreadPoolExecutor(max_workers=2) as executor:
        response = executor.submit(client.get, "/api/v1/sample/stream")
        assert entered.wait(3)
        quiesce = executor.submit(
            env.runtime.quiesce, str(uuid4()), access_token=env.admin["access_token"]
        )
        try:
            assert held.wait(3)
            assert env.runtime.maintenance.status()["business_requests"] == 1
            assert not quiesce.done()
        finally:
            release.set()
        assert response.result(timeout=3).content == b"first;last"
        assert quiesce.result(timeout=3)["state"] == "QUIESCED"
        assert env.runtime.maintenance.status()["requests"] == 0


@pytest.mark.parametrize("method", ["activate", "quiesce"])
def test_operator_or_previously_revoked_admin_cannot_change_admission(make_runtime, method):
    env = make_runtime(mode="dormant" if method == "activate" else "active")
    runtime = env.runtime
    operator_token = runtime.auth.login("maintenance-operator", PASSWORD)["access_token"]
    initial = runtime.maintenance.status()
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        getattr(runtime, method)(str(uuid4()), access_token=operator_token)
    assert runtime.maintenance.status() == initial
    guardian = runtime.auth.authenticate(
        runtime.auth.login("guardian-admin", PASSWORD)["access_token"]
    )
    runtime.auth.update_user(
        guardian,
        env.actor.id,
        role="operator",
        active=True,
        expected_version=1,
        request_key="revoke",
    )
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        getattr(runtime, method)(str(uuid4()), access_token=env.admin["access_token"])
    assert runtime.maintenance.status() == initial


def test_admitted_revocation_commits_before_final_serialized_permission_fence(
    make_runtime,
    monkeypatch,
):
    env = make_runtime()
    runtime = env.runtime
    entered, release = threading.Event(), threading.Event()
    guardian = runtime.auth.authenticate(
        runtime.auth.login("guardian-admin", PASSWORD)["access_token"]
    )

    @env.app.post("/api/v1/sample/revoke")
    def revoke():
        entered.set()
        assert release.wait(5)
        return runtime.auth.update_user(
            guardian,
            env.actor.id,
            role="operator",
            active=True,
            expected_version=1,
            request_key="queued-revocation",
        )

    held = observe_hold(runtime, monkeypatch)
    with client_for(env) as client, ThreadPoolExecutor(max_workers=2) as executor:
        revocation = executor.submit(client.post, "/api/v1/sample/revoke")
        assert entered.wait(3)
        quiesce = executor.submit(
            runtime.quiesce, str(uuid4()), access_token=env.admin["access_token"]
        )
        try:
            assert held.wait(3)
            assert not quiesce.done()
        finally:
            release.set()
        assert revocation.result(timeout=3).status_code == 200
        with pytest.raises(CoreError, match="SESSION_EXPIRED"):
            quiesce.result(timeout=3)
        assert runtime.maintenance.status()["state"] == "FAILED_HELD"
        assert_resources_held(runtime)
        assert client.get("/api/v1/users").status_code == 503


@pytest.mark.parametrize("busy", ["timer", "job"])
def test_busy_producer_timeout_keeps_resources_and_signals_both_before_join(make_runtime, busy):
    entered, release, wrote = threading.Event(), threading.Event(), threading.Event()
    runtime = None

    def timer(runtime):
        entered.set()
        assert release.wait(10)
        write(runtime)
        wrote.set()

    def job(context, payload):
        entered.set()
        assert release.wait(10)
        write(runtime)
        wrote.set()
        context.check_cancelled()

    env = make_runtime(
        manifest=ModuleManifest(
            "sample",
            "/sample",
            job_handlers={"sample.busy": JobHandler(job)},
            periodic_tasks={"sample.tick": PeriodicTask(timer, 1)} if busy == "timer" else {},
        )
    )
    runtime = env.runtime
    if busy == "job":
        runtime.jobs.submit(env.actor.id, "sample.busy", {}, "busy")
    with client_for(env) as client:
        try:
            assert entered.wait(3)
            expected = "PERIODIC_SHUTDOWN_TIMEOUT" if busy == "timer" else "JOB_SHUTDOWN_TIMEOUT"
            with pytest.raises(CoreError, match=expected):
                runtime.quiesce(
                    str(uuid4()), access_token=env.admin["access_token"], drain_timeout_seconds=1
                )
            assert runtime.periodic.stop_event.is_set() and runtime.runner.stop_event.is_set()
            assert runtime.maintenance.status()["state"] == "FAILED_HELD"
            assert_resources_held(runtime)
            assert client.get("/api/v1/users").status_code == 503
            assert client.get("/api/v1/health").status_code == 200
        finally:
            release.set()
        runtime.close()
        assert wrote.is_set() and value(runtime) == 1
        assert runtime.maintenance.status()["state"] == "CLOSED"


def test_http_drain_timeout_is_held_and_same_operation_can_finish_after_request(make_runtime):
    env = make_runtime()
    entered, release = threading.Event(), threading.Event()

    @env.app.post("/api/v1/sample/slow")
    def slow():
        entered.set()
        assert release.wait(5)
        write(env.runtime)
        return {"ok": True}

    with client_for(env) as client, ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(client.post, "/api/v1/sample/slow")
        assert entered.wait(3)
        operation_id = str(uuid4())
        try:
            with pytest.raises(CoreError, match="MAINTENANCE_DRAIN_TIMEOUT"):
                env.runtime.quiesce(
                    operation_id, access_token=env.admin["access_token"], drain_timeout_seconds=1
                )
            assert_resources_held(env.runtime)
            assert env.runtime.maintenance.status()["state"] == "FAILED_HELD"
        finally:
            release.set()
        assert response.result(timeout=3).status_code == 200
        assert (
            env.runtime.quiesce(operation_id, access_token=env.admin["access_token"])["state"]
            == "QUIESCED"
        )


def test_activation_failure_is_sanitized_held_and_never_reruns_partial_hook(make_runtime):
    hooks = []

    def fail(runtime):
        hooks.append("partial effect")
        write(runtime)
        raise RuntimeError("synthetic-private-error-must-not-leak")

    env = make_runtime(
        mode="dormant", manifest=ModuleManifest("sample", "/sample", on_startup=fail)
    )
    with client_for(env) as client:
        operation_id = str(uuid4())
        with pytest.raises(CoreError, match="MAINTENANCE_ACTIVATION_FAILED") as failed:
            env.runtime.activate(operation_id, access_token=env.admin["access_token"])
        assert "synthetic-private" not in repr(failed.value)
        assert env.runtime.maintenance.status()["state"] == "FAILED_HELD"
        assert_resources_held(env.runtime)
        assert value(env.runtime) == 1 and hooks == ["partial effect"]
        with pytest.raises(CoreError, match="MAINTENANCE_CONFLICT"):
            env.runtime.activate(operation_id, access_token=env.admin["access_token"])
        assert hooks == ["partial effect"]
        assert client.get("/api/v1/users").status_code == 503
    assert env.runtime.root._lock is None


def test_close_drains_admitted_health_denies_all_new_requests_and_retries_after_timeout(
    make_runtime,
    monkeypatch,
):
    env = make_runtime(mode="dormant")
    runtime = env.runtime
    entered, release = threading.Event(), threading.Event()
    original = runtime.auth.setup_required

    def slow_health():
        entered.set()
        assert release.wait(5)
        assert not runtime.writer._closed
        return original()

    monkeypatch.setattr(runtime.auth, "setup_required", slow_health)
    with client_for(env) as client, ThreadPoolExecutor(max_workers=1) as executor:
        health = executor.submit(client.get, "/api/v1/health")
        assert entered.wait(3)
        try:
            with pytest.raises(CoreError, match="MAINTENANCE_DRAIN_TIMEOUT"):
                runtime.close(drain_timeout_seconds=1)
            assert_resources_held(runtime)
            assert runtime.maintenance.status()["requests"] == 1
            for path in ("/api/v1/health", "/api/v1/auth/login", "/api/v1/users"):
                response = client.get(path)
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "RUNTIME_CLOSED"
        finally:
            release.set()
        assert health.result(timeout=3).status_code == 200
        runtime.close()
        runtime.close()
        assert runtime.root._lock is None and runtime.writer._closed
        assert runtime.maintenance.status()["state"] == "CLOSED"


@pytest.mark.parametrize("bad_id", ["", "not-a-uuid", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA", 12])
def test_maintenance_operation_identity_is_canonical_uuid_only(make_runtime, bad_id):
    env = make_runtime()
    for method in (env.runtime.activate, env.runtime.quiesce):
        with pytest.raises(CoreError, match="INVALID_MAINTENANCE_OPERATION"):
            method(bad_id, access_token=env.admin["access_token"])
    assert env.runtime.maintenance.status()["state"] == "ACTIVE"


@pytest.mark.parametrize("timeout", [True, 0, 301, float("nan"), float("inf"), 10**400])
def test_invalid_drain_deadline_cannot_freeze_runtime(make_runtime, timeout):
    env = make_runtime()
    with pytest.raises(CoreError, match="INVALID_MAINTENANCE_TIMEOUT"):
        env.runtime.quiesce(
            str(uuid4()), access_token=env.admin["access_token"], drain_timeout_seconds=timeout
        )
    assert env.runtime.maintenance.status()["state"] == "ACTIVE"
