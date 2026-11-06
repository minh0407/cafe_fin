"""Physical SQLite connection contention and transactional recovery, without fake balances."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import AUDIT, REQUESTS, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event, select
from test_records_api import balances, snapshot


def test_two_real_connections_cannot_consume_the_same_stock(records_api, monkeypatch):
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters = api.masters()
    receipt = api.create("entries", api.entry_data(masters, "10.000"))
    first_locked, second_attempted, release_first = (threading.Event() for _ in range(3))
    second_acquired, second_target_queued = threading.Event(), threading.Event()
    connection_ids = set()
    physical_connections, target_threads, unrelated_engines = {}, {}, set()
    observation_lock = threading.Lock()
    first_code, second_code = "PX-CONNECTION-1", "PX-CONNECTION-2"
    target_action = "records.entries.create"
    database2 = Database(api.runtime.database.path, create=False)
    writer2 = WriteCoordinator(database2)
    runtime2 = SimpleNamespace(
        database=database2, reader=database2.read, writer=writer2, auth=api.runtime.auth,
    )
    with database2.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
    first_execute, second_execute = api.runtime.writer.execute, writer2.execute

    def observe_connection(conn, code):
        with observation_lock:
            assert code not in physical_connections, "target opened more than one write transaction"
            physical_connections[code] = conn.connection.driver_connection
            target_threads[code] = threading.get_ident()
            connection_ids.add(id(conn.connection.driver_connection))

    def first_target_execute(actor, action, request_key, payload, operation, *, authorize=None):
        if (actor, action, request_key) != (api.principal.id, target_action, first_code):
            return first_execute(actor, action, request_key, payload, operation, authorize=authorize)

        def first_target_authorize(conn):
            # Actual WriteCoordinator.execute invokes this on its own worker,
            # after the real BEGIN IMMEDIATE. No caller-thread TLS is assumed.
            assert conn.in_transaction() and conn.connection.driver_connection.in_transaction
            observe_connection(conn, first_code)
            first_locked.set()
            assert release_first.wait(10), "test did not release SQLite write lock"
            assert authorize is not None
            return authorize(conn)

        return first_execute(actor, action, request_key, payload, operation,
                             authorize=first_target_authorize)

    def second_target_execute(actor, action, request_key, payload, operation, *, authorize=None):
        if (actor, action, request_key) != (api.principal.id, target_action, second_code):
            return second_execute(actor, action, request_key, payload, operation, authorize=authorize)
        # This dedicated coordinator has no JobRunner. All unrelated probes have
        # completed before this exact command is enqueued; it is its only target.
        second_target_queued.set()
        try:
            return second_execute(actor, action, request_key, payload, operation, authorize=authorize)
        finally:
            second_target_queued.clear()

    def unrelated_first_begin(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE":
            # Observe real background/probe transactions, without treating any
            # engine-wide BEGIN as the identity or lock of a target command.
            with observation_lock:
                unrelated_engines.add(conn.engine)

    def second_before_begin(conn, cursor, statement, parameters, context, executemany):
        if statement != "BEGIN IMMEDIATE":
            return
        if not second_target_queued.is_set():
            with observation_lock:
                unrelated_engines.add(conn.engine)
            return
        observe_connection(conn, second_code)
        assert not conn.connection.driver_connection.in_transaction
        second_attempted.set()

    def second_after_begin(conn, cursor, statement, parameters, context, executemany):
        if statement == "BEGIN IMMEDIATE" and second_target_queued.is_set():
            assert conn.connection.driver_connection is physical_connections[second_code]
            assert conn.connection.driver_connection.in_transaction
            second_acquired.set()

    monkeypatch.setattr(api.runtime.writer, "execute", first_target_execute)
    monkeypatch.setattr(writer2, "execute", second_target_execute)
    event.listen(api.runtime.database.engine, "after_cursor_execute", unrelated_first_begin)
    event.listen(database2.engine, "before_cursor_execute", second_before_begin)
    event.listen(database2.engine, "after_cursor_execute", second_after_begin)

    def consume(runtime, code):
        return RecordsService(runtime).save(
            "entries", api.entry_data(masters, "7.000", code=code, day="2026-11-02", kind="issue"),
            actor=api.principal, request_key=code,
        )

    try:
        # Force unrelated actual BEGINs through both run() and execute() before
        # either target, while the application's real JobRunner stays running.
        for index, writer in enumerate((api.runtime.writer, writer2)):
            assert writer.run(lambda conn: conn.exec_driver_sql("SELECT 1").scalar_one()) == 1
            assert writer.execute(api.principal.id, "test.unrelated", f"noise-{index}", {},
                lambda conn: {"probe": conn.exec_driver_sql("SELECT 1").scalar_one()}) == {"probe": 1}
            assert not first_locked.is_set()
            assert not second_attempted.is_set()
            assert not second_acquired.is_set()
            assert not second_target_queued.is_set()
            assert connection_ids == set() and physical_connections == {} and target_threads == {}
        assert unrelated_engines == {api.runtime.database.engine, database2.engine}

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(consume, api.runtime, first_code)
            assert first_locked.wait(5), "first target never acquired its actual write transaction"
            second = executor.submit(consume, runtime2, second_code)
            try:
                assert second_attempted.wait(5), "second connection did not attempt BEGIN IMMEDIATE"
                assert physical_connections[first_code].in_transaction
                assert not physical_connections[second_code].in_transaction
                assert not second_acquired.wait(0.1), "second BEGIN acquired the first writer's lock"
                assert not second.done(), "second writer must wait for the existing SQLite write lock"
            finally:
                release_first.set()
            successful = first.result(timeout=10)
            with pytest.raises(CoreError, match="STOCK_NEGATIVE"):
                second.result(timeout=10)
        assert second_acquired.is_set(), "second writer never acquired BEGIN after the first commit"
        assert len(connection_ids) == 2
        assert set(physical_connections) == {first_code, second_code}
        assert len(set(target_threads.values())) == 2
        assert successful["code"] == first_code
        assert list(balances(api).values()) == ["3.000"]
        assert api.get("entries")["total"] == 2
        movements = api.get("stock-movements")["items"]
        expected_ids = {receipt["id"], successful["id"]}
        assert len(movements) == 2
        assert {row["entry_id"] for row in movements} == expected_ids
        assert {row["delta_kg"] for row in movements} == {"10.000", "-7.000"}
        with api.runtime.reader() as conn:
            audits = conn.execute(select(AUDIT.c.entity_id).where(AUDIT.c.entity == "records.entries")).scalars().all()
            assert len(audits) == 2 and set(audits) == expected_ids
            receipts = conn.execute(select(REQUESTS.c.request_key).where(
                REQUESTS.c.actor == api.principal.id, REQUESTS.c.action == target_action,
            )).scalars().all()
            assert len(receipts) == 2
            assert first_code in receipts and second_code not in receipts
    finally:
        release_first.set()
        monkeypatch.setattr(api.runtime.writer, "execute", first_execute)
        monkeypatch.setattr(writer2, "execute", second_execute)
        event.remove(api.runtime.database.engine, "after_cursor_execute", unrelated_first_begin)
        event.remove(database2.engine, "before_cursor_execute", second_before_begin)
        event.remove(database2.engine, "after_cursor_execute", second_after_begin)
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
