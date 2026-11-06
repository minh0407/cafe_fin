"""Real auth, files and HTTP boundaries for generic file/module-job reads."""

import hashlib
from contextlib import contextmanager
from uuid import UUID

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import AUDIT
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient

TOKEN = "synthetic-read-scopes-session-0123456789abcdef"
PAYLOAD = b"synthetic private workbook original\x00\xff"


@pytest.fixture
def read_runtime(tmp_path, request):
    def module_job(context, payload):
        context.commit_chunk(
            "read-scope-proof",
            payload,
            checkpoint={"source_file_id": payload["source_file_id"]},
            counts={"done": 1},
            phase="accounting.readscope",
            effect=lambda conn: {"done": 1},
        )
        context.finalize(lambda conn: {"complete": True})

    modules = ()
    if getattr(request, "param", True):
        modules = (
            ModuleManifest(
                "accounting",
                "/accounting",
                permissions=("accounting.read", "accounting.write"),
                job_handlers={"accounting.readscope": JobHandler(module_job)},
            ),
        )
    runtime = Runtime(
        tmp_path / "Read scopes dữ liệu tổng hợp",
        initialize=True,
        modules=ModuleRegistry(modules),
    )
    sessions = {"admin": runtime.auth.setup("scope-admin", "synthetic-admin-password")}
    principals = {"admin": runtime.auth.authenticate(sessions["admin"]["access_token"])}
    accounts = {}
    for name in ("owner", "stranger"):
        accounts[name] = runtime.auth.create_user(
            principals["admin"],
            username=f"scope-{name}",
            password=f"synthetic-{name}-password",
            role="operator",
            request_key=f"create-{name}",
        )
        sessions[name] = runtime.auth.login(f"scope-{name}", f"synthetic-{name}-password")
        principals[name] = runtime.auth.authenticate(sessions[name]["access_token"])
    common = {"X-App-Session": TOKEN, "Origin": "http://tauri.localhost"}
    headers = {
        name: common | {"Authorization": "Bearer " + session["access_token"]}
        for name, session in sessions.items()
    }
    try:
        with TestClient(
            create_app(runtime, TOKEN, port=48959), base_url="http://127.0.0.1:48959"
        ) as client:
            uploaded = client.post(
                "/api/v1/files",
                headers=headers["owner"]
                | {
                    "X-File-Name": "private-synthetic-source.xlsm",
                    "X-Request-Key": "scope-original",
                    "Content-Type": "application/octet-stream",
                },
                content=PAYLOAD,
            )
            assert uploaded.status_code == 200, uploaded.text
            yield runtime, client, headers, principals, accounts, uploaded.json()
    finally:
        runtime.close()


def revoke_owner(runtime, principals, accounts):
    runtime.auth.update_user(
        principals["admin"],
        accounts["owner"]["id"],
        role="operator",
        active=False,
        expected_version=accounts["owner"]["version"],
        request_key="revoke-owner",
    )


def submit_module_job(runtime, principal, file_id):
    return runtime.jobs.submit(
        principal.id,
        "accounting.readscope",
        {"source_file_id": file_id},
        "owner-module-job",
        authorize=lambda conn: runtime.auth.authorize(conn, principal, "accounting.write"),
    )["job_id"]


def test_owner_and_admin_can_read_original_metadata_and_verified_bytes(read_runtime):
    _, client, headers, _, _, stored = read_runtime
    assert str(UUID(stored["id"])) == stored["id"]
    for role in ("owner", "admin"):
        metadata = client.get(f"/api/v1/files/{stored['id']}", headers=headers[role])
        assert metadata.status_code == 200, metadata.text
        assert metadata.json() == stored
        content = client.get(f"/api/v1/files/{stored['id']}/content", headers=headers[role])
        assert content.status_code == 200, content.text
        assert content.content == PAYLOAD
        assert content.headers["x-content-sha256"] == hashlib.sha256(PAYLOAD).hexdigest()


def test_file_id_and_baseline_permission_do_not_share_another_operators_file(
    read_runtime, monkeypatch
):
    runtime, client, headers, principals, _, stored = read_runtime
    assert "files.read" in principals["stranger"].permissions
    opened = []
    original_read = runtime.files.read

    @contextmanager
    def observe_open(file_id):
        opened.append(file_id)
        with original_read(file_id) as source:
            yield source

    monkeypatch.setattr(runtime.files, "read", observe_open)
    for suffix in ("", "/content"):
        response = client.get(f"/api/v1/files/{stored['id']}{suffix}", headers=headers["stranger"])
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
        assert "x-content-sha256" not in response.headers
        assert stored["original_name"] not in response.text
        assert PAYLOAD not in response.content
    assert opened == []


@pytest.mark.parametrize("provenance", ["missing", "ambiguous"])
def test_missing_or_ambiguous_create_owner_fails_closed_for_owner_and_admin(
    read_runtime, provenance
):
    runtime, client, headers, principals, _, stored = read_runtime

    def change_audit(conn):
        if provenance == "missing":
            conn.execute(
                AUDIT.delete().where(
                    AUDIT.c.entity == "core_file", AUDIT.c.entity_id == stored["id"]
                )
            )
        else:
            AuditService.record(
                conn,
                actor=principals["owner"].id,
                entity="core_file",
                entity_id=stored["id"],
                action="CREATE",
                after=stored,
            )

    runtime.writer.run(change_audit)
    for role in ("owner", "admin"):
        for suffix in ("", "/content"):
            response = client.get(f"/api/v1/files/{stored['id']}{suffix}", headers=headers[role])
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"
            assert "x-content-sha256" not in response.headers


def test_file_scope_uses_one_canonical_lowercase_uuid_identity(read_runtime):
    _, client, headers, _, _, stored = read_runtime
    aliases = {stored["id"].upper(), UUID(stored["id"]).hex, "{" + stored["id"] + "}"}
    aliases.discard(stored["id"])
    for alias in aliases:
        for suffix in ("", "/content"):
            response = client.get(f"/api/v1/files/{alias}{suffix}", headers=headers["owner"])
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "FILE_ID_INVALID"


def test_public_file_helper_checks_scope_on_the_callers_authorized_connection(read_runtime):
    runtime, _, _, principals, _, stored = read_runtime
    with runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        for role in ("owner", "admin", "stranger"):
            principal = runtime.auth.authorize(conn, principals[role], "accounting.write")
            if role == "stranger":
                with pytest.raises(CoreError, match="PERMISSION_DENIED"):
                    runtime.files.require_owner_or_admin(conn, principal, stored["id"])
            else:
                runtime.files.require_owner_or_admin(conn, principal, stored["id"])
                assert runtime.files.get(stored["id"], connection=conn).id == stored["id"]


@pytest.mark.parametrize("resource", ["metadata", "content", "module-job"])
def test_revocation_after_request_authentication_is_rechecked_before_read(
    read_runtime, monkeypatch, resource
):
    runtime, client, headers, principals, accounts, stored = read_runtime
    path = f"/api/v1/files/{stored['id']}"
    if resource == "content":
        path += "/content"
    elif resource == "module-job":
        path = "/api/v1/jobs/" + submit_module_job(runtime, principals["owner"], stored["id"])
    authenticate = runtime.auth.authenticate
    captured = []

    def revoke_after_authentication(token):
        principal = authenticate(token)
        if principal.id == principals["owner"].id and not captured:
            captured.append(principal)
            revoke_owner(runtime, principals, accounts)
        return principal

    monkeypatch.setattr(runtime.auth, "authenticate", revoke_after_authentication)
    response = client.get(path, headers=headers["owner"])
    assert len(captured) == 1
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    assert "x-content-sha256" not in response.headers
    assert PAYLOAD not in response.content


def test_revocation_during_file_verification_closes_source_before_response_headers(
    read_runtime, monkeypatch
):
    runtime, client, headers, principals, accounts, stored = read_runtime
    original_read = runtime.files.read
    sources = []

    @contextmanager
    def revoke_during_read(file_id):
        with original_read(file_id) as source:
            sources.append(source)
            revoke_owner(runtime, principals, accounts)
            yield source

    monkeypatch.setattr(runtime.files, "read", revoke_during_read)
    response = client.get(f"/api/v1/files/{stored['id']}/content", headers=headers["owner"])
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    assert "x-content-sha256" not in response.headers
    assert PAYLOAD not in response.content
    assert len(sources) == 1 and sources[0].closed


def test_module_job_read_permission_also_requires_same_actor_or_admin(read_runtime):
    runtime, client, headers, principals, _, stored = read_runtime
    assert "accounting.read" in principals["stranger"].permissions
    job_id = submit_module_job(runtime, principals["owner"], stored["id"])
    for role in ("owner", "admin"):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers[role])
        assert response.status_code == 200, response.text
        assert response.json()["actor"] == principals["owner"].id
        assert response.json()["kind"] == "accounting.readscope"
    response = client.get(f"/api/v1/jobs/{job_id}", headers=headers["stranger"])
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert stored["id"] not in response.text


@pytest.mark.parametrize("read_runtime", [False], indirect=True)
def test_foundation_proof_without_registered_modules_keeps_existing_read_behavior(read_runtime):
    runtime, client, headers, principals, _, _ = read_runtime
    assert runtime.modules.ordered() == ()
    response = client.post(
        "/api/v1/jobs",
        headers=headers["owner"],
        json={"kind": "foundation.sample", "payload": {}, "request_key": "foundation-proof"},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    for role in ("owner", "admin", "stranger"):
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers[role])
        assert response.status_code == 200, response.text
        assert response.json()["actor"] == principals["owner"].id
        assert response.json()["kind"] == "foundation.sample"
    response = client.post(
        "/api/v1/jobs",
        headers=headers["owner"],
        json={"kind": "foundation.unregistered", "payload": {}, "request_key": "unknown"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_JOB"
