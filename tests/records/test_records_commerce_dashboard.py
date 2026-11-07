"""Dashboard source meanings, VN dates and one real WAL snapshot."""

from datetime import date

from cafe_fin.records.bridge import RecordsReadProvider
from cafe_fin.records.service import RecordsService
from sqlalchemy import event

from tests.records.test_records_commerce import (
    commerce,
    editable,
    linked_entry,
    payment_data,
    trade_data,
)


def dashboard(api, start="2026-11-01", end="2026-11-03"):
    return api.get("records-dashboard", from_on=start, through_on=end)


def test_dashboard_sources_exact_products_and_daily_dates(records_api):
    api = records_api
    masters = commerce(api)
    inbound = api.create("trades", trade_data(masters, quantity="10.001"))
    receipt = api.create(
        "entries",
        linked_entry(api, masters, inbound, "10.001")
        | {
            "commercial_amount_vnd": "999999.99",
        },
    )
    outbound = api.create(
        "trades",
        trade_data(masters, direction="outbound", code="SALE", quantity="1.001", price="10.01")
        | {
            # UTC 17:30 is November 2 in Vietnam: classify by occurred_on, not UTC date.
            "occurred_on": "2026-11-02",
            "occurred_at": "2026-11-01T17:30:00Z",
        },
    )
    api.create(
        "entries", linked_entry(api, masters, outbound, "1.001", code="ISSUE", day="2026-11-03")
    )
    api.create("trades", trade_data(masters, direction="outbound", code="UNPRICED", price=None))
    api.create(
        "trades",
        trade_data(masters, direction="outbound", code="CANCELLED") | {"status": "cancelled"},
    )
    api.create(
        "trades",
        trade_data(masters, direction="outbound", code="OUTSIDE") | {"occurred_on": "2026-10-31"},
    )
    deleted = api.create("trades", trade_data(masters, direction="outbound", code="DELETED"))
    api.command("trades", deleted, "delete")
    api.create("trade-payments", payment_data(masters, inbound, code="CASH-OUT", amount="100.25"))
    api.create(
        "trade-payments",
        payment_data(masters, outbound, code="CASH-IN", amount="10.01")
        | {"occurred_on": "2026-11-03"},
    )
    removed = api.create(
        "trade-payments", payment_data(masters, outbound, code="REMOVED", amount="999")
    )
    api.command("trade-payments", removed, "delete")
    # Opening/adjustment are real inventory, but never purchases/sales in dashboard kg.
    api.create(
        "entries",
        api.entry_data(masters, "2", code="OPENING", day="2026-10-31", kind="opening")
        | {"note": "Synthetic opening"},
    )
    api.create(
        "entries",
        api.entry_data(masters, "3", code="ADJUSTMENT", kind="adjustment")
        | {"note": "Synthetic adjustment"},
    )
    inactive = api.create(
        "parties", {"code": "F999", "name": "Farm ngừng", "profile_kind": "farm", "active": False}
    )
    assert inactive["active"] is False
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(api.runtime.database.engine, "before_cursor_execute", observe)
    try:
        result = dashboard(api)
    finally:
        event.remove(api.runtime.database.engine, "before_cursor_execute", observe)
    assert result["coverage"] == "entered_records_only"
    assert result["inventory"]["cutoff"] == result["cutoff"]
    assert result["counts"] == {
        "farms": 1,
        "farm_surveys": 1,
        "customer_companies": 1,
        "inbound_trades": 1,
        "outbound_trades": 2,
    }
    assert result["period"] == {
        "inbound_kg": "10.001",
        "outbound_kg": "1.001",
        "cash_in_vnd": "10.01",
        "cash_out_vnd": "100.25",
        "sales_order_value_vnd": "10.02001",
        "unpriced_sales_orders": 1,
    }
    assert [row["occurred_on"] for row in result["daily"]] == [
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ]
    assert result["daily"][1]["sales_order_value_vnd"] == "10.02001"
    assert result["daily"][0]["sales_order_value_vnd"] == "0.00"
    assert result["daily"][2]["cash_in_vnd"] == "10.01"
    assert result["inventory"]["items"][0]["opening_kg"] == "2.000"
    assert result["inventory"]["items"][0]["closing_kg"] == "14.000"
    assert not any("accounting_" in statement.lower() for statement in statements)
    assert api.get(f"entries/{receipt['id']}")["commercial_amount_vnd"] == "999999.99"


def test_dashboard_range_maximum_and_empty_days(records_api):
    api = records_api
    for start, end in (("2026-11-02", "2026-11-01"), ("2026-01-01", "2027-01-02")):
        response = api.request(
            "GET", "records-dashboard", params={"from_on": start, "through_on": end}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_RANGE"
    result = dashboard(api, "2026-01-01", "2027-01-01")
    assert len(result["daily"]) == 366
    assert all(row["cash_in_vnd"] == "0.00" for row in result["daily"])
    assert result["counts"] == dict.fromkeys(result["counts"], 0)
    assert len(dashboard(api, "2026-11-01", "2026-11-01")["daily"]) == 1


def test_dashboard_uses_one_snapshot_during_concurrent_trade_payment_and_stock_write(
    records_api, monkeypatch
):
    api = records_api
    masters = commerce(api)
    service = RecordsService(api.runtime)
    original = RecordsReadProvider.inventory_summary
    wrote = []

    def write_after_inventory(provider, from_on, through_on, *, cutoff):
        inventory = original(provider, from_on, through_on, cutoff=cutoff)
        assert provider.connection is not None
        trade = service.save(
            "trades", trade_data(masters), actor=api.principal, request_key="snapshot-trade"
        )
        service.save(
            "entries",
            linked_entry(api, masters, trade, "10"),
            actor=api.principal,
            request_key="snapshot-entry",
        )
        service.save(
            "trade-payments",
            payment_data(masters, trade),
            actor=api.principal,
            request_key="snapshot-payment",
        )
        wrote.append(trade)
        return inventory

    monkeypatch.setattr(RecordsReadProvider, "inventory_summary", write_after_inventory)
    before = dashboard(api)
    assert len(wrote) == 1
    assert before["inventory"]["items"] == []
    assert before["counts"]["inbound_trades"] == 0
    assert before["period"]["cash_out_vnd"] == "0.00"
    assert before["period"]["inbound_kg"] == "0.000"
    monkeypatch.setattr(RecordsReadProvider, "inventory_summary", original)
    after = dashboard(api)
    assert after["counts"]["inbound_trades"] == 1
    assert after["period"]["cash_out_vnd"] == "123.45"
    assert after["inventory"]["items"][0]["closing_kg"] == "10.000"


def test_trade_history_restore_and_cancelled_dashboard_values(records_api):
    api = records_api
    masters = commerce(api)
    trade = api.create("trades", trade_data(masters, direction="outbound"))
    cancelled = api.replace("trades", trade, editable(trade) | {"status": "cancelled"}).json()
    assert dashboard(api)["counts"]["outbound_trades"] == 0
    removed = api.command("trades", cancelled, "delete").json()
    restored = api.command("trades", removed, "restore").json()
    assert restored["status"] == "cancelled"
    assert restored["version"] == 4
    assert api.get(f"trades/{trade['id']}/history")["total"] == 4
    assert (
        api.get(
            "records-dashboard", from_on=date(2026, 11, 1).isoformat(), through_on="2026-11-03"
        )["period"]["sales_order_value_vnd"]
        == "0.00"
    )


def test_cancelled_trade_can_be_deleted_after_customer_details_change(records_api):
    api = records_api
    masters = commerce(api)
    trade = api.create("trades", trade_data(masters, direction="outbound"))
    cancelled = api.replace("trades", trade, editable(trade) | {"status": "cancelled"}).json()
    response = api.replace(
        "parties", masters["customer"], editable(masters["customer"]) | {"tax_code": None}
    )
    assert response.status_code == 200
    deleted = api.command("trades", cancelled, "delete")
    assert deleted.status_code == 200
    restored = api.command("trades", deleted.json(), "restore")
    assert restored.status_code == 200
    assert api.replace("trades", restored.json(), editable(trade)).status_code == 422
