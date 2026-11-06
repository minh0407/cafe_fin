"""Physical SQLite connection contention and transactional recovery, without fake balances."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event
from test_records_api import balances, snapshot


def test_two_real_connections_cannot_consume_the_same_stock(records_api):
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "10.000"))
    first_locked, second_attempted, release_first = (threading.Event() for _ in range(3))
    connection_ids = set()
    database2 = Database(api.runtime.database.path, create=False)
    writer2 = WriteCoordinator(database2)
    runtime2 = SimpleNamespace(
        database=database2, reader=database2.read, writer=writer2, auth=api.runtime.auth,
    )
    with database2.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"

    def first_after_begin(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            connection_ids.add(id(conn.connection.driver_connection))
            first_locked.set()
            assert release_first.wait(10), "test did not release SQLite write lock"

    def second_before_begin(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            connection_ids.add(id(conn.connection.driver_connection))
            second_attempted.set()

    event.listen(api.runtime.database.engine, "after_cursor_execute", first_after_begin)
    event.listen(database2.engine, "before_cursor_execute", second_before_begin)

    def consume(runtime, code):
        return RecordsService(runtime).save(
            "entries", api.entry_data(masters, "7.000", code=code, day="2026-11-02", kind="issue"),
            actor=api.principal, request_key=code,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(consume, api.runtime, "PX-CONNECTION-1")
            assert first_locked.wait(5), "first physical connection never acquired its write lock"
            second = executor.submit(consume, runtime2, "PX-CONNECTION-2")
            try:
                assert second_attempted.wait(5), "second connection did not attempt BEGIN IMMEDIATE"
                assert not second.done(), "second writer must wait for the existing SQLite write lock"
            finally:
                release_first.set()
            successful = first.result(timeout=10)
            with pytest.raises(CoreError, match="STOCK_NEGATIVE"):
                second.result(timeout=10)
        assert len(connection_ids) == 2
        assert successful["code"] == "PX-CONNECTION-1"
        assert list(balances(api).values()) == ["3.000"]
        assert api.get("entries")["total"] == 2
        assert len(api.get("stock-movements")["items"]) == 2
    finally:
        release_first.set()
        event.remove(api.runtime.database.engine, "after_cursor_execute", first_after_begin)
        event.remove(database2.engine, "before_cursor_execute", second_before_begin)
        writer2.close()
        database2.close()


def test_audit_failure_rolls_back_record_ledger_and_receipt(records_api, monkeypatch):
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters = api.masters()
    before = snapshot(api)
    record = AuditService.record

    def fail_records_audit(conn, **values):
        if values["entity"].startswith("records."):
            raise RuntimeError("synthetic-audit-write-failure")
        return record(conn, **values)

    monkeypatch.setattr(AuditService, "record", fail_records_audit)
    with pytest.raises(RuntimeError, match="synthetic-audit-write-failure"):
        RecordsService(api.runtime).save(
            "entries", api.entry_data(masters, "10.000"), actor=api.principal,
            request_key="audit-failure-retryable",
        )
    assert snapshot(api) == before
    monkeypatch.setattr(AuditService, "record", record)
    api.create("entries", api.entry_data(masters, "10.000"), key="audit-failure-retryable")
    assert list(balances(api).values()) == ["10.000"]


def test_receipt_and_idempotency_survive_database_runtime_reopen(records_api):
    from cafe_fin.records.module import RecordsReadProvider, module_manifest
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters = api.masters()
    payload = api.entry_data(masters, "10.001")
    original = api.create("entries", payload, key="durable-records-request")
    data_root = api.runtime.root.path
    api.runtime.close()
    reopened = Runtime(data_root, modules=ModuleRegistry((module_manifest(),)))
    try:
        session = reopened.auth.login("records-admin", "records-synthetic-password")
        principal = reopened.auth.authenticate(session["access_token"])
        replayed = RecordsService(reopened).save(
            "entries", payload, actor=principal, request_key="durable-records-request",
        )
        assert replayed == original
        assert RecordsService(reopened).list("entries", actor=principal)["total"] == 1
        assert RecordsService(reopened).movements(actor=principal)["total"] == 1
        summary = RecordsReadProvider(reopened, principal).inventory_summary(
            date(2026, 11, 1), date(2026, 11, 1), cutoff=datetime.now(timezone.utc),
        )
        assert summary.items[0].closing_kg == "10.001"
    finally:
        reopened.close()


def test_scaled_weights_and_money_are_sqlite_integers_and_missing_values_are_null(records_api):
    api = records_api
    masters = api.masters()
    weighing = api.create("weighings", {
        "code": "CAN-INTEGER", "occurred_on": "2026-11-01", "lines": [
            {"quantity_source": "gross_tare", "gross_kg": "100.125", "tare_kg": "10.024"},
            {"quantity_source": "direct_net", "net_kg": "12.003"},
        ],
    })
    entry = api.create("entries", api.entry_data(masters, "10.001") | {
        "commercial_amount_vnd": "123.45",
    })
    draft = api.create("entries", api.entry_data(masters, "10.001", code="DRAFT-NULL") | {
        "status": "draft", "lines": [{"product_id": masters["product"]["id"],
            "warehouse_id": masters["warehouse"]["id"], "direction": "in", "quantity_kg": None}],
    })
    with api.runtime.reader() as conn:
        weights = conn.exec_driver_sql(
            "SELECT gross_scaled,tare_scaled,net_scaled,typeof(gross_scaled),"
            "typeof(tare_scaled),typeof(net_scaled) FROM records_lines "
            "WHERE document_id=? AND version=1 ORDER BY line_number", (weighing["id"],),
        ).all()
        assert weights == [
            (100125, 10024, 90101, "integer", "integer", "integer"),
            (None, None, 12003, "null", "null", "integer"),
        ]
        quantity = conn.exec_driver_sql(
            "SELECT quantity_scaled,typeof(quantity_scaled) FROM records_lines "
            "WHERE document_id=? AND version=1", (entry["id"],),
        ).one()
        assert quantity == (10001, "integer")
        missing = conn.exec_driver_sql(
            "SELECT quantity_scaled,typeof(quantity_scaled) FROM records_lines "
            "WHERE document_id=? AND version=1", (draft["id"],),
        ).one()
        assert missing == (None, "null")
        money = conn.exec_driver_sql(
            "SELECT commercial_scaled,typeof(commercial_scaled) FROM records_revisions "
            "WHERE document_id=? AND version=1", (entry["id"],),
        ).one()
        assert money == (12345, "integer")
        movement = conn.exec_driver_sql(
            "SELECT delta_scaled,typeof(delta_scaled) FROM records_movements WHERE entry_id=?",
            (entry["id"],),
        ).one()
        assert movement == (10001, "integer")
