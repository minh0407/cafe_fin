"""Bounded, credential-private controller for the real sidecar pipe and HTTP API."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path


class AcceptanceError(Exception):
    def __init__(self, code: str):
        self.code = code if re.fullmatch(r"[A-Z0-9_]{1,100}", code) else "ACCEPTANCE_FAILED"
        super().__init__(self.code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def outside_repo(path: Path, repository: Path) -> Path:
    resolved = path.resolve()
    if (
        resolved == repository
        or resolved.is_relative_to(repository)
        or str(resolved).startswith("\\\\")
        or any((parent / ".git").exists() for parent in (resolved, *resolved.parents))
    ):
        raise AcceptanceError("SYNTHETIC_LOCAL_ROOT_REQUIRED")
    return resolved


def artifact_identity(manifest_path: Path, expected_source: str) -> dict:
    """Validate coordinator provenance and bytes, without pretending to attest a build."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source):
        raise AcceptanceError("EXACT_CANDIDATE_SHA_REQUIRED")
    try:
        if manifest_path.stat().st_size > 256 * 1024:
            raise AcceptanceError("ARTIFACT_MANIFEST_LIMIT")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise AcceptanceError("ARTIFACT_MANIFEST_INVALID")
        if manifest.get("source_sha") != expected_source:
            raise AcceptanceError("ARTIFACT_SOURCE_MISMATCH")
        sidecar = manifest["sidecar"]
        raw_path = Path(sidecar["path"])
        if not raw_path.is_absolute() or str(raw_path).startswith("\\\\"):
            raise AcceptanceError("LOCAL_ABSOLUTE_ARTIFACT_REQUIRED")
        executable = raw_path.resolve()
        if executable.suffix.lower() != ".exe" or not executable.is_file():
            raise AcceptanceError("PACKAGED_SIDECAR_REQUIRED")
        if not re.fullmatch(r"[0-9a-f]{64}", sidecar["sha256"]):
            raise AcceptanceError("ARTIFACT_HASH_REQUIRED")
        if (
            type(sidecar["bytes"]) is not int
            or sidecar["bytes"] <= 0
            or executable.stat().st_size != sidecar["bytes"]
        ):
            raise AcceptanceError("ARTIFACT_SIZE_MISMATCH")
        if sha256(executable) != sidecar["sha256"]:
            raise AcceptanceError("ARTIFACT_HASH_MISMATCH")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise AcceptanceError("ARTIFACT_MANIFEST_INVALID") from exc
    return {
        "source_sha": expected_source,
        "sidecar": {
            "path": str(executable),
            "bytes": sidecar["bytes"],
            "sha256": sidecar["sha256"],
        },
        "manifest_sha256": sha256(manifest_path),
        "provenance": "coordinator_source_declaration_and_verified_file_digest",
        "gui_native": "NOT_RUN",
        "clean_windows": "NOT_RUN",
    }


class Sidecar:
    def __init__(self, command: list[str], repository: Path, data_root: Path):
        self.command, self.repository, self.data_root = command, repository, data_root
        self.process = None
        self.session_token = secrets.token_urlsafe(32)
        self.access_token = None
        self.api_base = None
        self.latencies: list[dict] = []
        self.stderr_bytes = 0
        self.closed = False
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def start(self, *, initialize: bool, source: bool):
        env = dict(os.environ)
        env["CAFE_FIN_MARKET_NETWORK"] = "0"
        env["PYTHONUTF8"] = "1"
        if source:
            env["PYTHONPATH"] = str(self.repository / "backend")
        else:
            env.pop("PYTHONPATH", None)
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.repository,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            # Do not copy/rename a blocked executable or weaken Windows policy.
            raise AcceptanceError("SIDECAR_OS_LAUNCH_BLOCKED") from exc
        messages: queue.Queue = queue.Queue(maxsize=2)

        def read_handshake():
            try:
                line = self.process.stdout.readline(16385)
                if not line.endswith(b"\n") or len(line) > 16384:
                    messages.put_nowait(AcceptanceError("HANDSHAKE_FRAME_INVALID"))
                else:
                    messages.put_nowait(json.loads(line))
            except (OSError, ValueError):
                messages.put_nowait(AcceptanceError("HANDSHAKE_FRAME_INVALID"))

        def drain_stderr():
            for block in iter(lambda: self.process.stderr.read(4096), b""):
                self.stderr_bytes += len(block)  # Never persist potentially sensitive output.

        threading.Thread(target=read_handshake, daemon=True).start()
        threading.Thread(target=drain_stderr, daemon=True).start()
        self.process.stdin.write(
            json.dumps(
                {
                    "protocol_version": 1,
                    "data_root": str(self.data_root),
                    "initialize": initialize,
                    "session_token": self.session_token,
                    "allowed_origin": "http://tauri.localhost",
                }
            ).encode()
            + b"\n"
        )
        self.process.stdin.flush()
        try:
            hello = messages.get(timeout=40)
        except queue.Empty as exc:
            self.close()
            raise AcceptanceError("SIDECAR_START_TIMEOUT") from exc
        if isinstance(hello, Exception):
            self.close()
            raise hello
        if hello.get("status") != "ready" or hello.get("protocol_version") != 1:
            self.close()
            raise AcceptanceError("SIDECAR_BOOT_REJECTED")
        parsed = urllib.parse.urlparse(hello.get("api_base", ""))
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path != "/api/v1"
            or not parsed.port
            or parsed.username
            or parsed.password
        ):
            self.close()
            raise AcceptanceError("LOOPBACK_HANDSHAKE_REQUIRED")
        self.api_base = hello["api_base"]
        self.closed = False
        return self

    def request(
        self, method, endpoint, body=None, *, file: Path | None = None, expected=200, label=None
    ):
        if (
            not endpoint.startswith("/")
            or "://" in endpoint
            or "\r" in endpoint
            or "\n" in endpoint
        ):
            raise AcceptanceError("LOCAL_ENDPOINT_REQUIRED")
        headers = {"X-App-Session": self.session_token, "Origin": "http://tauri.localhost"}
        if self.access_token:
            headers["Authorization"] = "Bearer " + self.access_token
        stream = None
        if file is not None:
            stream = file.open("rb")
            data = stream
            headers.update(
                {
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(file.stat().st_size),
                    "X-File-Name": urllib.parse.quote(file.name),
                    "X-Request-Key": secrets.token_hex(16),
                }
            )
        elif body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        else:
            data = None
        started = time.perf_counter()
        response = None
        try:
            request = urllib.request.Request(
                self.api_base + endpoint, data=data, headers=headers, method=method
            )
            try:
                response = self.opener.open(request, timeout=90)
            except urllib.error.HTTPError as exc:
                response = exc
            content = response.read(2 * 1024 * 1024 + 1)
            if len(content) > 2 * 1024 * 1024:
                raise AcceptanceError("HTTP_RESPONSE_LIMIT")
            if response.status != expected:
                raise AcceptanceError("HTTP_STATUS_UNEXPECTED")
            return json.loads(content)
        except (OSError, ValueError) as exc:
            raise AcceptanceError("LOCAL_HTTP_FAILED") from exc
        finally:
            self.latencies.append(
                {"label": label or endpoint.split("?")[0], "seconds": time.perf_counter() - started}
            )
            if response is not None:
                response.close()
            if stream is not None:
                stream.close()

    def content_hash(self, file_id: str) -> tuple[int, str]:
        headers = {
            "X-App-Session": self.session_token,
            "Origin": "http://tauri.localhost",
            "Authorization": "Bearer " + self.access_token,
        }
        request = urllib.request.Request(
            self.api_base + "/files/" + urllib.parse.quote(file_id, safe="") + "/content",
            headers=headers,
        )
        digest, size = hashlib.sha256(), 0
        with self.opener.open(request, timeout=90) as response:
            for block in iter(lambda: response.read(65536), b""):
                size += len(block)
                digest.update(block)
        return size, digest.hexdigest()

    def csv_receipt(self, file_id, columns, expected_rows, expected_income):
        """Hash raw derived bytes while checking CSV records with bounded lines."""
        headers = {
            "X-App-Session": self.session_token,
            "Origin": "http://tauri.localhost",
            "Authorization": "Bearer " + self.access_token,
        }
        request = urllib.request.Request(
            self.api_base + "/files/" + urllib.parse.quote(file_id, safe="") + "/content",
            headers=headers,
        )
        digest, size = hashlib.sha256(), 0
        money = next(index for index, column in enumerate(columns) if column["id"] == "amount")
        count, income = 0, Decimal(0)
        with self.opener.open(request, timeout=90) as response:

            def lines():
                nonlocal size
                first = True
                while raw := response.readline(262145):
                    if len(raw) > 262144:
                        raise AcceptanceError("CSV_EXPORT_LINE_LIMIT")
                    size += len(raw)
                    digest.update(raw)
                    yield raw.decode("utf-8-sig" if first else "utf-8")
                    first = False

            reader = csv.reader(lines(), strict=True)
            if next(reader, None) != [column["name"] for column in columns]:
                raise AcceptanceError("CSV_EXPORT_HEADER_MISMATCH")
            try:
                for record in reader:
                    if len(record) != len(columns):
                        raise AcceptanceError("CSV_EXPORT_WIDTH_MISMATCH")
                    value = Decimal(record[money])
                    if not value.is_finite():
                        raise AcceptanceError("CSV_EXPORT_MONEY_INVALID")
                    income += value
                    count += 1
            except (InvalidOperation, csv.Error, UnicodeError) as exc:
                raise AcceptanceError("CSV_EXPORT_INVALID") from exc
        if count != expected_rows or income != Decimal(expected_income):
            raise AcceptanceError("CSV_EXPORT_RECONCILIATION_MISMATCH")
        return {
            "bytes": size,
            "sha256": digest.hexdigest(),
            "data_rows": count,
            "data_cells": count * len(columns),
            "income_vnd": format(income, ".2f"),
        }

    def close(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b'{"command":"shutdown"}\n')
                self.process.stdin.flush()
                self.process.stdin.close()
                self.process.wait(timeout=25)
            except (OSError, subprocess.TimeoutExpired):
                # Owned process only. A forced stop is a failed acceptance result.
                if os.name == "nt" and self.process.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        check=False,
                    )
                elif self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=10)
                raise AcceptanceError("SIDECAR_SHUTDOWN_FAILED") from None
        if self.process.returncode != 0:
            raise AcceptanceError("SIDECAR_EXIT_FAILED")
        self.closed = True
