from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from cafe_fin.core.amounts import (
    INT64_MAX,
    exact_total,
    kg_string,
    money_string,
    parse_kg,
    parse_money,
)
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import AUDIT, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import Migration, ModuleManifest, ModuleRegistry
from cafe_fin.core.time import business_day_bounds
from sqlalchemy import Column, Integer, MetaData, Table, insert, select


def test_decimal_scale_overflow_and_total():
    assert parse_money("12.34") == 1234
    assert parse_kg("0.001") == 1
    assert kg_string(-1) == "-0.001"
    assert money_string(INT64_MAX) == "92233720368547758.07"
    assert exact_total([INT64_MAX, INT64_MAX]) == "184467440737095516.14"
    for invalid in ["", "1e2", "NaN", "1.001", "92233720368547758.08", 1.0]:
        with pytest.raises(CoreError):
            parse_money(invalid)


def test_business_day_is_vietnam_not_host_timezone():
    start, end = business_day_bounds(date(2026, 11, 6))
    assert start == datetime(2026, 11, 5, 17, tzinfo=timezone.utc)
    assert (end - start).total_seconds() == 86400


def test_serialized_write_rollback_idempotency_and_reopen(tmp_path):
    db = Database(tmp_path / "foundation.db")
    db.migrate()
    meta = MetaData()
    table = Table(
        "example_counter",
        meta,
        Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    writer = WriteCoordinator(db)
    writer.run(lambda conn: meta.create_all(conn))
    writer.run(lambda conn: conn.execute(insert(table).values(id=1, value=0)))

    def add(key):
        def operation(conn):
            value = conn.execute(select(table.c.value)).scalar_one() + 1
            conn.execute(table.update().values(value=value))
            AuditService.record(
                conn,
                actor="synthetic",
                entity="counter",
                entity_id="1",
                action="increment",
                before={"value": value - 1},
                after={"value": value},
            )
            return {"value": value}

        return writer.execute("synthetic", "increment", key, {"delta": 1}, operation)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add, [str(i) for i in range(24)]))
    original = add("24")
    assert add("24") == original
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        writer.execute("synthetic", "increment", "24", {"delta": 2}, lambda _: None)

    def broken(conn):
        conn.execute(table.update().values(value=999))
        AuditService.record(conn, actor="synthetic", entity="counter", entity_id="1", action="fail")
        raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError):
        writer.run(broken)
    with db.read() as conn:
        assert conn.execute(select(table.c.value)).scalar_one() == 25
        assert len(conn.execute(select(AUDIT)).all()) == 25
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar_one() == 2
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
    writer.close()
    db.close()
    reopened = Database(tmp_path / "foundation.db")
    reopened.migrate()
    retry_writer = WriteCoordinator(reopened)
    assert (
        retry_writer.execute(
            "synthetic", "increment", "24", {"delta": 1}, lambda _: pytest.fail("replayed effect")
        )
        == original
    )
    retry_writer.close()
    reopened.close()


def test_migrations_reject_newer_or_changed_schema(tmp_path):
    path = tmp_path / "migration.db"
    db = Database(path)
    v1 = Migration("sample", 1, "first", lambda conn: None)
    db.migrate((v1,))
    with pytest.raises(CoreError, match="SCHEMA_NEWER_THAN_APP"):
        db.migrate()
    with pytest.raises(CoreError, match="MIGRATION_CHANGED"):
        db.migrate((Migration("sample", 1, "changed", lambda conn: None),))
    db.close()


def test_registry_orders_dependencies_and_rejects_cycle():
    first = ModuleManifest("sample", "/sample")
    second = ModuleManifest("example", "/example", dependencies=("sample",))
    registry = ModuleRegistry((second, first))
    assert [item.id for item in registry.ordered()] == ["sample", "example"]
    with pytest.raises(CoreError, match="MODULE_DEPENDENCY"):
        ModuleRegistry((ModuleManifest("sample", "/sample", dependencies=("sample",)),)).ordered()
