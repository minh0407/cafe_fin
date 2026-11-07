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
PORT = 1420
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


def service_container(service):
    ids = compose("ps", "-q", service).split()
    check(len(ids) == 1, "SMOKE_CONTAINER_COUNT")
    item = json.loads(docker("inspect", ids[0]))[0]
    labels = item["Config"]["Labels"]
    check(labels.get("com.docker.compose.project") == PROJECT, "SMOKE_PROJECT_LABEL")
    check(labels.get("com.docker.compose.service") == service, "SMOKE_SERVICE_LABEL")
    check(item["State"]["Running"], "SMOKE_CONTAINER_STOPPED")
    check(item["Config"]["User"].split(":")[0] not in {"", "0", "root"}, "NONROOT_CONTAINER")
    check(item["HostConfig"]["ReadonlyRootfs"], "READONLY_CONTAINER")
    check(item["HostConfig"]["CapDrop"] == ["ALL"], "CAP_DROP_ALL")
    check("no-new-privileges:true" in item["HostConfig"]["SecurityOpt"], "NO_NEW_PRIVILEGES")
    return ids[0], item


def verify_container():
    """Bind the restart boundary to the private backend of this disposable project."""
    backend_id, item = service_container("cafe-fin")
    check(not item["HostConfig"].get("PortBindings"), "BACKEND_PRIVATE_PORT")
    check(not any(item["NetworkSettings"]["Ports"].values()), "BACKEND_PRIVATE_BINDING")
    mounts = [mount for mount in item["Mounts"] if mount["Destination"] == "/data"]
    check(len(mounts) == 1, "SMOKE_DATA_MOUNT")
    check(mounts[0].get("Name") == PROJECT + "_preview-data", "SMOKE_VOLUME_NAME")
    networks = item["NetworkSettings"]["Networks"]
    check(list(networks) == [PROJECT + "_preview-local"], "SMOKE_NETWORK")
    network = json.loads(docker("network", "inspect", PROJECT + "_preview-local"))[0]
    check(network["Internal"] is True, "NO_WAN_NETWORK")
    # This executes no secret reads/writes, and prints only the boolean/platform assertion.
    code = (
        "import sys; from cafe_fin.core.secrets import WindowsCredentialStore; "
        "assert sys.platform == 'linux'; assert WindowsCredentialStore().available is False"
    )
    docker("exec", backend_id, "python", "-c", code)
    gateway_id, gateway = service_container("gateway")
    bindings = {
        port: binding for port, binding in gateway["NetworkSettings"]["Ports"].items() if binding
    }
    check(
        bindings == {"1420/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(PORT)}]},
        "LOOPBACK_GATEWAY_BINDING",
    )
    check(
        set(gateway["NetworkSettings"]["Networks"])
        == {PROJECT + "_preview-front", PROJECT + "_preview-local"},
        "GATEWAY_NETWORKS",
    )
    front = json.loads(docker("network", "inspect", PROJECT + "_preview-front"))[0]
    check(front["Internal"] is False and front["Driver"] == "bridge", "GATEWAY_FRONT_NETWORK")
    check(gateway["Config"]["User"] == "101:101", "GATEWAY_USER")
    check(all(mount["Type"] == "tmpfs" for mount in gateway["Mounts"]), "GATEWAY_NO_DATA_MOUNTS")
    check(gateway["Config"]["Entrypoint"] == ["nginx"], "GATEWAY_ENTRYPOINT")
    check(
        gateway["Config"]["Cmd"] == ["-c", "/etc/nginx/preview.conf", "-g", "daemon off;"],
        "GATEWAY_FIXED_COMMAND",
    )
    expected_config = hashlib.sha256((ROOT / "scripts/preview/nginx.conf").read_bytes()).hexdigest()
    actual_config = docker("exec", gateway_id, "sha256sum", "/etc/nginx/preview.conf").split()[0]
    check(actual_config == expected_config, "GATEWAY_FIXED_CONFIG")
    return backend_id


class Client:
    def __init__(self):
        self.headers = {"Origin": ORIGIN}

    def ready(self):
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        try:
            connection.request("GET", "/", headers={"Host": "127.0.0.1:1420"})
            response = connection.getresponse()
            response.read()
            check(response.status in {200, 502, 503}, "RESTART_HTTP_STATUS")
            if response.status == 200:
                self.raw("GET", "/")
                return True
            return False
        finally:
            connection.close()

    def raw(self, method, path, *, headers=None, body=None, expected=200):
        connection = http.client.HTTPConnection("127.0.0.1", PORT, timeout=40)
        try:
            connection.request(method, path, body=body, headers={"Host": "127.0.0.1:1420", **(headers or {})})
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


def commerce_scenario(client, state):
    farm = client.call("POST", "/records/parties", {
        "request_key": key(), "code": "T001", "name": "Synthetic farm",
        "roles": ["supplier"], "profile_kind": "farm",
        "farm": {"owner_name": "Synthetic owner", "owner_id_card": "0000123",
                 "official_area_code": "SYNTHETIC-AREA", "plots": [],
                 "surveys": [{"season_year": 2026, "grade": 3, "ripeness_pct": "90.125"}]},
    })
    company = client.call("POST", "/records/parties", {
        "request_key": key(), "code": "TEST-COMPANY", "name": "Synthetic customer company",
        "roles": ["customer"], "profile_kind": "customer_company", "tax_code": "SYNTHETIC-MST",
        "representative": {"name": "Synthetic contact"}, "business_license": "SYNTHETIC-LICENSE",
    })
    product_id, warehouse_id = state["product"]["id"], state["warehouse"]["id"]
    trades = {}
    for direction, price in (("inbound", "90.00"), ("outbound", "100.01")):
        trade = client.call("POST", "/records/trades", {
            "request_key": key(), "code": key(), "occurred_on": DAY, "direction": direction,
            "party_id": company["id"] if direction == "outbound" else None,
            "vehicle_plate": "SYNTHETIC-PLATE", "lines": [{
                "farm_id": farm["id"] if direction == "inbound" else None,
                "product_id": product_id, "quantity_kg": "2.000", "unit_price_vnd": price,
                "bag_count": 1, "grade": 3,
            }],
        })
        payment = {"request_key": key(), "code": key(), "occurred_on": DAY,
                   "trade_id": trade["id"], "party_id": company["id"] if direction == "outbound" else farm["id"],
                   "amount_vnd": "45.67" if direction == "outbound" else "12.34", "method": "cash"}
        saved = client.call("POST", "/records/trade-payments", payment)
        check(client.call("POST", "/records/trade-payments", payment)["id"] == saved["id"], "PAYMENT_RETRY")
        client.call("POST", "/records/entries", {
            "request_key": key(), "code": key(), "occurred_on": DAY,
            "entry_type": "issue" if direction == "outbound" else "receipt", "status": "posted",
            "party_id": company["id"] if direction == "outbound" else farm["id"], "trade_id": trade["id"],
            "lines": [{"product_id": product_id, "warehouse_id": warehouse_id,
                       "quantity_kg": "2.000", "direction": "out" if direction == "outbound" else "in"}],
        })
        trades[direction] = trade
    denied = client.call("POST", "/records/entries", {
        "request_key": key(), "code": key(), "occurred_on": DAY, "entry_type": "issue", "status": "posted",
        "party_id": company["id"], "trade_id": trades["outbound"]["id"],
        "lines": [{"product_id": product_id, "warehouse_id": warehouse_id, "quantity_kg": "0.001", "direction": "out"}],
    }, expected=409)
    check(denied["error"]["code"] == "TRADE_CONFLICT", "TRADE_SHIPMENT_CAP")
    dashboard = client.call("GET", f"/records/records-dashboard?from_on={DAY}&through_on={DAY}")
    check(dashboard["counts"] == {"farms": 1, "farm_surveys": 1, "customer_companies": 1,
                                  "inbound_trades": 1, "outbound_trades": 1}, "DASHBOARD_COUNTS")
    check(dashboard["period"]["cash_in_vnd"] == "45.67" and dashboard["period"]["cash_out_vnd"] == "12.34", "DASHBOARD_CASH_SOURCE")
    check(dashboard["period"]["inbound_kg"] == "12.000" and dashboard["period"]["outbound_kg"] == "5.000", "DASHBOARD_STOCK_SOURCE")
    check(dashboard["period"]["sales_order_value_vnd"] == "200.02", "DASHBOARD_TRADE_VALUE")
    state["commerce"] = {"farm": farm, "company": company, "trades": trades}
    print("PASS FARM_COMPANY_TRADES_PAYMENTS_DASHBOARD", flush=True)


def commerce_persistence(client, state):
    farm = client.call("GET", f"/records/parties/{state['commerce']['farm']['id']}")
    check(farm["code"] == "T001" and farm["farm"]["owner_id_card"] == "0000123", "PERSIST_FARM_PROFILE")
    for trade in state["commerce"]["trades"].values():
        check(client.call("GET", f"/records/trades/{trade['id']}")["version"] == 1, "PERSIST_TRADE")
    dashboard = client.call("GET", f"/records/records-dashboard?from_on={DAY}&through_on={DAY}")
    check(dashboard["period"]["cash_in_vnd"] == "45.67", "PERSIST_TRADE_PAYMENT")


def pricing_scenario(client, state):
    product_id = state["product"]["id"]
    preview = client.call("POST", "/records/price-board-preview", {
        "pricing_method": "grade", "grade5_price_vnd": "100.01",
    })
    grades = {row["grade"]: row["unit_price_vnd"] for row in preview["grade_prices"]}
    check(grades == {5: "100.01", 4: "90.01", 3: "81.01", 2: "72.91", 1: "65.62"}, "GRADE_STEP_HALF_UP")
    board = client.call("POST", "/records/price-boards", {
        "request_key": key(), "price_date": DAY, "price_kind": "purchase_fresh",
        "pricing_method": "grade", "grade5_price_vnd": "100.01",
    })
    client.call("POST", "/records/price-boards", {
        "request_key": key(), "price_date": DAY, "price_kind": "purchase_processed",
        "pricing_method": "flat", "flat_price_vnd": "120.00",
    })
    sale_input = {"price_date": DAY, "price_kind": "sale", "product_id": product_id,
                  "pricing_method": "flat", "flat_price_vnd": "150.01"}
    sale_board = client.call("POST", "/records/price-boards", {**sale_input, "request_key": key()})
    purchase = client.call("GET", f"/records/price-quote?price_kind=purchase_fresh&price_date={DAY}&product_id={product_id}&grade=3")
    sale = client.call("GET", f"/records/price-quote?price_kind=sale&price_date={DAY}&product_id={product_id}")
    check(purchase["unit_price_vnd"] == "81.01" and sale["unit_price_vnd"] == "150.01", "SEPARATE_PURCHASE_SALE_QUOTES")
    missing = client.call("GET", "/records/price-quote?price_kind=purchase_fresh&price_date=2026-11-07&grade=3", expected=422)
    check(missing["error"]["code"] == "PRICE_NOT_FOUND", "NO_PREVIOUS_DAY_PRICE_FALLBACK")
    trades = {}
    for direction, quote in (("inbound", purchase), ("outbound", sale)):
        trades[direction] = client.call("POST", "/records/trades", {
            "request_key": key(), "code": key(), "occurred_on": DAY, "direction": direction,
            "party_id": state["commerce"]["company"]["id"] if direction == "outbound" else None,
            "lines": [{"farm_id": state["commerce"]["farm"]["id"] if direction == "inbound" else None,
                       "product_id": product_id, "quantity_kg": "1.001", "grade": 3 if direction == "inbound" else None,
                       "pricing_mode": "daily", "price_kind": quote["price_kind"], "price_snapshot": quote}],
        })
        check(trades[direction]["lines"][0]["unit_price_vnd"] == quote["unit_price_vnd"], "SERVER_AUTO_PRICE_FROM_KG")
    changed_board = client.call("PUT", f"/records/price-boards/{sale_board['id']}", {
        **sale_input, "flat_price_vnd": "160.01", "expected_version": sale_board["version"], "request_key": key(),
    })
    outbound = trades["outbound"]
    trade_fields = ("code", "occurred_on", "occurred_at", "physical_actor", "party_id", "direction", "status", "vehicle_plate", "weighing_id", "note", "lines")
    stale_input = {name: outbound[name] for name in trade_fields if name in outbound}
    stale_input["code"] = key()
    stale = client.call("POST", "/records/trades", {**stale_input, "request_key": key()}, expected=409)
    check(stale["error"]["code"] == "PRICE_CHANGED", "STALE_PRICE_BLOCKED")
    changed_lines = [dict(line) for line in outbound["lines"]]
    changed_lines[0]["quantity_kg"] = "2.001"
    outbound = client.call("PUT", f"/records/trades/{outbound['id']}", {
        **{name: outbound[name] for name in trade_fields if name in outbound}, "lines": changed_lines,
        "expected_version": outbound["version"], "request_key": key(),
    })
    check(outbound["lines"][0]["unit_price_vnd"] == "150.01", "FROZEN_PRICE_AFTER_BOARD_UPDATE")
    client.call("DELETE", f"/records/price-boards/{sale_board['id']}", {
        "request_key": key(), "expected_version": changed_board["version"],
    })
    changed_lines[0]["quantity_kg"] = "3.001"
    outbound = client.call("PUT", f"/records/trades/{outbound['id']}", {
        **{name: outbound[name] for name in trade_fields if name in outbound}, "lines": changed_lines,
        "expected_version": outbound["version"], "request_key": key(),
    })
    check(outbound["lines"][0]["unit_price_vnd"] == "150.01", "FROZEN_PRICE_AFTER_BOARD_DELETE")
    state["pricing"] = {"purchase_board": board, "outbound": outbound}
    print("PASS DAILY_GRADE_SEPARATE_SALE_AUTO_PRICE_FROZEN_SNAPSHOT", flush=True)


def pricing_persistence(client, state):
    trade = state["pricing"]["outbound"]
    saved = client.call("GET", f"/records/trades/{trade['id']}")
    check(saved["lines"][0]["unit_price_vnd"] == "150.01" and saved["lines"][0]["price_snapshot"]["price_board_version"] == 1, "PERSIST_FROZEN_PRICE_SNAPSHOT")


def main():
    global PROJECT, PORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=1420,
        help="Host transport port for disposable HTTP smoke; protocol Host/Origin stays canonical 1420. Not a browser preview URL.",
    )
    parser.add_argument("--browser", action="store_true", help="Read-only production UI check on canonical port 1420.")
    parser.add_argument(
        "--project",
        required=True,
        help="Disposable cafe-fin-preview-smoke or cafe-fin-preview-smoke-<suffix> project.",
    )
    args = parser.parse_args()
    check(1024 <= args.port <= 65535, "SMOKE_PORT_RANGE")
    PORT = args.port
    check(not args.browser or PORT == 1420, "BROWSER_CANONICAL_PORT")
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
    commerce_scenario(client, state)
    pricing_scenario(client, state)
    print("PASS RECORDS_IMPORT_REPORT_CONTRACT", flush=True)
    old_headers = dict(client.headers)
    container_id = verify_container()
    compose("restart", "cafe-fin")
    deadline = time.monotonic() + 60
    while True:
        try:
            if client.ready():
                break
        except (OSError, http.client.HTTPException):
            pass
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
    commerce_persistence(client, state)
    pricing_persistence(client, state)
    no_telegram(client)
    print("PASS RESTART_PERSISTENCE_NEW_CAPABILITY", flush=True)
    if args.browser:
        result = subprocess.run(
            ["node", str(ROOT / "tests/preview/browser_crm.mjs")], cwd=ROOT,
            input=json.dumps({"project": PROJECT, "username": username, "password": password,
                              "outbound_id": state["commerce"]["trades"]["outbound"]["id"],
                              "priced_outbound_id": state["pricing"]["outbound"]["id"]}),
            text=True, capture_output=True, timeout=120, check=False,
        )
        if result.returncode != 0:
            diagnostic = re.search(r"FAIL DOCKER_PRODUCTION_BROWSER_CRM_NAVIGATION_([A-Za-z_]+)", result.stderr)
            raise SmokeFailure("PRODUCTION_BROWSER_CRM_" + (diagnostic.group(1) if diagnostic else "UNKNOWN"))
        print("PASS DOCKER_PRODUCTION_BROWSER_CRM_NAVIGATION", flush=True)
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
