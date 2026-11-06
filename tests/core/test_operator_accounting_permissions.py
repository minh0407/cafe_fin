"""One local Operator owns independent accounting without an Admin approval step."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.db import AUDIT
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_operations import MaintenanceOperations
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import select

PASSWORD = "synthetic-operator-accounting-password"
COLUMNS = [
    {"id": "code", "name": "Mã", "kind": "text", "required": True},
    {"id": "day", "name": "Ngày", "kind": "date", "required": True},
    {"id": "amount", "name": "Thu", "kind": "money", "required": True, "precision": 19},
]
SEMANTICS = {"date_column": "day", "income_column": "amount"}


@pytest.fixture
def local_api(tmp_path):
    # Use production registration, including records/contracts/reporting, so a
    # permission expansion cannot pass by omitting the protected modules.
    runtime = Runtime(tmp_path / "operator-accounting", initialize=True)
    port = 48973
    common = {
        "X-App-Session": "synthetic-operator-accounting-app-0123456789",
        "Origin": "http://tauri.localhost",
    }
    app = create_app(runtime, common["X-App-Session"], port=port)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{port}") as client:
            setup = client.post(
                "/api/v1/auth/setup",
                headers=common,
                json={"username": "local-admin", "password": PASSWORD},
            )
            assert setup.status_code == 200, setup.text
            admin = common | {"Authorization": "Bearer " + setup.json()["access_token"]}
            created = client.post(
                "/api/v1/users",
                headers=admin,
                json={
                    "username": "local-operator",
                    "password": PASSWORD,
                    "role": "operator",
                    "request_key": "create-local-operator",
                },
            )
            assert created.status_code == 200, created.text
            login = client.post(
                "/api/v1/auth/login",
                headers=common,
                json={"username": "local-operator", "password": PASSWORD},
            )
            assert login.status_code == 200, login.text
            session = login.json()
            assert {"records", "accounting", "contracts", "reporting"} <= {
                module.id for module in runtime.modules.ordered()
            }
            yield SimpleNamespace(
                runtime=runtime,
                client=client,
                admin=admin,
                operator=common | {"Authorization": "Bearer " + session["access_token"]},
                token=session["access_token"],
                user=created.json(),
                permissions=session["user"]["permissions"],
            )
    finally:
        runtime.close()


def request(env, method, path, *, role="operator", expected=200, **kwargs):
    response = env.client.request(method, "/api/v1" + path, headers=getattr(env, role), **kwargs)
    assert response.status_code == expected, response.text
    return response.json()


def book_payload():
    return {
        "name": "Sổ độc lập của Operator",
        "columns": COLUMNS,
        "semantics": SEMANTICS,
        "request_key": "operator-book",
    }


def records_counts(runtime):
    with runtime.reader() as conn:
        tables = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'records_%'"
        ).scalars()
        counts = {
            name: conn.exec_driver_sql(f'SELECT COUNT(*) FROM "{name}"').scalar_one()
            for name in tables
        }
    assert counts  # Production records tables must exist; avoid a vacuous check.
    return counts


def test_operator_book_schema_row_lifecycle_keeps_versions_receipts_audit_and_crm_independence(
    local_api,
):
    env = local_api
    before = records_counts(env.runtime)
    book = request(env, "POST", "/accounting/books", json=book_payload())
    assert book["created_by"] == env.user["id"] and book["version"] == 1
    assert request(env, "POST", "/accounting/books", json=book_payload()) == book
    schema = {
        "expected_version": 1,
        "columns": COLUMNS + [{"id": "note", "name": "Ghi chú", "kind": "text"}],
        "semantics": SEMANTICS,
        "request_key": "operator-schema",
    }
    configured = request(env, "PATCH", f"/accounting/books/{book['id']}/schema", json=schema)
    assert configured["version"] == 2 and configured["schema_revision"] == 2
    assert (
        request(env, "PATCH", f"/accounting/books/{book['id']}/schema", json=schema) == configured
    )
    stale_schema = request(
        env,
        "PATCH",
        f"/accounting/books/{book['id']}/schema",
        expected=409,
        json=schema | {"request_key": "stale-schema"},
    )
    assert stale_schema["error"]["code"] == "VERSION_CONFLICT"
    create = {
        "values": {"code": "0001", "day": "2026-11-07", "amount": "15000000.00"},
        "request_key": "operator-row",
    }
    row = request(env, "POST", f"/accounting/books/{book['id']}/rows", json=create)
    assert request(env, "POST", f"/accounting/books/{book['id']}/rows", json=create) == row
    conflict = request(
        env,
        "POST",
        f"/accounting/books/{book['id']}/rows",
        expected=409,
        json=create | {"values": create["values"] | {"code": "0002"}},
    )
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    row_path = f"/accounting/rows/{row['id']}"
    edited = request(
        env,
        "PATCH",
        row_path,
        json={
            "expected_version": 1,
            "values": create["values"] | {"amount": "15000000.25", "note": "Đã sửa"},
            "request_key": "operator-row-edit",
        },
    )
    assert edited["version"] == 2 and edited["values"]["amount"] == "15000000.25"
    stale = request(
        env,
        "POST",
        row_path + "/delete",
        expected=409,
        json={"expected_version": 1, "request_key": "stale-delete"},
    )
    assert stale["error"]["code"] == "VERSION_CONFLICT"
    deleted = request(
        env,
        "POST",
        row_path + "/delete",
        json={"expected_version": 2, "request_key": "operator-row-delete"},
    )
    assert deleted["version"] == 3 and deleted["deleted_at"] is not None
    restore = {"expected_version": 3, "request_key": "operator-row-restore"}
    restored = request(env, "POST", row_path + "/restore", json=restore)
    assert restored["version"] == 4 and restored["deleted_at"] is None
    assert request(env, "POST", row_path + "/restore", json=restore) == restored
    assert request(env, "GET", row_path) == restored
    with env.runtime.reader() as conn:
        audit = (
            conn.execute(select(AUDIT).where(AUDIT.c.entity_id.in_((book["id"], row["id"]))))
            .mappings()
            .all()
        )
    assert len(audit) == 6  # Replays and rejected stale commands add no effects.
    assert {entry["actor"] for entry in audit} == {env.user["id"]}
    assert {(entry["entity"], entry["action"]) for entry in audit} == {
        ("accounting_book", "create"),
        ("accounting_book", "schema"),
        ("accounting_row", "create"),
        ("accounting_row", "update"),
        ("accounting_row", "delete"),
        ("accounting_row", "restore"),
    }
    assert sorted(
        json.loads(entry["after_json"])["version"]
        for entry in audit
        if entry["entity"] == "accounting_row"
    ) == [1, 2, 3, 4]
    assert records_counts(env.runtime) == before


def test_operator_accounting_rights_do_not_grant_admin_or_native_root_authority(local_api):
    env = local_api
    assert {"accounting.configure", "accounting.restore"} <= set(env.permissions)
    assert "core.manage" not in env.permissions and "contracts.templates" not in env.permissions
    for path in ("/users", "/settings/data-root", "/reporting/settings"):
        assert request(env, "GET", path, expected=403)["error"]["code"] == "PERMISSION_DENIED"
        request(env, "GET", path, role="admin")
    account = request(
        env,
        "POST",
        "/users",
        expected=403,
        json={
            "username": "forbidden-admin",
            "password": PASSWORD,
            "role": "admin",
            "request_key": "operator-cannot-admin",
        },
    )
    assert account["error"]["code"] == "PERMISSION_DENIED"
    template = request(env, "GET", "/contracts/templates")["items"][0]
    forbidden = request(
        env,
        "PATCH",
        f"/contracts/templates/{template['id']}",
        expected=403,
        json={
            "expected_version": template["version"],
            "title": "Forbidden template edit",
            "body": template["body"],
            "request_key": "operator-cannot-template",
        },
    )
    assert forbidden["error"]["code"] == "PERMISSION_DENIED"
    settings = request(
        env,
        "PUT",
        "/reporting/settings",
        expected=403,
        json={"expected_version": 0, "request_key": "operator-cannot-schedule"},
    )
    assert settings["error"]["code"] == "PERMISSION_DENIED"
    maintenance = MaintenanceOperations(env.runtime, generation=str(uuid4()))
    with pytest.raises(CoreError) as denied:
        maintenance.authorize_source_identity(env.token)
    assert denied.value.code == "PERMISSION_DENIED" and denied.value.status == 403
    assert maintenance.authorize_open_reports(env.token)["allowed"] is True


def test_revoked_operator_cannot_replay_completed_configuration_or_restore_commands(local_api):
    env = local_api
    book = request(env, "POST", "/accounting/books", json=book_payload())
    schema = {
        "expected_version": 1,
        "columns": COLUMNS,
        "semantics": SEMANTICS,
        "request_key": "operator-schema-before-revoke",
    }
    request(env, "PATCH", f"/accounting/books/{book['id']}/schema", json=schema)
    row = request(
        env,
        "POST",
        f"/accounting/books/{book['id']}/rows",
        json={
            "values": {"code": "revoked", "day": "2026-11-07", "amount": "1.00"},
            "request_key": "row-before-revoke",
        },
    )
    row_path = f"/accounting/rows/{row['id']}"
    deleted = request(
        env,
        "POST",
        row_path + "/delete",
        json={"expected_version": row["version"], "request_key": "delete-before-revoke"},
    )
    restore = {"expected_version": deleted["version"], "request_key": "restore-before-revoke"}
    request(env, "POST", row_path + "/restore", json=restore)
    request(
        env,
        "PATCH",
        f"/users/{env.user['id']}",
        role="admin",
        json={
            "role": "operator",
            "active": False,
            "expected_version": env.user["version"],
            "request_key": "disable-operator",
        },
    )
    for method, path, payload in (
        ("POST", "/accounting/books", book_payload()),
        ("PATCH", f"/accounting/books/{book['id']}/schema", schema),
        ("POST", row_path + "/restore", restore),
    ):
        response = request(env, method, path, expected=401, json=payload)
        assert response["error"]["code"] == "SESSION_EXPIRED"
