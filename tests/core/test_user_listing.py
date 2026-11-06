"""Admin account pagination/filtering through real auth, HTTP and SQLite snapshots."""

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.auth import USERS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import event, select

TOKEN = "synthetic-local-accounts-session-0123456789abcdef"
PASSWORD = "synthetic-local-accounts-password"
FIELDS = {"id", "username", "role", "version", "active"}


@pytest.fixture
def accounts_api(tmp_path):
    runtime = Runtime(
        tmp_path / "Tài khoản local tổng hợp", initialize=True, modules=ModuleRegistry()
    )
    common = {"X-App-Session": TOKEN, "Origin": "http://tauri.localhost"}
    app = create_app(runtime, TOKEN, port=48960)
    try:
        with TestClient(app, base_url="http://127.0.0.1:48960") as client:
            setup = client.post(
                "/api/v1/auth/setup",
                headers=common,
                json={"username": "account-admin", "password": PASSWORD},
            )
            assert setup.status_code == 200, setup.text
            headers = {
                "admin": common | {"Authorization": "Bearer " + setup.json()["access_token"]}
            }
            users = {
                "admin": {
                    key: value for key, value in setup.json()["user"].items() if key in FIELDS
                }
            }
            users["admin"]["active"] = True
            for label, username, role in (
                ("backup", "backup-admin", "admin"),
                ("operator", "entry-operator", "operator"),
            ):
                created = create(client, headers["admin"], username, role)
                users[label] = created
                login = client.post(
                    "/api/v1/auth/login",
                    headers=common,
                    json={"username": username, "password": PASSWORD},
                )
                assert login.status_code == 200, login.text
                headers[label] = common | {
                    "Authorization": "Bearer " + login.json()["access_token"]
                }
            yield runtime, client, common, headers, users
    finally:
        runtime.close()


def create(client, headers, username, role="operator"):
    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": username,
            "password": PASSWORD,
            "role": role,
            "request_key": "create-" + username,
        },
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == FIELDS
    return response.json()


def listing(client, headers, **params):
    response = client.get("/api/v1/users", headers=headers, params=params)
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"items", "total", "page", "page_size"}
    assert all(set(item) == FIELDS for item in result["items"])
    assert "password_hash" not in response.text and "$argon2" not in response.text
    assert PASSWORD not in response.text
    return result


def test_admin_listing_is_public_stably_paged_and_literal_search_precedes_pagination(accounts_api):
    _, client, _, headers, _ = accounts_api
    names = ["literal%name", "literal_name", "literal\\name", "literalXname", "Đắk_user"]
    for username in names:
        create(client, headers["admin"], username)
    all_users = listing(client, headers["admin"], page_size=500)
    assert all_users["total"] == 8
    expected = sorted(all_users["items"], key=lambda row: (row["username"], row["id"]))
    assert all_users["items"] == expected
    combined = []
    for page in range(1, 5):
        result = listing(client, headers["admin"], page=page, page_size=2)
        assert (result["total"], result["page"], result["page_size"]) == (8, page, 2)
        combined.extend(result["items"])
    assert combined == expected
    empty = listing(client, headers["admin"], page=5, page_size=2)
    assert empty["total"] == 8 and empty["items"] == []
    huge_page = listing(client, headers["admin"], page=10**30, page_size=500)
    assert huge_page["total"] == 8 and huge_page["items"] == []
    for search, expected_names in (
        ("%", {"literal%name"}),
        ("_", {"literal_name", "Đắk_user"}),
        ("\\", {"literal\\name"}),
        ("Đắk", {"Đắk_user"}),
        ("ACCOUNT-ADMIN", {"account-admin"}),
    ):
        result = listing(client, headers["admin"], search=search)
        assert result["total"] == len(expected_names)
        assert {row["username"] for row in result["items"]} == expected_names
    filtered = listing(client, headers["admin"], search="literal", page=2, page_size=1)
    assert filtered["total"] == 4
    assert filtered["items"][0]["username"] == sorted(names[:4])[1]


def test_listing_requires_local_login_and_current_admin_role(accounts_api):
    _, client, common, headers, _ = accounts_api
    response = client.get("/api/v1/users", headers=common)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "LOGIN_REQUIRED"
    response = client.get("/api/v1/users", headers=headers["operator"])
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert "items" not in response.json()


def test_role_and_active_filters_keep_disabled_accounts_visible_in_default_listing(accounts_api):
    _, client, _, headers, users = accounts_api
    disabled = client.patch(
        "/api/v1/users/" + users["operator"]["id"],
        headers=headers["admin"],
        json={
            "role": "operator",
            "active": False,
            "expected_version": 1,
            "request_key": "disable-operator",
        },
    )
    assert disabled.status_code == 200, disabled.text
    result = listing(client, headers["admin"], active=False)
    assert result["items"] == [disabled.json()] and result["total"] == 1
    assert listing(client, headers["admin"])["total"] == 3
    admins = listing(client, headers["admin"], role="admin", active=True)
    assert admins["total"] == 2 and all(row["role"] == "admin" for row in admins["items"])
    assert listing(client, headers["admin"], role="admin", active=False)["items"] == []


def test_listing_query_bounds_and_service_validation_do_not_change_users(accounts_api):
    runtime, client, _, headers, _ = accounts_api
    with runtime.reader() as conn:
        before = conn.execute(select(USERS)).all()
    for params in (
        {"page": 0},
        {"page": -1},
        {"page_size": 0},
        {"page_size": 501},
        {"search": "x" * 129},
        {"role": "superuser"},
        {"active": "not-a-bool"},
    ):
        response = client.get("/api/v1/users", headers=headers["admin"], params=params)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    admin = runtime.auth.authenticate(headers["admin"]["Authorization"][7:])
    for params in (
        {"page": True},
        {"page_size": 1.0},
        {"search": None},
        {"active": 1},
        {"role": False},
    ):
        with pytest.raises(CoreError):
            runtime.auth.list_users(admin, **params)
    with runtime.reader() as conn:
        assert conn.execute(select(USERS)).all() == before


@pytest.mark.parametrize("change", ["disable", "demote"])
def test_admin_revoked_after_request_capture_is_denied_before_listing(
    accounts_api, monkeypatch, change
):
    runtime, client, _, headers, users = accounts_api
    backup = runtime.auth.authenticate(headers["backup"]["Authorization"][7:])
    authenticate, captured = runtime.auth.authenticate, []

    def revoke_after_capture(token):
        principal = authenticate(token)
        if principal.id == users["admin"]["id"] and not captured:
            captured.append(principal)
            runtime.auth.update_user(
                backup,
                principal.id,
                role="operator" if change == "demote" else "admin",
                active=change != "disable",
                expected_version=1,
                request_key="revoke-listing-admin",
            )
        return principal

    monkeypatch.setattr(runtime.auth, "authenticate", revoke_after_capture)
    response = client.get("/api/v1/users", headers=headers["admin"])
    assert len(captured) == 1
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    assert "items" not in response.json() and PASSWORD not in response.text


def test_count_and_rows_share_one_readonly_snapshot_during_real_user_creation(accounts_api):
    runtime, client, _, headers, _ = accounts_api
    admin = runtime.auth.authenticate(headers["admin"]["Authorization"][7:])
    reader_ids, writer_ids = [], []

    def create_after_count(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO core_users"):
            writer_ids.append(id(conn.connection.driver_connection))
        if "count(" in statement.lower() and "core_users" in statement and not reader_ids:
            assert conn.exec_driver_sql("PRAGMA query_only").scalar_one() == 1
            assert conn.connection.driver_connection.in_transaction
            reader_ids.append(id(conn.connection.driver_connection))
            runtime.auth.create_user(
                admin,
                username="concurrent-operator",
                password=PASSWORD,
                role="operator",
                request_key="concurrent-listing-user",
            )

    event.listen(runtime.database.engine, "after_cursor_execute", create_after_count)
    try:
        result = listing(client, headers["admin"])
    finally:
        event.remove(runtime.database.engine, "after_cursor_execute", create_after_count)
    assert result["total"] == len(result["items"]) == 3
    assert "concurrent-operator" not in {row["username"] for row in result["items"]}
    assert len(reader_ids) == len(writer_ids) == 1 and reader_ids[0] != writer_ids[0]
    fresh = listing(client, headers["admin"])
    assert fresh["total"] == 4 and "concurrent-operator" in {
        row["username"] for row in fresh["items"]
    }


def test_existing_last_admin_update_guard_remains_enforced(accounts_api):
    _, client, _, headers, users = accounts_api
    response = client.patch(
        "/api/v1/users/" + users["backup"]["id"],
        headers=headers["admin"],
        json={
            "role": "operator",
            "active": True,
            "expected_version": 1,
            "request_key": "demote-backup",
        },
    )
    assert response.status_code == 200, response.text
    for change in ({"role": "operator", "active": True}, {"role": "admin", "active": False}):
        response = client.patch(
            "/api/v1/users/" + users["admin"]["id"],
            headers=headers["admin"],
            json=change | {"expected_version": 1, "request_key": "last-admin-" + change["role"]},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "LAST_ADMIN"
    admins = listing(client, headers["admin"], role="admin")
    assert admins["total"] == 1 and admins["items"] == [users["admin"]]


def test_openapi_listing_response_exposes_only_public_account_page(accounts_api):
    _, client, _, _, _ = accounts_api
    schema = client.app.openapi()
    operation = schema["paths"]["/api/v1/users"]["get"]
    assert operation["security"] == [{"AppSession": [], "LocalUser": []}]
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    page = schema["components"]["schemas"][response["$ref"].rsplit("/", 1)[-1]]
    assert set(page["properties"]) == {"items", "total", "page", "page_size"}
    detail_ref = page["properties"]["items"]["items"]["$ref"]
    assert (
        set(schema["components"]["schemas"][detail_ref.rsplit("/", 1)[-1]]["properties"]) == FIELDS
    )
