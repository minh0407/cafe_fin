"""Test-only private-pipe client for an unmodified source or frozen sidecar.

CAFE_FIN_REPORTING_TEST_SIDECAR selects an existing source-matched executable.
Without it, launch this checkout with the test interpreter. No transport, clock,
registry or timer patches are injected into either child.
"""

import hashlib
import json
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import httpx

MAX_FRAME = 16384
PASSWORD = "Synthetic-native-reporting-password"


def until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Native reporting probe exceeded bounded deadline")


class NativeSidecar:
    def __init__(self, root, *, initialize=False):
        self.root = root.resolve()
        self.generation = str(uuid4())
        self.session = secrets.token_urlsafe(32)
        self.access = None
        self.messages = queue.Queue()
        self.frames = []
        self.stderr = bytearray()
        self.http = httpx.Client(trust_env=False, timeout=20)
        environment = dict(os.environ)
        environment["CAFE_FIN_MARKET_NETWORK"] = "0"
        environment["PYTHONUTF8"] = "1"
        executable = os.environ.get("CAFE_FIN_REPORTING_TEST_SIDECAR")
        if executable:
            binary = Path(executable)
            assert binary.is_absolute() and binary.is_file(), "Expected an existing absolute EXE"
            expected = environment.get("CAFE_FIN_REPORTING_TEST_SIDECAR_SHA256", "")
            assert re.fullmatch(r"[0-9a-f]{64}", expected), "Supply the reviewed artifact SHA256"
            with binary.open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == expected, (
                    "Frozen sidecar hash differs from the reviewed artifact"
                )
            command = [str(binary)]  # Frozen entry point denies command-line arguments.
            environment.pop("PYTHONPATH", None)
        else:
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
            command = [sys.executable, "-m", "cafe_fin"]
        self.started = time.monotonic()
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def stdout():
            while raw := self.process.stdout.readline(MAX_FRAME + 1):
                if len(raw) > MAX_FRAME:
                    self.messages.put({"status": "invalid_frame"})
                    return
                self.frames.append(raw)
                try:
                    self.messages.put(json.loads(raw))
                except (ValueError, UnicodeError):
                    self.messages.put({"status": "invalid_frame"})

        def stderr():
            while raw := self.process.stderr.read(4096):
                # Drain the pipe even when full; never print raw diagnostic data.
                self.stderr.extend(raw[: max(0, 262144 - len(self.stderr))])

        self.readers = [threading.Thread(target=fn, daemon=True) for fn in (stdout, stderr)]
        for reader in self.readers:
            reader.start()
        try:
            self.send(
                {
                    "protocol_version": 1,
                    "session_token": self.session,
                    "data_root": str(self.root),
                    "initialize": initialize,
                    "allowed_origin": "http://tauri.localhost",
                    "maintenance_protocol": 1,
                    "generation": self.generation,
                    "activation_mode": "active",
                }
            )
            boot = self.messages.get(timeout=25)
            assert boot.get("status") == "ready", "Sidecar did not become ready"
            assert boot.get("runtime_state") == "ACTIVE"
            self.base = boot["api_base"]
            assert re.fullmatch(r"http://127\.0\.0\.1:[0-9]{1,5}/api/v1", self.base)
        except BaseException:
            self.close(check=False)
            raise

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def call(self, method, path, payload=None, *, content=False):
        assert path.startswith("/") and "://" not in path
        headers = {"X-App-Session": self.session}
        if self.access:
            headers["Authorization"] = "Bearer " + self.access
        response = self.http.request(method, self.base + path, headers=headers, json=payload)
        # No response body in failures: credential validation may contain secrets.
        assert response.status_code == 200, f"Native API {method} {path}: {response.status_code}"
        return response.content if content else response.json()

    def login(self, *, setup=False):
        self.access = self.call(
            "POST",
            "/auth/setup" if setup else "/auth/login",
            {"username": "native-report-admin", "password": PASSWORD},
        )["access_token"]
        # FIFO core job barrier drains the finite startup dispatch before tests
        # enable a due schedule. It cannot be mistaken for the real timer later.
        job = self.call(
            "POST",
            "/jobs",
            {"kind": "foundation.sample", "payload": {}, "request_key": str(uuid4())},
        )
        until(lambda: self.call("GET", "/jobs/" + job["job_id"])["state"] == "COMPLETED")

    def control(self, command, **fields):
        request = {
            "maintenance_protocol": 1,
            "request_id": str(uuid4()),
            "generation": self.generation,
            "command": command,
            "access_token": self.access,
            **fields,
        }
        if command not in ("reports.authorize_open", "maintenance.source_identity"):
            request.setdefault("operation_id", str(uuid4()))
            request["origin_generation"] = self.generation
        self.send(request)
        result = self.messages.get(timeout=30)
        assert result.get("request_id") == request["request_id"]
        assert result.get("generation") == self.generation
        code = result.get("code", "UNKNOWN")
        safe_code = (
            code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,80}", code) else "UNKNOWN"
        )
        assert result.get("status") == "ok", f"Private control command failed: {safe_code}"
        return result

    def close(self, *, check=True):
        forced = False
        try:
            if self.process.poll() is None:
                self.send({"command": "shutdown"})
                self.process.wait(timeout=25)
        except (OSError, subprocess.TimeoutExpired):
            forced = True
            self.process.kill()  # Cleanup only; never counted as a graceful exit.
            self.process.wait(timeout=10)
        finally:
            self.http.close()
            for reader in self.readers:
                reader.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
        if check:
            assert not forced and self.process.returncode == 0, "Sidecar failed graceful shutdown"

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.close(check=kind is None)
