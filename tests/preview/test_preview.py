"""Real SQLite/ASGI checks for the separate browser adapter; synthetic data only."""

import importlib.util
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from cafe_fin.core import secrets
from cafe_fin.core.errors import CoreError
from cafe_fin.reporting.telegram import OfficialTelegram
from fastapi.testclient import TestClient

SPEC = importlib.util.spec_from_file_location(
    "cafe_fin_browser_preview", Path(__file__).parents[2] / "scripts" / "preview.py"
)
preview = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preview)
BOOT_HEADERS = {
    "X-Preview-Bootstrap": "1",
    "Sec-Fetch-Site": "same-origin",
    "Origin": preview.ORIGIN,
}


@pytest.fixture
def frontend(tmp_path):
    folder = tmp_path / "ui"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>synthetic preview</html>", encoding="utf-8")
    (folder / "assets" / "bundle.js").write_text("export {};", encoding="utf-8")
    return folder


@pytest.fixture
def client(tmp_path, frontend):
    runtime = preview.open_preview_runtime(tmp_path / "data")
    app = preview.BrowserPreview(runtime, frontend)
    with TestClient(app, base_url=preview.ORIGIN) as connection:
        yield connection, runtime
    assert runtime._closed
    assert not runtime.runner.thread.is_alive()
    assert not runtime.periodic.thread.is_alive()


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 403),
        ({"Host": "evil.example:1420", **BOOT_HEADERS}, 400),
        ({"Host": "localhost:1420", **BOOT_HEADERS}, 400),
        ({**BOOT_HEADERS, "Origin": "https://evil.example"}, 403),
        ({**BOOT_HEADERS, "Sec-Fetch-Site": "cross-site"}, 403),
        ({**BOOT_HEADERS, "Sec-Fetch-Site": "same-site"}, 403),
        ({**BOOT_HEADERS, "X-Preview-Bootstrap": "0"}, 403),
    ],
)
def test_bootstrap_guards(client, headers, status):
    connection, _ = client
    response = connection.post("/preview/bootstrap", headers=headers)
    assert response.status_code == status
    assert "session_token" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert not any(key.startswith("access-control-") for key in response.headers)


def bootstrap(connection):
    response = connection.post("/preview/bootstrap", headers=BOOT_HEADERS)
    assert response.status_code == 200
    boot = response.json()
    assert set(boot) == {
        "protocol_version",
        "api_base",
        "session_token",
        "data_root",
        "runtime_state",
    }
    assert boot["api_base"] == preview.ORIGIN + "/api/v1"
    assert len(boot["session_token"]) >= 32
    assert "maintenance_protocol" not in boot and "generation" not in boot
    assert not any(key.startswith("access-control-") for key in response.headers)
    return {"X-App-Session": boot["session_token"], "Origin": preview.ORIGIN}


def test_real_api_session_and_bearer_setup_files_exports_and_lifespan(client):
    connection, runtime = client
    assert runtime._started and runtime.runner.thread.is_alive()
    assert connection.get("/api/v1/health").status_code == 401
    headers = bootstrap(connection)
    assert connection.get("/api/v1/health", headers=headers).json()["setup_required"]
    assert connection.get("/api/v1/auth/me", headers=headers).status_code == 401
    setup = connection.post(
        "/api/v1/auth/setup",
        headers=headers,
        json={"username": "previewadmin", "password": "synthetic-password"},
    )
    assert setup.status_code == 200, setup.text
    headers["Authorization"] = "Bearer " + setup.json()["access_token"]
    assert connection.get("/api/v1/auth/me", headers=headers).json()["role"] == "admin"
    uploaded = connection.post(
        "/api/v1/files?category=documents",
        content=b"synthetic bytes",
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-File-Name": "synthetic.txt",
            "X-Request-Key": "preview-upload",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["id"]
    assert connection.get(f"/api/v1/files/{file_id}/content", headers=headers).content == (
        b"synthetic bytes"
    )
    exported = connection.post(
        "/api/v1/spikes/documents", headers=headers, json={"request_key": "preview-real-export"}
    )
    assert exported.status_code == 200 and exported.json()["errors"] == []
    assert {item["format"] for item in exported.json()["documents"]} == {"pdf", "docx"}
    for item in exported.json()["documents"]:
        assert (
            connection.get(f"/api/v1/files/{item['file_id']}/content", headers=headers).status_code
            == 200
        )


def test_reopen_keeps_data_requires_new_capability(tmp_path, frontend):
    data = tmp_path / "data"
    with TestClient(
        preview.BrowserPreview(preview.open_preview_runtime(data), frontend),
        base_url=preview.ORIGIN,
    ) as connection:
        headers = bootstrap(connection)
        old_token = headers["X-App-Session"]
        assert (
            connection.post(
                "/api/v1/auth/setup",
                headers=headers,
                json={"username": "previewadmin", "password": "synthetic-password"},
            ).status_code
            == 200
        )
    with TestClient(
        preview.BrowserPreview(preview.open_preview_runtime(data), frontend),
        base_url=preview.ORIGIN,
    ) as connection:
        assert (
            connection.get("/api/v1/health", headers={"X-App-Session": old_token}).status_code
            == 401
        )
        headers = bootstrap(connection)
        assert not connection.get("/api/v1/health", headers=headers).json()["setup_required"]
        assert (
            connection.post(
                "/api/v1/auth/login",
                headers=headers,
                json={"username": "previewadmin", "password": "synthetic-password"},
            ).status_code
            == 200
        )
    assert old_token.encode() not in b"".join(
        file.read_bytes() for file in data.rglob("*") if file.is_file()
    )


def test_refuse_unmarked_nonempty_directory_without_mutation(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    original = data / "existing.txt"
    original.write_bytes(b"preserve")
    with pytest.raises(CoreError, match="DATA_ROOT_INVALID"):
        preview.open_preview_runtime(data)
    assert list(data.iterdir()) == [original]
    assert original.read_bytes() == b"preserve"


def test_static_and_native_routes_do_not_leak_files_or_allow_cors(client):
    connection, _ = client
    assert connection.get("/").status_code == 200
    assert connection.get("/assets/bundle.js").status_code == 200
    for path in [
        "/preview/restart",
        "/preview/open-reports",
        "/preview/maintenance",
        "/data/database/cafe_fin.db",
        "/assets/missing.js",
        "/assets/%2e%2e/index.html",
    ]:
        assert connection.get(path).status_code == 404
    assert connection.get("/preview/bootstrap", headers=BOOT_HEADERS).status_code == 403
    assert (
        connection.post("/preview/bootstrap?token=forbidden", headers=BOOT_HEADERS).status_code
        == 403
    )
    assert (
        connection.post(
            "/preview/bootstrap",
            headers=[*BOOT_HEADERS.items(), ("Host", "127.0.0.1:1420"), ("Host", "evil.example")],
        ).status_code
        == 403
    )
    response = connection.options("/api/v1/health", headers={"Origin": preview.ORIGIN})
    assert response.status_code == 403
    assert not any(key.startswith("access-control-") for key in response.headers)
    assert connection.get("/", headers={"Origin": "https://evil.example"}).status_code == 403


def test_linux_credentials_unavailable_and_connection_check_no_wan(tmp_path, frontend, monkeypatch):
    # Simulate just the adapter's platform on Windows; real Linux is a Docker gate.
    monkeypatch.setattr(secrets, "sys", SimpleNamespace(platform="linux"))
    calls = []

    def no_wan(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Preview must not contact WAN without credentials")

    monkeypatch.setattr(socket, "create_connection", no_wan)
    monkeypatch.setattr(OfficialTelegram, "verify", no_wan)
    monkeypatch.setattr(OfficialTelegram, "send_text", no_wan)
    monkeypatch.setattr(OfficialTelegram, "send_document", no_wan)
    with TestClient(
        preview.BrowserPreview(preview.open_preview_runtime(tmp_path / "data"), frontend),
        base_url=preview.ORIGIN,
    ) as connection:
        headers = bootstrap(connection)
        setup = connection.post(
            "/api/v1/auth/setup",
            headers=headers,
            json={"username": "previewadmin", "password": "synthetic-password"},
        )
        headers["Authorization"] = "Bearer " + setup.json()["access_token"]
        settings = connection.get("/api/v1/reporting/settings", headers=headers).json()
        assert settings["credential_store_available"] is False
        assert settings["credential_configured"] is False
        assert settings["sender_status"] == "UNCONFIGURED"
        result = connection.post(
            "/api/v1/reporting/connection-check",
            headers=headers,
            json={"request_key": "preview-no-network"},
        )
        assert result.status_code == 200
        assert result.json() == {"state": "UNCONFIGURED", "code": "TELEGRAM_UNCONFIGURED"}
        credential = connection.put(
            "/api/v1/reporting/credentials",
            headers=headers,
            json={"bot_token": "123456789:" + "A" * 35},
        )
        assert credential.status_code == 503
        assert credential.json()["error"]["code"] == "SECRET_STORE_UNAVAILABLE"
        assert not calls
