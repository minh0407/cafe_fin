import threading
import time

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.jobs import JOBS, JobHandler
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import func, select


@pytest.fixture
def boundary_runtime(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def privileged(context, payload):
        assert payload == {"snapshot_id": "confirmed-synthetic-snapshot"}
        entered.set()
        assert release.wait(5)
        context.commit_chunk(
            "confirmed-effect",
            payload,
            checkpoint={"next": 1},
            counts={"done": 1},
            phase="sample.privileged",
            effect=lambda conn: {"confirmed": True},
        )
        context.finalize(lambda conn: {"complete": True})

    manifest = ModuleManifest(
        "sample",
        "/sample",
        permissions=("sample.read", "sample.write"),
        job_handlers={"sample.privileged": JobHandler(privileged, resumable=True)},
    )
    runtime = Runtime(
        tmp_path / "Job boundaries", initialize=True, modules=ModuleRegistry((manifest,))
    )
    admin_session = runtime.auth.setup("boundary-admin", "synthetic-boundary-password")
    admin = runtime.auth.authenticate(admin_session["access_token"])
    runtime.auth.create_user(
        admin,
        username="boundary-operator",
        password="synthetic-operator-password",
        role="operator",
        request_key="boundary-operator",
    )
    operator_session = runtime.auth.login("boundary-operator", "synthetic-operator-password")
    token, port = "synthetic-boundary-session-0123456789abcdef", 48953
    common = {"X-App-Session": token, "Origin": "http://tauri.localhost"}
    headers = {
        "admin": common | {"Authorization": "Bearer " + admin_session["access_token"]},
        "operator": common | {"Authorization": "Bearer " + operator_session["access_token"]},
    }
    app = create_app(runtime, token, port=port)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{port}") as client:
            yield runtime, client, headers, admin, entered, release
    finally:
        release.set()
        runtime.close()


def submit_trusted(runtime, admin):
    # Represents a module endpoint after its own typed validation/confirmation and
    # permission checks; raw public /jobs is deliberately not that boundary.
    return runtime.jobs.submit(
        admin.id,
        "sample.privileged",
        {"snapshot_id": "confirmed-synthetic-snapshot"},
        "trusted-module-confirm",
        authorize=lambda conn: runtime.auth.authorize(conn, admin, "core.manage"),
    )["job_id"]


def wait_completed(runtime, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = runtime.jobs.status(job_id)
        if status["state"] == "COMPLETED":
            return status
        time.sleep(0.01)
    pytest.fail(f"job did not complete: {runtime.jobs.status(job_id)}")


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_registered_module_jobs_cannot_use_generic_mutation_endpoints(boundary_runtime, role):
    runtime, client, headers, admin, entered, release = boundary_runtime
    with runtime.reader() as conn:
        before = conn.execute(select(func.count()).select_from(JOBS)).scalar_one()
    response = client.post(
        "/api/v1/jobs",
        headers=headers[role],
        json={
            "kind": "sample.privileged",
            "payload": {"skip_validation": True},
            "request_key": "raw-bypass",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "MODULE_JOB_ENDPOINT_REQUIRED"
    assert not entered.is_set()
    with runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(JOBS)).scalar_one() == before

    job_id = submit_trusted(runtime, admin)
    try:
        assert entered.wait(5)
        before_status = runtime.jobs.status(job_id)
        for action in ("cancel", "resume"):
            response = client.post(f"/api/v1/jobs/{job_id}/{action}", headers=headers[role])
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "MODULE_JOB_ENDPOINT_REQUIRED"
        assert runtime.jobs.status(job_id) == before_status
    finally:
        release.set()
    assert wait_completed(runtime, job_id)["counts"] == {"done": 1}


def test_module_status_requires_module_read_but_operator_can_use_foundation_proof(boundary_runtime):
    runtime, client, headers, admin, entered, release = boundary_runtime
    job_id = submit_trusted(runtime, admin)
    try:
        assert entered.wait(5)
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers["operator"])
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers["admin"])
        assert response.status_code == 200
        assert response.json()["kind"] == "sample.privileged"

        # The single worker is still inside the module handler, keeping this proof job
        # WAITING so cancel/resume is deterministic rather than a race with completion.
        response = client.post(
            "/api/v1/jobs",
            headers=headers["operator"],
            json={"kind": "foundation.sample", "payload": {}, "request_key": "operator-foundation"},
        )
        assert response.status_code == 200
        proof_id = response.json()["job_id"]
        response = client.post(f"/api/v1/jobs/{proof_id}/cancel", headers=headers["operator"])
        assert response.status_code == 200
        assert response.json()["state"] == "CANCELLED"
        response = client.post(f"/api/v1/jobs/{proof_id}/resume", headers=headers["operator"])
        assert response.status_code == 200
        assert response.json()["state"] == "WAITING"
        assert (
            client.get(f"/api/v1/jobs/{proof_id}", headers=headers["operator"]).status_code == 200
        )
    finally:
        release.set()
    assert wait_completed(runtime, job_id)["counts"] == {"done": 1}
    assert wait_completed(runtime, proof_id)["counts"] == {"steps": 3}
