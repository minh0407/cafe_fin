"""Actual HTTP/container smoke on an already-running disposable preview project.

Run from any directory: python tests/preview/docker_smoke.py --project cafe-fin-preview-smoke
The caller starts/stops the project. This script only restarts its verified service;
it never creates/removes containers, volumes or files. Credentials stay in memory.
Requires Python 3.10+ and Docker Compose CLI; no installed application packages.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import re
import secrets
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from uuid import uuid4

ORIGIN = "http://127.0.0.1:1420"
PROJECT = "cafe-fin-preview-smoke"
ROOT = Path(__file__).resolve().parents[2]
DAY = "2026-11-06"
COLUMNS = [
    {"id": "code", "name": "Code", "kind": "text", "required": True},
    {"id": "day", "name": "Day", "kind": "date", "required": True},
    {"id": "received", "name": "Cash received", "kind": "money", "required": True},
    {"id": "paid", "name": "Cash paid", "kind": "money", "required": True},
]


class SmokeFailure(Exception):
    """Only fixed diagnostic codes may reach stdout/stderr."""


def check(condition, code):
    if not condition:
        raise SmokeFailure(code)


def key():
    return str(uuid4())


def docker(*args):
    result = subprocess.run(
        ["docker", *args], cwd=ROOT, capture_output=True, timeout=90, check=False
    )
    check(result.returncode == 0, "DOCKER_COMMAND")
    return result.stdout.decode("utf-8")


def compose(*args):
    return docker("compose", "-f", str(ROOT / "compose.preview.yaml"), "-p", PROJECT, *args)


def verify_container():
    """Bind the destructive boundary to a single exact disposable project."""
    ids = compose("ps", "-q", "cafe-fin").split()
    check(len(ids) == 1, "SMOKE_CONTAINER_COUNT")
    item = json.loads(docker("inspect", ids[0]))[0]
    labels = item["Config"]["Labels"]
    check(labels.get("com.docker.compose.project") == PROJECT, "SMOKE_PROJECT_LABEL")
    check(labels.get("com.docker.compose.service") == "cafe-fin", "SMOKE_SERVICE_LABEL")
    check(item["State"]["Running"], "SMOKE_CONTAINER_STOPPED")
    bindings = item["NetworkSettings"]["Ports"].get("1420/tcp")
    check(bindings == [{"HostIp": "127.0.0.1", "HostPort": "1420"}], "LOOPBACK_BINDING")
    mounts = [mount for mount in item["Mounts"] if mount["Destination"] == "/data"]
    check(len(mounts) == 1, "SMOKE_DATA_MOUNT")
    check(mounts[0].get("Name") == PROJECT + "_preview-data", "SMOKE_VOLUME_NAME")
    check(item["HostConfig"]["ReadonlyRootfs"], "READONLY_CONTAINER")
    networks = item["NetworkSettings"]["Networks"]
    check(list(networks) == [PROJECT + "_preview-local"], "SMOKE_NETWORK")
    network = json.loads(docker("network", "inspect", PROJECT + "_preview-local"))[0]
    check(network["Internal"] is True, "NO_WAN_NETWORK")
    # This executes no secret reads/writes, and prints only the boolean/platform assertion.
    code = (
        "import sys; from cafe_fin.core.secrets import WindowsCredentialStore; "
        "assert sys.platform == 'linux'; assert WindowsCredentialStore().available is False"
    )
    docker("exec", ids[0], "python", "-c", code)
    return ids[0]


class Client:
    def __init__(self):
        self.headers = {"Origin": ORIGIN}

    def raw(self, method, path, *, headers=None, body=None, expected=200):
        connection = http.client.HTTPConnection("127.0.0.1", 1420, timeout=40)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            content = response.read()
            received = {name.lower(): value for name, value in response.getheaders()}
            check(response.status == expected, "HTTP_STATUS")
            check(received.get("cache-control") == "no-store", "NO_STORE")
            check(received.get("x-content-type-options") == "nosniff", "NOSNIFF")
            check(not any(name.startswith("access-control-") for name in received), "NO_CORS")
            return content, received
        finally:
            connection.close()

    def call(self, method, path, payload=None, *, expected=200):
        headers = dict(self.headers)
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        content, _ = self.raw(
            method, "/api/v1" + path, headers=headers, body=body, expected=expected
        )
        return json.loads(content)

    def bootstrap(self):
        content, _ = self.raw(
            "POST",
            "/preview/bootstrap",
            headers={"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "X-Preview-Bootstrap": "1"},
        )
        boot = json.loads(content)
        check(
            set(boot)
            == {"protocol_version", "api_base", "session_token", "data_root", "runtime_state"},
            "BOOT_SCHEMA",
        )
        check(boot["api_base"] == ORIGIN + "/api/v1", "BOOT_BASE")
        check(len(boot["session_token"]) >= 32, "BOOT_CAPABILITY")
        self.headers = {"Origin": ORIGIN, "X-App-Session": boot["session_token"]}

    def download(self, path, digest=None):
        body, headers = self.raw("GET", "/api/v1" + path, headers=self.headers)
        check(bool(body), "EMPTY_EXPORT")
        expected_hash = digest or headers.get("x-content-sha256")
        if expected_hash:
            check(hashlib.sha256(body).hexdigest() == expected_hash, "EXPORT_HASH")
        return body

    def upload(self, body):
        content, _ = self.raw(
            "POST",
            "/api/v1/files",
            headers=self.headers
            | {
                "X-File-Name": "synthetic-smoke.csv",
                "X-Request-Key": key(),
                "Content-Type": "application/octet-stream",
            },
            body=body,
        )
        return json.loads(content)

    def batch(self, identity):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            batch = self.call("GET", f"/accounting/import-jobs/{identity}")
            state = batch.get("job", {}).get("state")
            check(state not in {"FAILED", "CANCELLED", "RECOVERABLE"}, "IMPORT_JOB_FAILED")
            if state == "COMPLETED" and batch["state"] not in {
                "UPLOADED",
                "PARSING",
                "VALIDATING",
                "COMMITTING",
            }:
                return batch
            time.sleep(0.2)
        raise SmokeFailure("IMPORT_TIMEOUT")


def guards(client):
    client.raw("GET", "/")
    client.raw("GET", "/api/v1/health", expected=401)
    for headers, status in [
        ({}, 403),
        ({"Host": "localhost:1420", "X-Preview-Bootstrap": "1"}, 400),
        ({"Origin": "https://evil.example", "X-Preview-Bootstrap": "1"}, 403),
        ({"X-Preview-Bootstrap": "0"}, 403),
        ({"X-Preview-Bootstrap": "1", "Sec-Fetch-Site": "cross-site"}, 403),
    ]:
        content, _ = client.raw("POST", "/preview/bootstrap", headers=headers, expected=status)
        check(b"session_token" not in content, "BOOT_DENIAL_LEAK")
    client.raw(
        "POST",
        "/preview/bootstrap?token=forbidden",
        headers={"X-Preview-Bootstrap": "1"},
        expected=403,
    )
    client.bootstrap()
    client.call("GET", "/auth/me", expected=401)


def no_telegram(client):
    settings = client.call("GET", "/reporting/settings")
    check(settings["credential_store_available"] is False, "LINUX_SECRET_STORE")
    check(settings["credential_configured"] is False, "UNCONFIGURED_CREDENTIALS")
    check(settings["sender_status"] == "UNCONFIGURED", "UNCONFIGURED_SENDER")
    check("bot_token" not in settings, "SETTINGS_SECRET_LEAK")
    check(
        client.call("POST", "/reporting/connection-check", {"request_key": key()})
        == {"state": "UNCONFIGURED", "code": "TELEGRAM_UNCONFIGURED"},
        "UNCONFIGURED_CHECK",
    )


def scenario(client):
    product = client.call(
        "POST",
        "/records/products",
        {"code": "SMOKE-COFFEE", "name": "Synthetic coffee", "request_key": key()},
    )
    warehouse = client.call(
        "POST",
        "/records/products/warehouses",
        {"code": "SMOKE-WAREHOUSE", "name": "Synthetic warehouse", "request_key": key()},
    )

    def entry(quantity, kind):
        return {
            "code": key(),
            "occurred_on": DAY,
            "entry_type": kind,
            "status": "posted",
            "note": "Synthetic smoke basis",
            "request_key": key(),
            "lines": [
                {
                    "product_id": product["id"],
                    "warehouse_id": warehouse["id"],
                    "quantity_kg": quantity,
                    "direction": "out" if kind == "issue" else "in",
                }
            ],
        }

    payload = entry("10.000", "receipt")
    receipt = client.call("POST", "/records/entries", payload)
    check(
        client.call("POST", "/records/entries", payload)["id"] == receipt["id"], "ENTRY_IDEMPOTENCY"
    )
    issue = client.call("POST", "/records/entries", entry("3.000", "issue"))
    denied = client.call("POST", "/records/entries", entry("8.000", "issue"), expected=409)
    check(denied["error"]["code"] == "STOCK_NEGATIVE", "NEGATIVE_STOCK_CREATE")
    denied = client.call(
        "DELETE",
        f"/records/entries/{receipt['id']}",
        {"expected_version": receipt["version"], "request_key": key()},
        expected=409,
    )
    check(denied["error"]["code"] == "STOCK_NEGATIVE", "NEGATIVE_STOCK_DELETE")
    book = client.call(
        "POST",
        "/accounting/books",
        {
            "name": "Independent synthetic smoke book",
            "columns": COLUMNS,
            "semantics": {
                "date_column": "day",
                "income_column": "received",
                "expense_column": "paid",
                "metric_meanings": {"income": "cash_receipts", "expense": "cash_payments"},
            },
            "request_key": key(),
        },
    )
    row = client.call(
        "POST",
        f"/accounting/books/{book['id']}/rows",
        {
            "values": {"code": "MANUAL", "day": DAY, "received": "10.00", "paid": "2.00"},
            "request_key": key(),
        },
    )
    original = b"code,day,received,paid\nI001,2026-11-06,1.11,0\nI002,2026-11-06,2.22,0\nI003,2026-11-06,bad,0\n"
    source = client.upload(original)
    check(client.download(f"/files/{source['id']}/content") == original, "IMMUTABLE_ORIGINAL")
    batch = client.call(
        "POST",
        "/accounting/import-jobs",
        {"book_id": book["id"], "file_id": source["id"], "request_key": key()},
    )
    batch = client.batch(batch["id"])
    batch = client.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/mapping",
        {
            "expected_version": batch["version"],
            "mapping": {"code": "A", "day": "B", "received": "C", "paid": "D"},
            "request_key": key(),
        },
    )
    client.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/validate",
        {"expected_version": batch["version"], "request_key": key()},
    )
    batch = client.batch(batch["id"])
    check(
        batch["counts"]["source_rows"] == 3 and batch["counts"]["invalid"] == 1, "IMPORT_VALIDATION"
    )
    confirm = {
        "expected_version": batch["version"],
        "staging_revision": batch["revision"],
        "mapping_revision": batch["mapping_revision"],
        "decision_revision": batch["decision_revision"],
        "validation_token": batch["validation_token"],
        "mode": "valid_rows_only",
        "request_key": key(),
    }
    client.call("POST", f"/accounting/import-jobs/{batch['id']}/confirm", confirm)
    batch = client.batch(batch["id"])
    check(batch["state"] == "PARTIALLY_COMMITTED", "IMPORT_PARTIAL_STATE")
    check(
        batch["counts"]["published_rows"] == 2 and batch["counts"]["pending"] == 0,
        "IMPORT_PUBLISHED_COUNTS",
    )
    client.call("POST", f"/accounting/import-jobs/{batch['id']}/confirm", confirm)
    check(
        client.call("GET", f"/accounting/books/{book['id']}/rows")["total"] == 3,
        "IMPORT_RETRY_DUPLICATION",
    )
    report = client.call(
        "POST",
        "/reporting/reports/preview",
        {
            "from_on": DAY,
            "through_on": DAY,
            "book_ids": [book["id"]],
            "reason": "Synthetic actual-container smoke",
            "request_key": key(),
        },
    )
    snapshot = report["snapshot"]
    check(
        snapshot["sources"]["inventory"]["items"][0]["closing_kg"] == "7.000",
        "ACCOUNTING_STOCK_INDEPENDENCE",
    )
    metrics = snapshot["sources"]["books"][0]["metrics"]
    check(
        next(m["amount_vnd"] for m in metrics if m["meaning"] == "cash_receipts") == "13.33",
        "ACCOUNTING_TOTAL",
    )
    report = client.call(
        "POST",
        f"/reporting/reports/{report['id']}/save",
        {"expected_version": report["version"], "request_key": key()},
    )
    exports = []
    for format_ in ("txt", "pdf"):
        exported = client.call(
            "POST",
            f"/reporting/reports/{report['id']}/exports",
            {"format": format_, "request_key": key()},
        )
        check(exported["local_export"]["state"] == "READY", "REPORT_LOCAL_COPY")
        body = client.download(
            f"/reporting/reports/{report['id']}/exports/{exported['id']}/content",
            exported["sha256"],
        )
        check(format_ != "pdf" or body.startswith(b"%PDF-"), "REPORT_PDF")
        exports.append(exported)
    template = next(
        t for t in client.call("GET", "/contracts/templates")["items"] if t["kind"] == "purchase"
    )
    contract = client.call(
        "POST",
        "/contracts",
        {
            "request_key": key(),
            "data": {
                "kind": "purchase",
                "number": "SYNTHETIC-SMOKE",
                "occurred_on": DAY,
                "template_id": template["id"],
                "company": {"type": "company", "name": "Synthetic company"},
                "counterparty": {"type": "person", "name": "Synthetic party"},
                "lines": [
                    {
                        "description": "Synthetic coffee",
                        "quantity_kg": "9.001",
                        "unit_price": "10.00",
                    }
                ],
                "tax": {"mode": "none"},
                "payment": {"method": "cash", "recorded_paid_amount": "90.01"},
                "terms": {"additional": "Synthetic additional terms"},
            },
        },
    )
    version = client.call(
        "POST",
        f"/contracts/{contract['id']}/exports",
        {"formats": ["docx", "pdf"], "expected_version": contract["version"], "request_key": key()},
    )
    for format_ in ("docx", "pdf"):
        body = client.download(
            f"/contracts/{contract['id']}/versions/{version['id']}/files/{format_}",
            version["files"][format_]["sha256"],
        )
        check(
            body.startswith(b"%PDF-") if format_ == "pdf" else zipfile.is_zipfile(io.BytesIO(body)),
            "CONTRACT_FORMAT",
        )
    return {
        "product": product,
        "warehouse": warehouse,
        "receipt": receipt,
        "issue": issue,
        "book": book,
        "row": row,
        "source": source,
        "original": original,
        "batch": batch,
        "report": report,
        "exports": exports,
        "contract": contract,
        "contract_version": version,
    }


def persistence(client, state):
    for resource, name in (
        ("products", "product"),
        ("products/warehouses", "warehouse"),
        ("entries", "receipt"),
        ("entries", "issue"),
    ):
        check(
            client.call("GET", f"/records/{resource}/{state[name]['id']}")["id"]
            == state[name]["id"],
            "PERSIST_RECORD",
        )
    rows = client.call("GET", f"/accounting/books/{state['book']['id']}/rows")
    check(
        rows["total"] == 3 and state["row"]["id"] in {row["id"] for row in rows["items"]},
        "PERSIST_ROWS",
    )
    batch = client.call("GET", f"/accounting/import-jobs/{state['batch']['id']}")
    check(batch["counts"]["published_rows"] == 2, "PERSIST_IMPORT")
    check(
        client.download(f"/files/{state['source']['id']}/content") == state["original"],
        "PERSIST_ORIGINAL",
    )
    report = client.call("GET", f"/reporting/reports/{state['report']['id']}")
    check(report["sha256"] == state["report"]["sha256"], "PERSIST_REPORT_SNAPSHOT")
    for exported in state["exports"]:
        client.download(
            f"/reporting/reports/{report['id']}/exports/{exported['id']}/content",
            exported["sha256"],
        )
    version = state["contract_version"]
    for format_ in ("docx", "pdf"):
        client.download(
            f"/contracts/{state['contract']['id']}/versions/{version['id']}/files/{format_}",
            version["files"][format_]["sha256"],
        )
    balances = client.call("GET", f"/records/stock-balances?from_on={DAY}&through_on={DAY}")
    check(balances["items"][0]["closing_kg"] == "7.000", "PERSIST_STOCK")


def main():
    global PROJECT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        required=True,
        help="Disposable cafe-fin-preview-smoke or cafe-fin-preview-smoke-<suffix> project.",
    )
    args = parser.parse_args()
    check(
        re.fullmatch(r"cafe-fin-preview-smoke(?:-[a-z0-9-]{1,32})?", args.project),
        "SMOKE_PROJECT_ALLOWLIST",
    )
    PROJECT = args.project
    verify_container()
    client = Client()
    guards(client)
    check(client.call("GET", "/health")["setup_required"], "SMOKE_VOLUME_MUST_BE_FRESH")
    username, password = "smoke-admin", secrets.token_urlsafe(32)
    login = client.call("POST", "/auth/setup", {"username": username, "password": password})
    client.headers["Authorization"] = "Bearer " + login["access_token"]
    check(client.call("GET", "/auth/me")["role"] == "admin", "ADMIN_SETUP")
    no_telegram(client)
    print("PASS SECURITY_AUTH_LINUX", flush=True)
    state = scenario(client)
    print("PASS RECORDS_IMPORT_REPORT_CONTRACT", flush=True)
    old_headers = dict(client.headers)
    container_id = verify_container()
    compose("restart", "cafe-fin")
    deadline = time.monotonic() + 60
    while True:
        try:
            client.raw("GET", "/")
            break
        except (OSError, http.client.HTTPException):
            if time.monotonic() >= deadline:
                raise SmokeFailure("RESTART_TIMEOUT") from None
            time.sleep(0.3)
    check(verify_container() == container_id, "RESTART_CONTAINER_ID")
    client.raw("GET", "/api/v1/health", headers=old_headers, expected=401)
    client.bootstrap()
    check(client.headers["X-App-Session"] != old_headers["X-App-Session"], "CAPABILITY_ROTATION")
    check(client.call("GET", "/health")["setup_required"] is False, "PERSIST_ADMIN")
    login = client.call("POST", "/auth/login", {"username": username, "password": password})
    client.headers["Authorization"] = "Bearer " + login["access_token"]
    persistence(client, state)
    no_telegram(client)
    print("PASS RESTART_PERSISTENCE_NEW_CAPABILITY", flush=True)
    print("PASS DOCKER_HTTP_SMOKE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SmokeFailure as error:
        print("FAIL " + str(error), flush=True)
        sys.exit(1)
    except Exception:
        # Exception repr/response bodies can contain credentials; never print them.
        print("FAIL SMOKE_INTERNAL", flush=True)
        sys.exit(1)
