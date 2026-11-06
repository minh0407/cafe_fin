"""Original-byte transfer tests; no workbook parsing or business import is performed."""

import asyncio
import hashlib
import io
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import zipfile
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient

TOKEN = "synthetic-transfer-session-0123456789abcdef"
ORIGIN = "http://tauri.localhost"
PORT = 48956
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FILE_FIELDS = {"id", "sha256", "size", "category", "original_name", "media_type", "created_at"}


def large_synthetic_workbook():
    """A small workbook plus inert unreferenced padding; ZIP_STORED keeps it >2 MiB."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Dữ liệu tổng hợp" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>001</t></is></c><c r="B1" t="inlineStr"><is><t>Đắk Lắk</t></is></c></row></sheetData></worksheet>',
        )
        archive.writestr("synthetic-padding.bin", b"synthetic-padding-only-" * 150000)
    return output.getvalue()


@pytest.fixture
def transfer_sidecar(tmp_path):
    root = tmp_path / "Tệp nguồn có dấu và khoảng trắng"
    binary = os.environ.get("CAFE_FIN_TEST_SIDECAR")
    env = dict(os.environ)
    if binary:
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            env.pop(key, None)
    else:
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
    process = subprocess.Popen(
        [binary] if binary else [sys.executable, "-m", "cafe_fin"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
    )
    try:
        process.stdin.write(
            json.dumps(
                {
                    "protocol_version": 1,
                    "session_token": TOKEN,
                    "data_root": str(root),
                    "initialize": True,
                    "allowed_origin": ORIGIN,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        process.stdin.flush()
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        boot = json.loads(lines.get(timeout=20))
        assert boot["status"] == "ready", boot
        with httpx.Client(trust_env=False, timeout=15) as client:
            base = boot["api_base"]
            common = {"X-App-Session": TOKEN, "Origin": ORIGIN}
            setup = client.post(
                base + "/auth/setup",
                headers=common,
                json={"username": "transfer-admin", "password": "synthetic-transfer-password"},
            )
            assert setup.status_code == 200, setup.text
            headers = common | {"Authorization": "Bearer " + setup.json()["access_token"]}
            yield root, base, client, headers
        process.stdin.write('{"command":"shutdown"}\n')
        process.stdin.flush()
        process.wait(timeout=15)
        assert process.returncode == 0
        assert process.stderr.read() == ""
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()


def test_real_sidecar_large_original_bytes_unicode_chunked_replay_and_no_orphans(transfer_sidecar):
    root, base, client, headers = transfer_sidecar
    payload = large_synthetic_workbook()
    assert len(payload) > 2 * 1024**2
    original_name = "Sổ kế toán đầu kỳ 001 Đắk Lắk.xlsx"
    upload_headers = headers | {
        "X-File-Name": quote(original_name, safe=""),
        "X-Request-Key": "original-large-workbook",
        "Content-Type": XLSX_TYPE,
    }
    uploaded = client.post(
        base + "/files?category=workbooks", headers=upload_headers, content=payload
    )
    assert uploaded.status_code == 200, uploaded.text
    result = uploaded.json()
    assert set(result) == FILE_FIELDS
    assert result["original_name"] == original_name
    assert result["category"] == "workbooks"
    assert result["size"] == len(payload)
    assert result["media_type"] == XLSX_TYPE
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()

    def chunks():
        for offset in range(0, len(payload), 64 * 1024):
            yield payload[offset : offset + 64 * 1024]

    replay_request = client.build_request(
        "POST", base + "/files?category=workbooks", headers=upload_headers, content=chunks()
    )
    assert replay_request.headers["transfer-encoding"] == "chunked"
    assert "content-length" not in replay_request.headers
    replay = client.send(replay_request)
    assert replay.status_code == 200, replay.text
    assert replay.json() == result
    metadata = client.get(base + f"/files/{result['id']}", headers=headers)
    assert metadata.status_code == 200
    assert metadata.json() == result
    content = client.get(base + f"/files/{result['id']}/content", headers=headers)
    assert content.status_code == 200
    assert content.content == payload
    assert list((root / "imports").iterdir()) == []
    stored = list((root / "workbooks").iterdir())
    assert len(stored) == 1
    assert hashlib.sha256(stored[0].read_bytes()).hexdigest() == result["sha256"]
    with closing(
        sqlite3.connect((root / "database" / "cafe_fin.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        assert conn.execute("SELECT count(*) FROM core_files").fetchone()[0] == 1


@pytest.fixture
def transfer_runtime(tmp_path):
    runtime = Runtime(tmp_path / "Transfer validation", initialize=True)
    session = runtime.auth.setup("transfer-admin", "synthetic-transfer-password")
    headers = {
        "X-App-Session": TOKEN,
        "Origin": ORIGIN,
        "Authorization": "Bearer " + session["access_token"],
        "Host": f"127.0.0.1:{PORT}",
        "X-File-Name": quote("Tệp thử.xlsx", safe=""),
        "X-Request-Key": "small-transfer",
        "Content-Type": XLSX_TYPE,
    }
    app = create_app(runtime, TOKEN, port=PORT)
    try:
        yield runtime, app, headers
    finally:
        runtime.close()


def asgi_upload(app, headers, chunks=None):
    consumed = []
    messages = []
    iterator = iter(chunks) if chunks is not None else None

    async def receive():
        if iterator is None:
            raise AssertionError("invalid/unauthorized upload consumed the request body")
        chunk = next(iterator, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed.append(len(chunk))
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/files",
        "raw_path": b"/api/v1/files",
        "query_string": b"category=workbooks",
        "root_path": "",
        "headers": [
            (key.lower().encode("ascii"), value.encode("ascii")) for key, value in headers.items()
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", PORT),
    }
    asyncio.run(app(scope, receive, send))
    status = next(
        message["status"] for message in messages if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, json.loads(body), consumed


@pytest.mark.parametrize("invalid", ["missing-name", "missing-key", "long-key", "path-name"])
def test_upload_header_validation_rejects_before_receiving_bytes(transfer_runtime, invalid):
    runtime, app, headers = transfer_runtime
    headers = dict(headers)
    if invalid == "missing-name":
        headers.pop("X-File-Name")
    elif invalid == "missing-key":
        headers.pop("X-Request-Key")
    elif invalid == "long-key":
        headers["X-Request-Key"] = "x" * 129
    else:
        headers["X-File-Name"] = quote("../outside.xlsx", safe="")
    status, error, consumed = asgi_upload(app, headers)
    assert status in {400, 422}
    assert error["error"]["code"]
    assert consumed == []
    assert list(runtime.root.resolve_key("imports").iterdir()) == []
    assert list(runtime.root.resolve_key("workbooks").iterdir()) == []


@pytest.mark.parametrize(
    "invalid, expected", [("app-session", 401), ("user-session", 401), ("origin", 403)]
)
def test_upload_auth_and_origin_reject_before_receiving_bytes(transfer_runtime, invalid, expected):
    _, app, headers = transfer_runtime
    headers = dict(headers)
    if invalid == "app-session":
        headers["X-App-Session"] = "invalid"
    elif invalid == "user-session":
        headers.pop("Authorization")
    else:
        headers["Origin"] = "https://outside.example"
    status, error, consumed = asgi_upload(app, headers)
    assert status == expected
    assert error["error"]["code"]
    assert consumed == []


def test_chunked_upload_limit_stops_early_and_leaves_no_file(transfer_runtime):
    runtime, app, headers = transfer_runtime
    runtime.files.max_bytes = 1024
    status, _, consumed = asgi_upload(app, headers, [b"x" * 700] * 10)
    assert status == 413
    assert 0 < sum(consumed) <= 1024 + 700
    assert list(runtime.root.resolve_key("imports").iterdir()) == []
    assert list(runtime.root.resolve_key("workbooks").iterdir()) == []


def test_content_length_limit_and_other_command_json_limit_remain_enforced(transfer_runtime):
    runtime, app, headers = transfer_runtime
    runtime.files.max_bytes = 1024
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        limited = client.post(
            "/api/v1/files?category=workbooks", headers=headers, content=b"x" * 2048
        )
        assert limited.status_code == 413
        command_headers = {
            key: value
            for key, value in headers.items()
            if key not in {"X-File-Name", "X-Request-Key"}
        }
        oversized = client.post(
            "/api/v1/jobs",
            headers=command_headers | {"Content-Type": "application/json"},
            content=b"x" * (2 * 1024**2 + 1),
        )
        assert oversized.status_code == 413
    assert list(runtime.root.resolve_key("imports").iterdir()) == []
    assert list(runtime.root.resolve_key("workbooks").iterdir()) == []


def test_browser_preflight_allows_only_the_required_transfer_headers(transfer_runtime):
    _, app, _ = transfer_runtime
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        response = client.options(
            "/api/v1/files?category=workbooks",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,x-app-session,x-file-name,x-request-key",
            },
        )
        assert response.status_code == 200
        allowed = {
            item.strip().lower()
            for item in response.headers["access-control-allow-headers"].split(",")
        }
        assert {
            "x-file-name",
            "x-request-key",
            "x-app-session",
            "authorization",
            "content-type",
        }.issubset(allowed)
        denied = client.options(
            "/api/v1/files?category=workbooks",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-run-shell",
            },
        )
        assert denied.status_code == 403


def test_actor_revoked_while_uploading_cannot_commit_original_file(transfer_runtime):
    runtime, app, headers = transfer_runtime
    original = runtime.auth.authenticate(headers["Authorization"][7:])
    runtime.auth.create_user(
        original,
        username="second-admin",
        password="synthetic-second-password",
        role="admin",
        request_key="second-admin",
    )
    session = runtime.auth.login("second-admin", "synthetic-second-password")
    second = runtime.auth.authenticate(session["access_token"])

    def chunks():
        # Executed only when the route receives the body, after middleware captured
        # the original principal. Revocation must be checked again at file commit.
        runtime.auth.update_user(
            second,
            original.id,
            role="operator",
            active=False,
            expected_version=original.version,
            request_key="revoke-during-upload",
        )
        yield b"synthetic-original-file"

    status, error, consumed = asgi_upload(app, headers, chunks())
    assert status in {401, 403}
    assert error["error"]["code"] in {"SESSION_EXPIRED", "PERMISSION_DENIED"}
    assert consumed
    assert list(runtime.root.resolve_key("imports").iterdir()) == []
    assert list(runtime.root.resolve_key("workbooks").iterdir()) == []
