from datetime import date

import pytest
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import AUDIT, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.stock_guard import (
    StockPoint,
    StockScope,
    assert_nonnegative,
    guard_stock_mutation,
)
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    func,
    insert,
    select,
    update,
)

ledger = Table(
    "example_stock_ledger",
    MetaData(),
    Column("id", String, primary_key=True),
    Column("occurred_on", String, nullable=False),
    Column("order_key", String, nullable=False),
    Column("delta", Integer, nullable=False),
)


@pytest.fixture
def runtime(tmp_path):
    db = Database(tmp_path / "stock.sqlite3")
    db.migrate()
    writer = WriteCoordinator(db)
    writer.run(lambda conn: ledger.create(conn))
    writer.run(
        lambda conn: conn.execute(
            insert(ledger),
            [
                dict(id="in", occurred_on="2026-11-02", order_key="0001", delta=10000),
                dict(id="out", occurred_on="2026-11-03", order_key="0002", delta=-8000),
            ],
        )
    )
    yield db, writer
    writer.close()
    db.close()


def scopes(conn):
    rows = conn.execute(
        select(ledger).order_by(ledger.c.occurred_on, ledger.c.order_key, ledger.c.id)
    )
    yield StockScope(
        "synthetic-warehouse/product",
        (
            StockPoint(row.id, date.fromisoformat(row.occurred_on), row.order_key, row.delta)
            for row in rows
        ),
    )


@pytest.mark.parametrize("operation", ["delete", "backdate", "reduce"])
def test_edit_delete_and_backdate_revalidate_history_and_rollback_audit(runtime, operation):
    db, writer = runtime

    def mutate(conn):
        if operation == "delete":
            conn.execute(delete(ledger).where(ledger.c.id == "in"))
        elif operation == "backdate":
            conn.execute(
                update(ledger).where(ledger.c.id == "out").values(occurred_on="2026-11-01")
            )
        else:
            conn.execute(update(ledger).where(ledger.c.id == "in").values(delta=7000))
        AuditService.record(
            conn,
            actor="synthetic",
            entity="example_stock",
            entity_id="in",
            action=operation,
            before={"delta": 10000},
            after={"synthetic": True},
        )

    with pytest.raises(CoreError, match="STOCK_NEGATIVE") as caught:
        writer.run(lambda conn: guard_stock_mutation(conn, mutate, scopes))
    assert caught.value.details["related_entry_id"] == "out"
    with db.read() as conn:
        assert conn.execute(select(func.count()).select_from(AUDIT)).scalar_one() == 0
        assert conn.execute(select(ledger.c.delta).where(ledger.c.id == "in")).scalar_one() == 10000
        assert (
            conn.execute(select(ledger.c.occurred_on).where(ledger.c.id == "out")).scalar_one()
            == "2026-11-03"
        )


def test_same_day_order_is_stable_not_current_balance_only():
    day = date(2026, 11, 6)
    with pytest.raises(CoreError, match="STOCK_NEGATIVE"):
        assert_nonnegative(
            [StockPoint("out", day, "0001", -1000), StockPoint("in", day, "0002", 2000)]
        )
    assert (
        assert_nonnegative(
            [StockPoint("in", day, "0001", 2000), StockPoint("out", day, "0002", -1000)]
        )
        == 1000
    )
    with pytest.raises(CoreError, match="STOCK_ORDER_INVALID"):
        assert_nonnegative(
            [StockPoint("in", day, "0002", 2000), StockPoint("out", day, "0001", -1000)]
        )


def test_checked_prefix_overflow_and_no_binary_float():
    day = date(2026, 11, 6)
    with pytest.raises(CoreError, match="AMOUNT_OVERFLOW"):
        assert_nonnegative(
            [StockPoint("large", day, "1", 2**63 - 1), StockPoint("extra", day, "2", 1)]
        )
    with pytest.raises(CoreError, match="AMOUNT_OVERFLOW"):
        assert_nonnegative([StockPoint("float", day, "1", 1.5)])
