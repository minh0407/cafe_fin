import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from cafe_fin.core.api import create_app
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from pypdf import PdfReader

TOKEN = "synthetic-app-session-0123456789abcdef"
ORIGIN = "http://tauri.localhost"
PORT = 48931


def test_api_auth_origin_host_paging_downloads_and_jobs(tmp_path):
    runtime = Runtime(tmp_path / "Dữ liệu thử có khoảng trắng", initialize=True)
    app = create_app(runtime, TOKEN, port=PORT)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        assert client.get("/api/v1/health").status_code == 401
        headers = {"X-App-Session": TOKEN, "Origin": ORIGIN}
        assert client.get("/api/v1/health", headers=headers).json()["setup_required"]
        evil = client.get("/api/v1/health", headers=headers | {"Origin": "https://outside.example"})
        assert evil.status_code == 403
        assert "access-control-allow-origin" not in evil.headers
        assert (
            client.get("/api/v1/health", headers=headers | {"Host": "rebound.example"}).status_code
            == 400
        )
        preflight = client.options(
            "/api/v1/users",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-app-session,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == ORIGIN
        assert client.get("/api/v1/spikes/grid", headers=headers).status_code == 401
        invalid = client.post(
            "/api/v1/auth/setup",
            headers=headers,
            json={"username": "admin", "password": "secret", "unknown": "secret"},
        )
        assert invalid.status_code == 422
        assert "secret" not in invalid.text
        result = client.post(
            "/api/v1/auth/setup",
            headers=headers,
            json={"username": "admin", "password": "synthetic-password"},
        )
        assert result.status_code == 200, result.text
        user_token = result.json()["access_token"]
        headers["Authorization"] = f"Bearer {user_token}"
        grid = client.get("/api/v1/spikes/grid?page=2&page_size=500", headers=headers).json()
        assert len(grid["items"]) == 500 and grid["items"][0]["source_row"] == 502
        assert grid["items"][0]["amount"] == "92233720368547758.07"
        assert client.get("/api/v1/spikes/grid?page_size=501", headers=headers).status_code == 422
        assert (
            client.post(
                "/api/v1/jobs",
                headers=headers,
                json={"kind": "unknown", "payload": {}, "request_key": "job"},
            ).status_code
            == 400
        )
        job = client.post(
            "/api/v1/jobs",
            headers=headers,
            json={"kind": "foundation.sample", "payload": {}, "request_key": "job"},
        ).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(f"/api/v1/jobs/{job['job_id']}", headers=headers).json()
            if status["state"] == "COMPLETED":
                break
            time.sleep(0.02)
        assert status["state"] == "COMPLETED"
        documents = client.post(
            "/api/v1/spikes/documents", headers=headers, json={"request_key": "sample-export"}
        ).json()
        assert documents["errors"] == [], documents
        assert {item["format"] for item in documents["documents"]} == {"docx", "pdf"}
        assert (
            client.post(
                "/api/v1/spikes/documents", headers=headers, json={"request_key": "sample-export"}
            ).json()
            == documents
        )
        for item in documents["documents"]:
            download = client.get(f"/api/v1/files/{item['file_id']}/content", headers=headers)
            assert download.status_code == 200
            assert hashlib.sha256(download.content).hexdigest() == item["sha256"]
            if item["format"] == "pdf":
                assert "Cà phê" in "".join(
                    page.extract_text() for page in PdfReader(io.BytesIO(download.content)).pages
                )
        note_payload = {"text": "Ghi chú tổng hợp", "request_key": "example-create"}
        note = client.post("/api/v1/example/notes", headers=headers, json=note_payload).json()
        assert note["version"] == 1
        assert (
            client.post("/api/v1/example/notes", headers=headers, json=note_payload).json() == note
        )
        patch_url = f"/api/v1/example/notes/{note['id']}"
        assert (
            client.patch(
                patch_url,
                headers=headers,
                json={"text": "Bản sửa", "expected_version": 1, "request_key": "edit-1"},
            ).json()["version"]
            == 2
        )
        assert (
            client.patch(
                patch_url,
                headers=headers,
                json={"text": "Bản sửa cũ", "expected_version": 1, "request_key": "edit-2"},
            ).status_code
            == 409
        )
        client.post(
            "/api/v1/users",
            headers=headers,
            json={
                "username": "operator",
                "password": "synthetic-password",
                "role": "operator",
                "request_key": "operator-create",
            },
        ).raise_for_status()
        operator = client.post(
            "/api/v1/auth/login",
            headers={"X-App-Session": TOKEN},
            json={"username": "operator", "password": "synthetic-password"},
        ).json()
        operator_headers = {
            "X-App-Session": TOKEN,
            "Authorization": "Bearer " + operator["access_token"],
        }
        assert client.get("/api/v1/settings/data-root", headers=operator_headers).status_code == 403
        assert client.get(patch_url, headers=operator_headers).status_code == 403
        oversized = client.post(
            "/api/v1/jobs", headers=headers, content=b" " * (2 * 1024 * 1024 + 1)
        )
        assert oversized.status_code == 413
        schema = app.openapi()
        assert schema["paths"]["/api/v1/auth/login"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"].endswith("AuthDTO")
        assert TOKEN not in json.dumps(schema)
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def sidecar(path: Path, token=TOKEN, initialize=True):
    process = subprocess.Popen(
        [sys.executable, "-m", "cafe_fin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[2] / "backend")},
    )
    process.stdin.write(
        json.dumps(
            {
                "protocol_version": 1,
                "session_token": token,
                "data_root": str(path),
                "initialize": initialize,
                "allowed_origin": ORIGIN,
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    process.stdin.flush()
    lines = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    line = lines.get(timeout=20)
    return process, json.loads(line)


def shutdown(process):
    process.stdin.write('{"command":"shutdown"}\n')
    process.stdin.flush()
    process.wait(timeout=15)
    assert process.returncode == 0
    assert process.stderr.read() == ""


def test_sidecar_real_loopback_unicode_second_instance_and_restart(tmp_path):
    root = tmp_path / "Kho dữ liệu Việt Nam có dấu"
    process, boot = sidecar(root)
    try:
        assert boot["status"] == "ready"
        assert TOKEN not in json.dumps(boot)
        assert boot["api_base"].startswith("http://127.0.0.1:")
        headers = {"X-App-Session": TOKEN}
        with httpx.Client(trust_env=False, timeout=5) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    response = client.get(boot["api_base"] + "/health", headers=headers)
                    if response.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline
                time.sleep(0.05)
            assert client.get(boot["api_base"] + "/health").status_code == 401
            second, failure = sidecar(root, initialize=False)
            second.wait(timeout=10)
            assert failure["code"] == "DATA_ROOT_LOCKED" and second.returncode == 1
            assert str(root) not in json.dumps(failure)
        shutdown(process)
        again, ready = sidecar(root, initialize=False)
        assert ready["status"] == "ready"
        shutdown(again)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    missing, error = sidecar(tmp_path / "absent", initialize=False)
    missing.wait(timeout=10)
    assert error["code"] == "DATA_ROOT_UNAVAILABLE"
    assert not (tmp_path / "absent").exists()
    bad, error = sidecar(tmp_path / "bad-token-root", token="invalid-token")
    bad.wait(timeout=10)
    assert error["code"] == "BOOT_PROTOCOL_INVALID"
    assert not (tmp_path / "bad-token-root").exists()
