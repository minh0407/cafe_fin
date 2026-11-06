"""Real-loopback regressions for download validation and interrupted document exports.

Faults run inside a Python source sidecar child, never the frozen executable or a
developer's existing data root. Session credentials still enter only via stdin.
"""

import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

import httpx
import pytest

TOKEN = "synthetic-recovery-session-0123456789abcdef"
ORIGIN = "http://tauri.localhost"
PASSWORD = "synthetic-recovery-password"


def _spawn(root, patches="", *, initialize=True):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[2] / "backend")
    environment["PYTHONUTF8"] = "1"
    code = "import cafe_fin.__main__ as entry\n" + patches + "\nraise SystemExit(entry.main())\n"
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=environment,
    )
    process.stdin.write(
        json.dumps(
            {
                "protocol_version": 1,
                "session_token": TOKEN,
                "data_root": str(root),
                "initialize": initialize,
                "allowed_origin": ORIGIN,
            }
        )
        + "\n"
    )
    process.stdin.flush()
    messages = queue.Queue()
    threading.Thread(target=lambda: messages.put(process.stdout.readline()), daemon=True).start()
    try:
        line = messages.get(timeout=20)
        assert line, "Sidecar exited without a boot envelope."
        assert TOKEN not in line
        return process, json.loads(line)
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        raise


def _stop(process):
    if process.poll() is None:
        try:
            process.stdin.write('{"command":"shutdown"}\n')
            process.stdin.flush()
            process.wait(timeout=15)
        except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=10)
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close()


@contextmanager
def _sidecar(root, patches="", *, initialize=True):
    process, boot = _spawn(root, patches, initialize=initialize)
    try:
        assert boot["status"] == "ready", boot
        base = boot["api_base"]
        with httpx.Client(trust_env=False, timeout=10) as client:
            deadline = time.monotonic() + 10
            while True:
                try:
                    if (
                        client.get(base + "/health", headers={"X-App-Session": TOKEN}).status_code
                        == 200
                    ):
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "Ready sidecar did not serve health."
                time.sleep(0.02)
            yield process, client, base
    finally:
        _stop(process)


def _authenticate(client, base, *, setup=True):
    headers = {"X-App-Session": TOKEN, "Origin": ORIGIN}
    response = client.post(
        base + ("/auth/setup" if setup else "/auth/login"),
        headers=headers,
        json={"username": "recovery-admin", "password": PASSWORD},
    )
    response.raise_for_status()
    return headers | {"Authorization": "Bearer " + response.json()["access_token"]}


def _file_rows(root):
    databases = list((root / "database").glob("*.sqlite3")) + list((root / "database").glob("*.db"))
    assert len(databases) == 1
    with closing(sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM core_files ORDER BY id")]


@pytest.mark.parametrize(
    ("damage", "error_code"),
    [("missing", "FILE_MISSING"), ("corrupt", "FILE_HASH_MISMATCH")],
)
def test_download_validates_owned_file_before_sending_success_headers(tmp_path, damage, error_code):
    root = tmp_path / "Dữ liệu download thử"
    with _sidecar(root) as (process, client, base):
        headers = _authenticate(client, base)
        export = client.post(
            base + "/spikes/documents", headers=headers, json={"request_key": "download"}
        )
        export.raise_for_status()
        document = export.json()["documents"][0]
        record = next(row for row in _file_rows(root) if row["id"] == document["file_id"])
        source = (root / record["relative_key"]).resolve()
        assert source.is_relative_to(root.resolve())
        if damage == "missing":
            source.unlink()
        else:
            source.write_bytes(b"synthetic corrupted export")
        # A real HTTP stream exposes the original 200-before-generator-error bug.
        with client.stream(
            "GET", base + f"/files/{document['file_id']}/content", headers=headers
        ) as response:
            assert response.status_code == 409
            body = json.loads(response.read())
            assert body["error"]["code"] == error_code
            assert body["request_id"]
            assert response.headers["content-type"].startswith("application/json")
            assert "content-disposition" not in response.headers
            assert str(root) not in json.dumps(body)
        assert process.poll() is None


def test_final_document_receipt_failure_reuses_both_committed_formats(tmp_path):
    marker = tmp_path / "aggregate-fault.json"
    patches = f"""
import json
from pathlib import Path
from cafe_fin.core.db import WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentRenderer
marker = Path({str(marker)!r})
original_execute = WriteCoordinator.execute
committed = []
failed = False
render_calls = {{"docx": 0, "pdf": 0}}
for format in ("docx", "pdf"):
    original_render = getattr(DocumentRenderer, format)
    def guarded_render(self, snapshot, _format=format, _original=original_render):
        render_calls[_format] += 1
        if render_calls[_format] > 1:
            raise RuntimeError("Committed format was rendered again")
        return _original(self, snapshot)
    setattr(DocumentRenderer, format, guarded_render)
def interrupted_execute(self, actor, action, key, payload, operation, **kwargs):
    global failed
    if action == "spikes.documents" and not failed:
        assert len(committed) == 2
        marker.write_text(json.dumps({{"files": committed, "render_calls": render_calls}}), encoding="utf-8")
        failed = True
        raise CoreError("SYNTHETIC_FINAL_RECEIPT_FAILURE", "Tệp thử đã ghi; receipt cuối tạm lỗi.", 503)
    result = original_execute(self, actor, action, key, payload, operation, **kwargs)
    if action == "files.put" and result["category"] == "documents":
        committed.append(result)
    return result
WriteCoordinator.execute = interrupted_execute
"""
    root = tmp_path / "aggregate-data"
    with _sidecar(root, patches) as (_, client, base):
        headers = _authenticate(client, base)
        command = {"request_key": "same-export-attempt"}
        first = client.post(base + "/spikes/documents", headers=headers, json=command)
        assert first.status_code == 503
        assert first.json()["error"]["code"] == "SYNTHETIC_FINAL_RECEIPT_FAILURE"
        evidence = json.loads(marker.read_text(encoding="utf-8"))
        original = {item["id"]: item["sha256"] for item in evidence["files"]}
        assert evidence["render_calls"] == {"docx": 1, "pdf": 1}
        retry = client.post(base + "/spikes/documents", headers=headers, json=command)
        assert retry.status_code == 200, retry.text
        result = retry.json()
        assert result["errors"] == []
        assert {item["format"] for item in result["documents"]} == {"docx", "pdf"}
        assert {item["file_id"]: item["sha256"] for item in result["documents"]} == original
        assert len(_file_rows(root)) == 2
        assert (
            client.post(base + "/spikes/documents", headers=headers, json=command).json() == result
        )


def test_crash_after_first_document_reuses_format_and_pinned_snapshot_on_restart(tmp_path):
    marker = tmp_path / "crash-after-first-format.json"
    patches = f"""
import json
import os
from pathlib import Path
from cafe_fin.core.db import WriteCoordinator
from cafe_fin.core.renderers import DocumentRenderer
original_execute = WriteCoordinator.execute
original_docx = DocumentRenderer.docx
snapshot_hash = None
def record_snapshot(self, snapshot):
    global snapshot_hash
    snapshot_hash = snapshot.sha256
    return original_docx(self, snapshot)
DocumentRenderer.docx = record_snapshot
def crash_after_file(self, actor, action, key, payload, operation, **kwargs):
    result = original_execute(self, actor, action, key, payload, operation, **kwargs)
    if action == "files.put" and result["category"] == "documents":
        with Path({str(marker)!r}).open("w", encoding="utf-8") as stream:
            json.dump({{"file": result, "snapshot_sha256": snapshot_hash}}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(86)
    return result
WriteCoordinator.execute = crash_after_file
"""
    root = tmp_path / "crash-data"
    command = {"request_key": "crash-export-attempt"}
    with _sidecar(root, patches) as (process, client, base):
        headers = _authenticate(client, base)
        with pytest.raises(httpx.TransportError):
            client.post(base + "/spikes/documents", headers=headers, json=command)
        process.wait(timeout=10)
        assert process.returncode == 86
    evidence = json.loads(marker.read_text(encoding="utf-8"))
    assert len(_file_rows(root)) == 1
    restart_patches = """
from cafe_fin.core import api
from cafe_fin.core.renderers import DocumentRenderer, DocumentSnapshot
def changed_snapshot_source():
    return DocumentSnapshot(title="Changed synthetic source after crash")
def committed_docx_must_not_render(self, snapshot):
    raise RuntimeError("Previously committed DOCX must be reused")
api.synthetic_snapshot = changed_snapshot_source
DocumentRenderer.docx = committed_docx_must_not_render
"""
    with _sidecar(root, restart_patches, initialize=False) as (_, client, base):
        headers = _authenticate(client, base, setup=False)
        retry = client.post(base + "/spikes/documents", headers=headers, json=command)
        assert retry.status_code == 200, retry.text
        result = retry.json()
        assert result["errors"] == []
        assert result["snapshot_sha256"] == evidence["snapshot_sha256"]
        docx = next(item for item in result["documents"] if item["format"] == "docx")
        assert docx["file_id"] == evidence["file"]["id"]
        assert docx["sha256"] == evidence["file"]["sha256"]
        assert {item["format"] for item in result["documents"]} == {"docx", "pdf"}
        assert len(_file_rows(root)) == 2
        assert (
            client.post(base + "/spikes/documents", headers=headers, json=command).json() == result
        )


def test_runtime_start_failure_never_advertises_ready(tmp_path):
    patches = """
def failed_start(self):
    raise OSError("Synthetic local runner startup failure")
entry.Runtime.start = failed_start
"""
    process, envelope = _spawn(tmp_path / "startup-data", patches)
    try:
        process.wait(timeout=15)
        assert process.returncode == 1
        remaining = [json.loads(line) for line in process.stdout.read().splitlines() if line]
        messages = [envelope, *remaining]
        assert all(item["status"] == "error" for item in messages)
        assert envelope["code"] == "STARTUP_FAILED"
        assert envelope["api_base"] == ""
        assert TOKEN not in json.dumps(messages)
        assert "Synthetic local runner startup failure" not in json.dumps(messages)
    finally:
        _stop(process)
