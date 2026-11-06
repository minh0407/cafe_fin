"""Actual default registry: independent books, immutable contracts and atomic reporting."""

import csv
import hashlib
import io
import threading
import time
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as accounting_schema
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core import secrets
from cafe_fin.core.api import create_app
from cafe_fin.core.contracts import CONTRACT_VERSION
from cafe_fin.core.db import AUDIT, REQUESTS, Database, WriteCoordinator
from cafe_fin.core.imports import attempts, claims
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.runtime import Runtime
from cafe_fin.records.module import RecordsReadProvider
from cafe_fin.records.service import RecordsService
from fastapi.testclient import TestClient
from sqlalchemy import func, select

DAY = "2026-11-06"
COLUMNS = [
    {"id": "code", "name": "Code", "kind": "text", "required": True},
    {"id": "day", "name": "Day", "kind": "date", "required": True},
    {"id": "received", "name": "Cash received", "kind": "money", "required": True},
    {"id": "paid", "name": "Cash paid", "kind": "money", "required": True},
]


def key():
    return str(uuid4())


class Workflow:
    def __init__(self, runtime, client, headers, actor):
        self.runtime, self.client, self.headers, self.actor = runtime, client, headers, actor

    def call(self, method, path, *, role="admin", expected=200, **kwargs):
        response = self.client.request(
            method, "/api/v1" + path, headers=self.headers[role], **kwargs
        )
        assert response.status_code == expected, (response.status_code, response.text)
        return response.json()

    def book(self, *, known=True):
        semantics = {"date_column": "day", "income_column": "received", "expense_column": "paid"}
        if known:
            semantics["metric_meanings"] = {"income": "cash_receipts", "expense": "cash_payments"}
        return self.call(
            "POST",
            "/accounting/books",
            json={
                "name": "Independent synthetic cash book",
                "columns": COLUMNS,
                "semantics": semantics,
                "request_key": key(),
            },
        )

    def row(self, book, code, received, paid="0", day=DAY):
        return self.call(
            "POST",
            f"/accounting/books/{book['id']}/rows",
            json={
                "values": {"code": code, "day": day, "received": received, "paid": paid},
                "request_key": key(),
            },
        )

    def stock(self):
        product = self.call(
            "POST",
            "/records/products",
            json={
                "code": "INTEGRATION-COFFEE",
                "name": "Synthetic coffee",
                "request_key": key(),
            },
        )
        warehouse = self.call(
            "POST",
            "/records/products/warehouses",
            json={
                "code": "INTEGRATION-WAREHOUSE",
                "name": "Synthetic warehouse",
                "request_key": key(),
            },
        )
        return product, warehouse

    def entry(self, product, warehouse, amount, *, day=DAY, kind="receipt"):
        payload = {
            "code": key(),
            "occurred_on": day,
            "entry_type": kind,
            "status": "posted",
            "note": "Synthetic entered basis",
            "lines": [
                {
                    "product_id": product["id"],
                    "warehouse_id": warehouse["id"],
                    "quantity_kg": amount,
                    "direction": "out" if kind == "issue" else "in",
                }
            ],
        }
        return self.call("POST", "/records/entries", json=payload | {"request_key": key()}), payload

    def preview(self, books, *, first=DAY, last=DAY, role="admin"):
        return self.call(
            "POST",
            "/reporting/reports/preview",
            role=role,
            json={
                "from_on": first,
                "through_on": last,
                "book_ids": [book["id"] for book in books],
                "reason": "Synthetic integration capture",
                "request_key": key(),
            },
        )

    def export_rows(self, book):
        export = self.call(
            "POST",
            f"/accounting/books/{book['id']}/exports",
            json={
                "format": "csv",
                "request_key": key(),
            },
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = self.call("GET", f"/accounting/exports/{export['job_id']}")
            assert status["state"] not in {"FAILED", "CANCELLED", "RECOVERABLE"}, status
            if status["state"] == "COMPLETED" and status["file_id"]:
                content = self.client.get(
                    f"/api/v1/files/{status['file_id']}/content", headers=self.headers["admin"]
                )
                assert content.status_code == 200, content.text
                assert (
                    hashlib.sha256(content.content).hexdigest()
                    == content.headers["x-content-sha256"]
                )
                return list(csv.DictReader(io.StringIO(content.content.decode("utf-8-sig"))))
            threading.Event().wait(0.01)
        pytest.fail("actual accounting export did not complete")

    def wait_batch(self, identity, expected="COMPLETED"):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            batch = self.call("GET", f"/accounting/import-jobs/{identity}")
            state = batch.get("job", {}).get("state")
            if state == "COMPLETED" and batch["state"] in {
                "UPLOADED",
                "PARSING",
                "VALIDATING",
                "COMMITTING",
            }:
                threading.Event().wait(0.01)
                continue
            if state in {"COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"}:
                assert state == expected, batch
                return batch
            threading.Event().wait(0.01)
        pytest.fail("actual accounting import job did not reach terminal state")

    def confirm(self, batch):
        return self.call(
            "POST",
            f"/accounting/import-jobs/{batch['id']}/confirm",
            json={
                "expected_version": batch["version"],
                "staging_revision": batch["revision"],
                "mapping_revision": batch["mapping_revision"],
                "decision_revision": batch["decision_revision"],
                "validation_token": batch["validation_token"],
                "mode": "valid_rows_only",
                "request_key": key(),
            },
        )


@pytest.fixture
def workflow(tmp_path):
    # No synthetic registry/provider adapter: this is the app's default assembly.
    runtime = Runtime(tmp_path / "Cross-module dữ liệu mới", initialize=True)
    session = runtime.auth.setup("integration-admin", "synthetic-integration-password")
    actor = runtime.auth.authenticate(session["access_token"])
    operator = runtime.auth.create_user(
        actor,
        username="integration-operator",
        password="synthetic-operator-password",
        role="operator",
        request_key="integration-operator",
    )
    operator_session = runtime.auth.login("integration-operator", "synthetic-operator-password")
    common = {
        "X-App-Session": "synthetic-business-workflow-0123456789abcdef",
        "Origin": "http://tauri.localhost",
    }
    headers = {
        "admin": common | {"Authorization": "Bearer " + session["access_token"]},
        "operator": common | {"Authorization": "Bearer " + operator_session["access_token"]},
    }
    try:
        with TestClient(
            create_app(runtime, common["X-App-Session"], port=48964),
            base_url="http://127.0.0.1:48964",
            raise_server_exceptions=False,
        ) as client:
            result = Workflow(runtime, client, headers, actor)
            result.operator = operator
            yield result
    finally:
        runtime.close()


def metric(snapshot, book, meaning="cash_receipts"):
    source = next(row for row in snapshot["sources"]["books"] if row["book_id"] == book["id"])
    return next(row["amount_vnd"] for row in source["metrics"] if row["meaning"] == meaning)


def test_default_registry_dates_meanings_frozen_report_and_manual_contracts_without_side_effects(
    workflow,
):
    w = workflow
    assert {module.id for module in w.runtime.modules.ordered()} == {
        "example",
        "records",
        "contracts",
        "accounting",
        "reporting",
    }
    assert "reporting.tick" in w.runtime.periodic.tasks
    assert (
        "accounting.commit" in w.runtime.jobs.handlers
        and "reporting.dispatch" in w.runtime.jobs.handlers
    )
    product, warehouse = w.stock()
    w.entry(product, warehouse, "100.000", day="2026-11-05", kind="opening")
    receipt, receipt_payload = w.entry(product, warehouse, "20.001")
    w.entry(product, warehouse, "5.001", day="2026-11-07", kind="issue")
    book, unknown = w.book(), w.book(known=False)
    w.row(book, "before", "1000", day="2026-11-05")
    row = w.row(book, "first", "10.01", "2.01")
    w.row(book, "last", "20.02", "3.02", day="2026-11-07")
    w.row(book, "after", "9000", day="2026-11-08")
    w.row(unknown, "uninterpreted", "999.99")
    report = w.preview([book, unknown], last="2026-11-07")
    snapshot = report["snapshot"]
    assert snapshot["consistency"] == "atomic_read_snapshot"
    assert snapshot["bridge_contract_version"] == CONTRACT_VERSION
    assert snapshot["coverage"] == "entered_records_only" and snapshot["hold"] is None
    assert snapshot["period"]["from"] == "2026-11-05T17:00:00+00:00"
    assert snapshot["period"]["to"] == "2026-11-07T17:00:00+00:00"
    assert metric(snapshot, book) == "30.03" and metric(snapshot, book, "cash_payments") == "5.03"
    unknown_dto = next(
        item for item in snapshot["sources"]["books"] if item["book_id"] == unknown["id"]
    )
    assert all(item["meaning"] is None for item in unknown_dto["metrics"])
    assert "UNINTERPRETED_MONEY_METRICS" in snapshot["warnings"]
    stock = snapshot["sources"]["inventory"]["items"][0]
    assert (stock["opening_kg"], stock["received_kg"], stock["issued_kg"], stock["closing_kg"]) == (
        "100.000",
        "20.001",
        "5.001",
        "115.000",
    )
    assert snapshot["production"][0]["purchased_kg"] == "20.001"
    assert snapshot["production"][0]["sold_kg"] == "5.001"
    assert metric(w.preview([book])["snapshot"], book) == "10.01"

    templates = w.call("GET", "/contracts/templates")["items"]
    template = next(item for item in templates if item["kind"] == "purchase")
    # Manual parties/weights require no records link and payment is contract text,
    # never an instruction to post stock or independent cash-book rows.
    data = {
        "kind": "purchase",
        "number": "SYNTHETIC-MANUAL",
        "occurred_on": DAY,
        "template_id": template["id"],
        "company": {"type": "company", "name": "Synthetic company"},
        "counterparty": {"type": "person", "name": "Manually entered party"},
        "lines": [{"description": "Manual coffee", "quantity_kg": "9.001", "unit_price": "10.00"}],
        "tax": {"mode": "none"},
        "payment": {"method": "cash", "recorded_paid_amount": "90.01"},
        "terms": {"additional": "Điều khoản tổng hợp không tạo giao dịch kế toán."},
    }
    before_contract = w.preview([book], last="2026-11-07")["snapshot"]["sources"]
    contract = w.call("POST", "/contracts", json={"data": data, "request_key": key()})
    version = w.call(
        "POST",
        f"/contracts/{contract['id']}/exports",
        json={
            "formats": ["docx", "pdf"],
            "expected_version": contract["version"],
            "request_key": key(),
        },
    )
    for format in ("docx", "pdf"):
        content = w.client.get(
            f"/api/v1/contracts/{contract['id']}/versions/{version['id']}/files/{format}",
            headers=w.headers["admin"],
        )
        assert content.status_code == 200, content.text
        assert hashlib.sha256(content.content).hexdigest() == version["files"][format]["sha256"]
    after_contract = w.preview([book], last="2026-11-07")["snapshot"]["sources"]
    # Cutoff labels change per capture; the actual source quantities/metrics do not.
    assert after_contract["inventory"]["items"] == before_contract["inventory"]["items"]
    assert after_contract["books"][0]["metrics"] == before_contract["books"][0]["metrics"]
    party = w.call(
        "POST",
        "/records/parties",
        json={
            "code": "LINKED-PARTY",
            "name": "Real entered source party",
            "type": "person",
            "request_key": key(),
        },
    )
    assert w.call("GET", f"/contracts/sources/parties/{party['id']}")["name"] == party["name"]
    weighing = w.call(
        "POST",
        "/records/weighings",
        json={
            "code": "INTEGRATION-WEIGHING",
            "occurred_on": DAY,
            "party_id": party["id"],
            "lines": [{"quantity_source": "direct_net", "net_kg": "12.345"}],
            "request_key": key(),
        },
    )
    linked = w.call("GET", f"/contracts/sources/weighings/{weighing['id']}", role="operator")
    assert linked["id"] == weighing["id"] and linked["lines"][0]["net_kg"] == "12.345"
    assert linked["lines"][0]["gross_kg"] is None

    w.call(
        "PUT",
        f"/records/entries/{receipt['id']}",
        json=receipt_payload
        | {
            "lines": [receipt_payload["lines"][0] | {"quantity_kg": "30.001"}],
            "expected_version": receipt["version"],
            "request_key": key(),
        },
    )
    w.call(
        "PATCH",
        f"/accounting/rows/{row['id']}",
        json={
            "values": {"received": "15.01"},
            "expected_version": row["version"],
            "request_key": key(),
        },
    )
    frozen = w.call("GET", f"/reporting/reports/{report['id']}")
    assert frozen["sha256"] == report["sha256"] and frozen["snapshot"] == snapshot
    assert metric(w.preview([book], last="2026-11-07")["snapshot"], book) == "35.03"


def test_real_import_pending_cancel_resume_publish_and_second_pass_are_visible_atomically(
    workflow, monkeypatch
):
    w, book = workflow, workflow.book()
    product, warehouse = w.stock()
    w.entry(product, warehouse, "50.000")
    manual = w.row(book, "MANUAL", "10.00", "2.00")
    original = b"code,day,received,paid\nI001,2026-11-06,1.11,0\nI002,2026-11-06,2.22,0\nI003,2026-11-06,bad,0\n"
    uploaded = w.client.post(
        "/api/v1/files",
        content=original,
        headers=w.headers["admin"]
        | {
            "X-File-Name": quote("Nguồn tổng hợp.csv"),
            "X-Request-Key": key(),
            "Content-Type": "application/octet-stream",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    source = uploaded.json()
    batch = w.call(
        "POST",
        "/accounting/import-jobs",
        json={
            "book_id": book["id"],
            "file_id": source["id"],
            "request_key": key(),
        },
    )
    batch = w.wait_batch(batch["id"])
    batch = w.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/mapping",
        json={
            "expected_version": batch["version"],
            "mapping": {"code": "A", "day": "B", "received": "C", "paid": "D"},
            "request_key": key(),
        },
    )
    w.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/validate",
        json={
            "expected_version": batch["version"],
            "request_key": key(),
        },
    )
    batch = w.wait_batch(batch["id"])
    assert batch["counts"]["source_rows"] == 3 and batch["counts"]["invalid"] == 1
    assert metric(w.preview([book])["snapshot"], book) == "10.00"
    assert {row["Code"] for row in w.export_rows(book)} == {"MANUAL"}

    entered, release = threading.Event(), threading.Event()
    commit_chunk = JobContext.commit_chunk

    def pause_after_real_pending(context, *args, **kwargs):
        result = commit_chunk(context, *args, **kwargs)
        if kwargs.get("phase") == "commit_pending" and not entered.is_set():
            entered.set()
            assert release.wait(15), "integration test did not release genuine import worker"
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", pause_after_real_pending)
    try:
        w.confirm(batch)
        assert entered.wait(10)
        pending = w.call("GET", f"/accounting/import-jobs/{batch['id']}")
        assert (
            pending["counts"]["staged_committed_rows"],
            pending["counts"]["published_rows"],
            pending["counts"]["pending"],
        ) == (2, 0, 2)
        with w.runtime.reader() as conn:
            assert (
                conn.execute(
                    select(func.count()).select_from(accounting_schema.entries)
                ).scalar_one()
                == 3
            )
        assert w.call("GET", f"/accounting/books/{book['id']}/rows")["total"] == 1
        assert metric(w.preview([book])["snapshot"], book) == "10.00"
        provider = AccountingReadProvider(w.runtime, w.actor)
        assert (
            next(
                item.amount_vnd
                for item in provider.book_summary(
                    book["id"],
                    date.fromisoformat(DAY),
                    date.fromisoformat(DAY),
                    cutoff=datetime.now(timezone.utc),
                ).metrics
                if item.meaning == "cash_receipts"
            )
            == "10.00"
        )
        # Stop the one real worker at its safe boundary so the same worker can
        # execute an export while the durable attempt remains pending/hidden.
        w.call("POST", f"/accounting/import-jobs/{batch['id']}/cancel", json={"request_key": key()})
    finally:
        release.set()
    cancelled = w.wait_batch(batch["id"], expected="CANCELLED")
    assert cancelled["counts"]["pending"] == 2
    assert {row["Code"] for row in w.export_rows(book)} == {"MANUAL"}
    w.call("POST", f"/accounting/import-jobs/{batch['id']}/resume", json={"request_key": key()})
    first = w.wait_batch(batch["id"])
    assert first["state"] == "PARTIALLY_COMMITTED"
    assert (first["counts"]["published_rows"], first["counts"]["pending"]) == (2, 0)
    before = w.call("GET", f"/accounting/books/{book['id']}/rows")
    assert before["total"] == 3 and manual["id"] in {row["id"] for row in before["items"]}
    assert metric(w.preview([book])["snapshot"], book) == "13.33"
    assert {row["Code"] for row in w.export_rows(book)} == {"MANUAL", "I001", "I002"}

    invalid = w.call(
        "GET", f"/accounting/import-jobs/{batch['id']}/staging", params={"status": "invalid"}
    )["items"][0]
    revised = w.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/patches",
        json={
            "expected_version": first["version"],
            "request_key": key(),
            "patches": [
                {
                    "row_id": invalid["row_id"],
                    "expected_version": invalid["revision"],
                    "values": {"received": "3.33"},
                }
            ],
        },
    )
    w.call(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/validate",
        json={
            "expected_version": revised["version"],
            "request_key": key(),
        },
    )
    ready = w.wait_batch(batch["id"])
    w.confirm(ready)
    final = w.wait_batch(batch["id"])
    assert final["state"] == "COMPLETED"
    assert (
        final["counts"]["published_rows"],
        final["counts"]["staged_committed_rows"],
        final["counts"]["pending"],
    ) == (3, 3, 0)
    rows = w.call("GET", f"/accounting/books/{book['id']}/rows")
    assert rows["total"] == 4 and {row["id"] for row in before["items"]}.issubset(
        {row["id"] for row in rows["items"]}
    )
    assert metric(w.preview([book])["snapshot"], book) == "16.66"
    assert {row["Code"] for row in w.export_rows(book)} == {"MANUAL", "I001", "I002", "I003"}
    with w.runtime.reader() as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(claims).where(claims.c.job_id == batch["id"])
            ).scalar_one()
            == 3
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(attempts)
                .where(attempts.c.job_id == batch["id"], attempts.c.state == "PUBLISHED")
            ).scalar_one()
            == 2
        )
    snapshot = w.preview([book])["snapshot"]
    assert snapshot["sources"]["inventory"]["items"][0]["closing_kg"] == "50.000"
    original_again = w.client.get(
        f"/api/v1/files/{source['id']}/content", headers=w.headers["admin"]
    )
    assert (
        original_again.content == original
        and hashlib.sha256(original).hexdigest() == source["sha256"]
    )


def test_default_atomic_factory_keeps_both_sources_on_one_connection_during_second_writer_commit(
    workflow, monkeypatch
):
    w, book = workflow, workflow.book()
    product, warehouse = w.stock()
    receipt, payload = w.entry(product, warehouse, "10.001")
    row = w.row(book, "ONE", "10.01")
    database = Database(w.runtime.database.path, create=False)
    writer = WriteCoordinator(database)
    facade = SimpleNamespace(**vars(w.runtime))
    facade.database, facade.reader, facade.writer = database, database.read, writer
    records_read = RecordsReadProvider.inventory_summary
    book_read = AccountingReadProvider.book_summary
    reads, writer_connections, changed = [], [], []

    def inventory(provider, *args, **kwargs):
        conn = provider.connection
        assert conn is not None and conn.connection.driver_connection.in_transaction
        reads.append(
            (
                "records",
                id(conn),
                id(conn.connection.driver_connection),
                conn.get_transaction(),
                provider.principal.id,
            )
        )
        result = records_read(provider, *args, **kwargs)
        if not changed:
            changed.append(True)
            RecordsService(facade).save(
                "entries",
                payload | {"lines": [payload["lines"][0] | {"quantity_kg": "15.003"}]},
                actor=w.actor,
                request_key=key(),
                identity=receipt["id"],
                expected_version=1,
            )
            AccountingService(facade).mutate_row(
                w.actor, row["id"], 1, key(), values={"received": "15.03"}
            )
        return result

    def accounting(provider, *args, **kwargs):
        conn = provider.connection
        reads.append(
            (
                "accounting",
                id(conn),
                id(conn.connection.driver_connection),
                conn.get_transaction(),
                provider.actor.id,
            )
        )
        return book_read(provider, *args, **kwargs)

    from sqlalchemy import event

    def observe_writer(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            writer_connections.append(id(conn.connection.driver_connection))

    event.listen(database.engine, "before_cursor_execute", observe_writer)
    monkeypatch.setattr(RecordsReadProvider, "inventory_summary", inventory)
    monkeypatch.setattr(AccountingReadProvider, "book_summary", accounting)
    try:
        first = w.preview([book])["snapshot"]
        second = w.preview([book], role="operator")["snapshot"]
    finally:
        event.remove(database.engine, "before_cursor_execute", observe_writer)
        writer.close()
        database.close()
    assert first["sources"]["inventory"]["items"][0]["closing_kg"] == "10.001"
    assert metric(first, book) == "10.01"
    assert second["sources"]["inventory"]["items"][0]["closing_kg"] == "15.003"
    assert metric(second, book) == "15.03"
    assert len(reads) == 4 and all(identity != reads[0][2] for identity in writer_connections)
    for records, accounting in ((reads[0], reads[1]), (reads[2], reads[3])):
        assert records[1:4] == accounting[1:4]
    assert [read[4] for read in reads] == [
        w.actor.id,
        w.actor.id,
        w.operator["id"],
        w.operator["id"],
    ]


def test_revocation_during_real_cross_module_capture_cannot_persist_preview(workflow, monkeypatch):
    w, book = workflow, workflow.book()
    product, warehouse = w.stock()
    w.entry(product, warehouse, "10.001")
    w.row(book, "ONE", "10.01")
    original, captured = RecordsReadProvider.inventory_summary, []

    def revoke_after_inventory(provider, *args, **kwargs):
        result = original(provider, *args, **kwargs)
        assert provider.principal.id == w.operator["id"]
        captured.append(provider.principal.id)
        w.runtime.auth.update_user(
            w.actor,
            w.operator["id"],
            role="operator",
            active=False,
            expected_version=1,
            request_key=key(),
        )
        return result

    monkeypatch.setattr(RecordsReadProvider, "inventory_summary", revoke_after_inventory)
    before = w.call("GET", "/reporting/reports")["total"]
    response = w.call(
        "POST",
        "/reporting/reports/preview",
        role="operator",
        expected=401,
        json={
            "from_on": DAY,
            "through_on": DAY,
            "book_ids": [book["id"]],
            "request_key": key(),
        },
    )
    assert response["error"]["code"] == "SESSION_EXPIRED" and captured == [w.operator["id"]]
    assert w.call("GET", "/reporting/reports")["total"] == before
    with w.runtime.reader() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(REQUESTS)
                .where(
                    REQUESTS.c.actor == w.operator["id"], REQUESTS.c.action == "reporting.preview"
                )
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                select(func.count())
                .select_from(AUDIT)
                .where(AUDIT.c.actor == w.operator["id"], AUDIT.c.entity == "reporting_report")
            ).scalar_one()
            == 0
        )


def test_unavailable_windows_credential_api_does_not_block_default_registry_local_reporting(
    tmp_path, monkeypatch
):
    def unavailable():
        raise OSError("synthetic unavailable Windows adapter")

    monkeypatch.setattr(secrets, "_WindowsAPI", unavailable)
    runtime = Runtime(tmp_path / "Unavailable OS store local data", initialize=True)
    session = runtime.auth.setup("local-only-admin", "synthetic-local-only-password")
    headers = {
        "X-App-Session": "synthetic-no-secret-store-0123456789abcdef",
        "Authorization": "Bearer " + session["access_token"],
        "Origin": "http://tauri.localhost",
    }
    try:
        with TestClient(
            create_app(runtime, headers["X-App-Session"], port=48965),
            base_url="http://127.0.0.1:48965",
        ) as client:
            assert client.get("/api/v1/health", headers=headers).status_code == 200
            settings = client.get("/api/v1/reporting/settings", headers=headers)
            assert settings.status_code == 200, settings.text
            assert settings.json()["credential_store_available"] is False
            assert (
                settings.json()["enabled"] is False
                and settings.json()["sender_status"] == "UNCONFIGURED"
            )
            response = client.post(
                "/api/v1/reporting/reports/preview",
                headers=headers,
                json={
                    "from_on": DAY,
                    "through_on": DAY,
                    "book_ids": [],
                    "request_key": key(),
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["snapshot"]["consistency"] == "atomic_read_snapshot"
    finally:
        runtime.close()
