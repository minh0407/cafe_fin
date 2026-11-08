"""Run the synthetic records scenario against a private source/frozen sidecar.

This is API evidence, never native GUI or clean-client acceptance. No supplied
data root is accepted: every invocation creates new synthetic data outside Git.
"""

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

REPO = Path(__file__).resolve().parents[3]
ORIGIN = "http://tauri.localhost"


def require(condition, step):
    if not condition:
        raise RuntimeError(step)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(REPO), *args], text=True, encoding="utf-8"
    ).strip()


def guarded_output_parent(value):
    """Inspect ancestor metadata before resolve/mkdir can follow a redirect.

    Marker contents and existing operational data are never opened. Any marker
    entry (including a .git file for a worktree) protects its whole subtree.
    """
    raw = os.fspath(value)
    require(not raw.replace("\\", "/").startswith(("//", "/??/")), "output_local_path")
    path = Path(raw).absolute()
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        require(
            not stat.S_ISLNK(info.st_mode)
            and not getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            "output_no_reparse",
        )
        for name in (".git", ".cafe-fin-root.json"):
            try:
                (component / name).lstat()
            except FileNotFoundError:
                continue
            raise RuntimeError("output_outside_protected_root")
    resolved = path.resolve()
    require(not resolved.is_relative_to(REPO), "output_outside_repository")
    return resolved


def verify_attestation(binary, receipt, source_commit):
    """Check the builder's explicit source/hash claim before executing the file.

    The receipt is a trusted build input, not a cryptographic proof of compilation.
    Do not fabricate one by hashing an unknown executable to make a test run.
    """
    require(receipt.stat().st_size <= 65536, "attestation_size")
    data = json.loads(receipt.read_text(encoding="utf-8-sig"))
    require(
        type(data.get("schema_version")) is int and data["schema_version"] == 1,
        "attestation_schema",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "source_commit")
    require(data.get("source_commit") == source_commit, "attestation_source")
    artifact = data.get("sidecar", {})
    require(artifact.get("filename") == binary.name, "attestation_filename")
    require(
        type(artifact.get("bytes")) is int and artifact["bytes"] == binary.stat().st_size,
        "attestation_bytes",
    )
    actual = sha256(binary)
    require(artifact.get("sha256") == actual, "attestation_hash")
    return {
        "source_commit": source_commit,
        "filename": binary.name,
        "bytes": binary.stat().st_size,
        "sha256": actual,
        "attestation_sha256": sha256(receipt),
        "binding": "builder_attestation_verified_against_file",
    }


class Sidecar:
    def __init__(self, data_root, binary=None, *, initialize=True):
        self.token = secrets.token_urlsafe(40)
        self.process = None
        self.root, self.binary, self.initialize = data_root, binary, initialize
        self.stderr_bytes = 0
        self.stderr_hash = hashlib.sha256()

    def __enter__(self):
        if __package__:
            from .process_tree import launch_private
        else:
            from process_tree import launch_private

        environment = dict(os.environ)
        environment["CAFE_FIN_MARKET_NETWORK"] = "0"
        if self.binary:
            environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                environment.pop(name, None)
            command = [str(self.binary)]
        else:
            environment["PYTHONPATH"] = str(REPO / "backend")
            command = [sys.executable, "-m", "cafe_fin"]
        self.process = launch_private(command, cwd=str(self.root.parent), env=environment)
        self.stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self.stderr_thread.start()
        messages = queue.Queue(maxsize=1)

        def read_boot():
            messages.put(self.process.stdout.readline(16385))

        threading.Thread(target=read_boot, daemon=True).start()
        try:
            self.send(
                {
                    "protocol_version": 1,
                    "session_token": self.token,
                    "data_root": str(self.root),
                    "initialize": self.initialize,
                    "allowed_origin": ORIGIN,
                }
            )
            line = messages.get(timeout=40)
            require(len(line) <= 16384, "boot_frame_bound")
            boot = json.loads(line)
            require(boot.get("status") == "ready", "boot_ready")
            endpoint = urlsplit(boot.get("api_base", ""))
            require(
                endpoint.scheme == "http"
                and endpoint.hostname == "127.0.0.1"
                and endpoint.port is not None
                and endpoint.path == "/api/v1"
                and not endpoint.query
                and not endpoint.fragment
                and endpoint.username is None
                and endpoint.password is None,
                "boot_loopback_endpoint",
            )
            self.api_base = boot["api_base"]
            return self
        except BaseException:
            self._cleanup()
            raise

    def _drain_stderr(self):
        while chunk := self.process.stderr.read(4096):
            self.stderr_bytes += len(chunk)
            self.stderr_hash.update(chunk)

    def send(self, frame):
        self.process.stdin.write(json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def _cleanup(self):
        self.process.close_tree(timeout=10)
        self.stderr_thread.join(timeout=2)
        require(not self.stderr_thread.is_alive(), "stderr_reader_stopped")
        self._close_streams()

    def _close_streams(self):
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self.process.poll() is None:
                self.send({"command": "shutdown"})
                self.process.wait(timeout=25)
        finally:
            self._cleanup()
        if exc_type is None:
            require(self.process.returncode == 0, "sidecar_clean_exit")
            require(self.stderr_bytes == 0, "sidecar_stderr_empty")


class RecordsHTTP:
    def __init__(self, sidecar, *, password, initialize):
        self.last_request = None
        self.client = httpx.Client(
            base_url=sidecar.api_base + "/",
            timeout=15,
            trust_env=False,
            headers={"X-App-Session": sidecar.token, "Origin": ORIGIN},
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    health = self.client.get("health")
                    if health.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                require(time.monotonic() < deadline, "http_ready")
                time.sleep(0.05)
            require(health.json()["setup_required"] is initialize, "setup_state")
            require(
                self.client.get("health", headers={"X-App-Session": ""}).status_code == 401,
                "session_auth_guard",
            )
            result = self.client.post(
                "auth/setup" if initialize else "auth/login",
                json={"username": "records-desktop-synthetic", "password": password},
            )
            require(result.status_code == 200, "local_auth")
            self.client.headers["Authorization"] = "Bearer " + result.json()["access_token"]
        except BaseException:
            self.client.close()
            raise

    def request(self, method, path, *, data=None, params=None):
        require(
            not path.startswith("/") and ":" not in path and ".." not in path,
            "records_relative_path",
        )
        self.last_request = {"method": method, "path": path}
        response = self.client.request(method, "records/" + path, json=data, params=params)
        self.last_request["status"] = response.status_code
        return response

    def stock(self):
        result = self.request(
            "GET",
            "stock-balances",
            params={
                "from_on": "2026-01-01",
                "through_on": "2026-12-31",
            },
        )
        require(result.status_code == 200, "stock_read")
        data = result.json()
        data.pop("cutoff", None)
        return data


def run(output_parent, binary=None, receipt=None):
    require(__debug__, "assertions_required")
    if __package__:
        from .scenario import exercise
    else:
        from scenario import exercise

    output_parent = guarded_output_parent(output_parent)
    output_parent.mkdir(parents=True, exist_ok=True)
    guarded_output_parent(output_parent)
    output = Path(tempfile.mkdtemp(prefix="records-desktop-", dir=output_parent))
    report = {
        "schema_version": 1,
        "status": "FAIL",
        "evidence_kind": "frozen_sidecar_http" if binary else "source_sidecar_http",
        "source_commit": git("rev-parse", "HEAD"),
        "tracked_worktree_clean": not bool(git("status", "--porcelain", "--untracked-files=no")),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine": {
            "os": platform.platform(),
            "architecture": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "harness_python": platform.python_version(),
        },
        "network_gate": "CAFE_FIN_MARKET_NETWORK=0",
        "native_gui": "NOT RUN",
        "clean_windows_pc2": "NOT RUN",
        "live_market": "NOT RUN; offline synthetic scenario",
        "data_root": str(output / "Dữ liệu tổng hợp"),
        "harness_inputs": {
            path.name: sha256(path)
            for path in (Path(__file__), Path(__file__).with_name("scenario.py"))
        },
    }
    try:
        if binary:
            require(report["tracked_worktree_clean"], "frozen_requires_clean_tracked_source")
            report["artifact"] = verify_attestation(binary, receipt, report["source_commit"])
        password = secrets.token_urlsafe(32)
        root = Path(report["data_root"])
        with Sidecar(root, binary) as sidecar:
            api = RecordsHTTP(sidecar, password=password, initialize=True)
            try:
                report["scenario"] = exercise(api, occurred_on="2026-11-08")
                before = api.stock()
            finally:
                api.client.close()
        if binary:
            verify_attestation(binary, receipt, report["source_commit"])
        with Sidecar(root, binary, initialize=False) as sidecar:
            api = RecordsHTTP(sidecar, password=password, initialize=False)
            try:
                require(api.stock() == before, "restart_stock_persistence")
            finally:
                api.client.close()
        report["restart_stock_persistence"] = "PASS"
        report["clean_shutdown_twice"] = "PASS"
        report["status"] = "PASS"
    except Exception as exc:
        # Never serialize arbitrary HTTP responses, boot frames, paths or secrets.
        report["failure_type"] = type(exc).__name__
        if type(exc) is RuntimeError and re.fullmatch(r"[a-z_]+", str(exc)):
            report["failure_step"] = str(exc)
        if "api" in locals():
            report["last_request"] = api.last_request
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        destination = output / "report.json"
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(destination)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--sidecar", type=Path)
    parser.add_argument("--attestation", type=Path)
    args = parser.parse_args()
    if bool(args.sidecar) != bool(args.attestation):
        parser.error("--sidecar and --attestation must be supplied together")
    raise SystemExit(
        run(
            args.output_parent,
            args.sidecar.resolve() if args.sidecar else None,
            args.attestation.resolve() if args.attestation else None,
        )
    )
