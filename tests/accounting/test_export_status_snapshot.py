"""Real export publication and authenticated status share a coherent snapshot."""

import hashlib
import threading
import time
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.api import create_app
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import select


def key():
    return str(uuid4())


@pytest.fixture
def api(tmp_path):
    runtime = Runtime(
        tmp_path / "export-status-snapshot",
        initialize=True,
        modules=ModuleRegistry((module_manifest(),)),
    )
    admin_session = runtime.auth.setup("status-admin", "synthetic-status-admin-password")
    admin = runtime.auth.authenticate(admin_session["access_token"])
    actors, headers, users = {"admin": admin}, {}, {}
    common = {
        "X-App-Session": "synthetic-export-status-app-session-0123456",
        "Origin": "http://tauri.localhost",
    }
    headers["admin"] = common | {"Authorization": "Bearer " + admin_session["access_token"]}
    for role in ("owner", "other"):
        users[role] = runtime.auth.create_user(
            admin,
            username="status-" + role,
            password="synthetic-status-operator-password",
            role="operator",
            request_key=key(),
        )
        session = runtime.auth.login("status-" + role, "synthetic-status-operator-password")
        actors[role] = runtime.auth.authenticate(session["access_token"])
        headers[role] = common | {"Authorization": "Bearer " + session["access_token"]}
    service = AccountingService(runtime)
    book = service.create_book(
        admin, "Synthetic status book", [{"id": "code", "name": "Code", "kind": "text"}], {}, key()
    )
    service.create_row(admin, book["id"], {"code": "SYNTHETIC-EXPORT-STATUS"}, key())
    app = create_app(runtime, common["X-App-Session"], port=48958)
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:48958", raise_server_exceptions=False
        ) as client:
            yield {
                "runtime": runtime,
                "client": client,
                "actors": actors,
                "headers": headers,
                "users": users,
                "book": book,
                "common": common,
            }
    finally:
        runtime.close()


def start_export(api):
    response = api["client"].post(
        f"/api/v1/accounting/books/{api['book']['id']}/exports",
        headers=api["headers"]["owner"],
        json={"format": "csv", "request_key": key()},
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_completed(status, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = status(job_id)
        if current["state"] in {"COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"}:
            assert current["state"] == "COMPLETED", current.get("error_code")
            return current
        time.sleep(0.01)
    pytest.fail("real export worker did not complete")


def get_status(api, job_id, role="owner"):
    return api["client"].get(f"/api/v1/accounting/exports/{job_id}", headers=api["headers"][role])


def assert_no_status_leak(response, expected, code):
    assert response.status_code == expected, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert set(body) == {"error", "request_id"}
    assert not any(
        name in body for name in ("file_id", "actor", "state", "kind", "counts", "checkpoint")
    )


def test_export_status_race_returns_one_snapshot_and_next_poll_has_real_file(api, monkeypatch):
    runtime = api["runtime"]
    entered_put, release_put = threading.Event(), threading.Event()
    original_put, original_status = runtime.files.put, runtime.jobs.status

    def paused_put(*args, **kwargs):
        if kwargs.get("original_name", "").startswith("accounting-derived-exact-"):
            entered_put.set()
            assert release_put.wait(10), "test did not release real export file storage"
        return original_put(*args, **kwargs)

    monkeypatch.setattr(runtime.files, "put", paused_put)
    route_calls = []
    try:
        started = start_export(api)
        job_id = started["job_id"]
        assert entered_put.wait(10)
        assert original_status(job_id)["state"] == "RUNNING"
        with runtime.reader() as connection:
            assert (
                connection.execute(
                    select(s.exports.c.file_id).where(s.exports.c.job_id == job_id)
                ).scalar_one()
                is None
            )

        def finish_worker_before_reading_status(*args, **kwargs):
            # Forward the public method's arguments unchanged, supporting both
            # the old signature and the approved caller-connection extension.
            if threading.current_thread() is runtime.runner.thread:
                return original_status(*args, **kwargs)
            connection = kwargs.get("connection")
            assert connection is not None, "export status must borrow its domain snapshot"
            assert connection.in_transaction() and not connection.closed
            transaction = connection.get_transaction()
            route_calls.append(True)
            release_put.set()
            wait_completed(original_status, job_id)
            result = original_status(*args, **kwargs)
            assert connection.get_transaction() is transaction
            assert connection.in_transaction() and not connection.closed
            return result

        monkeypatch.setattr(runtime.jobs, "status", finish_worker_before_reading_status)
        response = get_status(api, job_id)
        assert response.status_code == 200, response.text
        observed = response.json()
        assert route_calls
        assert observed["state"] == "RUNNING"
        assert observed["file_id"] is None
        monkeypatch.setattr(runtime.jobs, "status", original_status)
        fresh = get_status(api, job_id)
        assert fresh.status_code == 200
        final = fresh.json()
        assert final["state"] == "COMPLETED"
        assert str(UUID(final["file_id"])) == final["file_id"]
        with runtime.reader() as connection:
            persisted = connection.execute(
                select(s.exports.c.file_id).where(s.exports.c.job_id == job_id)
            ).scalar_one()
        assert final["file_id"] == persisted
        downloaded = api["client"].get(
            f"/api/v1/files/{persisted}/content", headers=api["headers"]["owner"]
        )
        assert downloaded.status_code == 200
        assert b"SYNTHETIC-EXPORT-STATUS" in downloaded.content
        assert hashlib.sha256(downloaded.content).hexdigest() == runtime.files.get(persisted).sha256
    finally:
        release_put.set()
        monkeypatch.setattr(runtime.jobs, "status", original_status)


def test_owner_and_admin_read_export_status_other_actor_and_unauthenticated_do_not(api):
    started = start_export(api)
    wait_completed(api["runtime"].jobs.status, started["job_id"])
    owner = get_status(api, started["job_id"])
    admin = get_status(api, started["job_id"], "admin")
    assert owner.status_code == admin.status_code == 200
    assert owner.json()["state"] == admin.json()["state"] == "COMPLETED"
    assert owner.json()["file_id"] == admin.json()["file_id"]
    assert_no_status_leak(get_status(api, started["job_id"], "other"), 403, "PERMISSION_DENIED")
    unauthenticated = api["client"].get(
        f"/api/v1/accounting/exports/{started['job_id']}", headers=api["common"]
    )
    assert unauthenticated.status_code == 401
    assert "file_id" not in unauthenticated.json()


def test_request_actor_revoked_before_export_snapshot_is_reauthorized(api, monkeypatch):
    runtime = api["runtime"]
    started = start_export(api)
    wait_completed(runtime.jobs.status, started["job_id"])
    original_reader = runtime.reader
    revoked = threading.Event()

    @contextmanager
    def revoke_after_request_auth_before_snapshot():
        with original_reader() as connection:
            if not revoked.is_set():
                runtime.auth.update_user(
                    api["actors"]["admin"],
                    api["actors"]["owner"].id,
                    role="operator",
                    active=False,
                    expected_version=api["users"]["owner"]["version"],
                    request_key=key(),
                )
                revoked.set()
            yield connection

    monkeypatch.setattr(runtime, "reader", revoke_after_request_auth_before_snapshot)
    response = get_status(api, started["job_id"])
    assert revoked.is_set()
    assert_no_status_leak(response, 401, "SESSION_EXPIRED")


def test_unknown_and_other_namespace_jobs_are_not_export_status_oracles(api, monkeypatch):
    runtime = api["runtime"]
    actor = api["actors"]["other"]
    foreign = runtime.jobs.submit(
        actor.id,
        "foundation.sample",
        {},
        key(),
        authorize=lambda connection: runtime.auth.authorize(connection, actor, "jobs.write"),
    )["job_id"]
    original_status = runtime.jobs.status
    wait_completed(original_status, foreign)
    route_calls = []

    def no_foreign_status_lookup(*args, **kwargs):
        if threading.current_thread() is runtime.runner.thread:
            return original_status(*args, **kwargs)
        route_calls.append(True)
        pytest.fail("unknown export route queried another job's status")

    monkeypatch.setattr(runtime.jobs, "status", no_foreign_status_lookup)
    for job_id in (key(), foreign):
        assert_no_status_leak(get_status(api, job_id), 404, "EXPORT_NOT_FOUND")
    assert not route_calls
