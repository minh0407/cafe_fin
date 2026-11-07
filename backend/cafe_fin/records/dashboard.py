"""Records-only operational dashboard, all sources in one authenticated snapshot."""

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from cafe_fin.core.amounts import parse_kg, parse_money
from cafe_fin.core.errors import CoreError

from .bridge import RecordsReadProvider
from .migrations import MOVEMENTS as M
from .service import RecordsService, current_query, decimal_total, effective_movements


def _metrics():
    return dict.fromkeys(
        (
            "inbound_kg",
            "outbound_kg",
            "cash_in_vnd",
            "cash_out_vnd",
            "sales_order_value_vnd",
            "unpriced_sales_orders",
        ),
        0,
    )


def _serialize(values):
    result = {}
    for key, value in values.items():
        if key == "unpriced_sales_orders":
            result[key] = value
        elif key == "sales_order_value_vnd":
            whole, fraction = decimal_total(value, 5).split(".")
            result[key] = whole + "." + fraction.rstrip("0").ljust(2, "0")
        else:
            result[key] = decimal_total(value, 3 if key.endswith("_kg") else 2)
    return result


def dashboard(runtime, actor, from_on: date, through_on: date):
    if (
        type(from_on) is not date
        or type(through_on) is not date
        or from_on > through_on
        or (through_on - from_on).days >= 366
    ):
        raise CoreError("INVALID_RANGE", "Khoảng ngày dashboard phải từ 1 đến 366 ngày.", 422)
    start, end = from_on.isoformat(), through_on.isoformat()
    daily = {
        (from_on + timedelta(days=index)).isoformat(): _metrics()
        for index in range((through_on - from_on).days + 1)
    }
    counts = dict.fromkeys(
        ("farms", "farm_surveys", "customer_companies", "inbound_trades", "outbound_trades"), 0
    )
    service = RecordsService(runtime)
    with runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        service._authorize(conn, actor)
        cutoff = datetime.now(timezone.utc)
        inventory = (
            RecordsReadProvider(runtime, actor)
            .bind_connection(conn)
            .inventory_summary(from_on, through_on, cutoff=cutoff)
        )
        for row in conn.execute(current_query("parties", cutoff=cutoff)).mappings():
            party = json.loads(row.data_json)
            if party["deleted_at"] or not party.get("active", True):
                continue
            if party.get("profile_kind") == "farm":
                counts["farms"] += 1
                counts["farm_surveys"] += len((party.get("farm") or {}).get("surveys", []))
            elif party.get("profile_kind") == "customer_company":
                counts["customer_companies"] += 1
        for row in conn.execute(current_query("trades", cutoff=cutoff)).mappings():
            trade = json.loads(row.data_json)
            if (
                trade["deleted_at"]
                or trade["status"] != "recorded"
                or not start <= trade["occurred_on"] <= end
            ):
                continue
            counts[trade["direction"] + "_trades"] += 1
            if trade["direction"] == "outbound":
                metrics = daily[trade["occurred_on"]]
                if any(line["unit_price_vnd"] is None for line in trade["lines"]):
                    metrics["unpriced_sales_orders"] += 1
                else:
                    metrics["sales_order_value_vnd"] += sum(
                        parse_kg(line["quantity_kg"]) * parse_money(line["unit_price_vnd"])
                        for line in trade["lines"]
                    )
        for row in conn.execute(
            effective_movements(cutoff=cutoff).where(
                M.c.occurred_on >= start,
                M.c.occurred_on <= end,
                M.c.entry_type.in_(("receipt", "issue")),
            )
        ).mappings():
            field = "inbound_kg" if row.entry_type == "receipt" else "outbound_kg"
            daily[row.occurred_on][field] += abs(row.delta_scaled)
        payments = current_query("trade-payments", cutoff=cutoff).subquery()
        trades = current_query("trades", cutoff=cutoff).subquery()
        payment_query = select(
            payments.c.data_json,
            func.json_extract(trades.c.data_json, "$.direction").label("direction"),
        ).join(trades, trades.c.id == func.json_extract(payments.c.data_json, "$.trade_id"))
        for row in conn.execute(payment_query).mappings():
            payment = json.loads(row.data_json)
            if payment["deleted_at"] or not start <= payment["occurred_on"] <= end:
                continue
            field = "cash_in_vnd" if row.direction == "outbound" else "cash_out_vnd"
            daily[payment["occurred_on"]][field] += parse_money(payment["amount_vnd"])
        period = _metrics()
        for values in daily.values():
            for key, value in values.items():
                period[key] += value
        return {
            "coverage": "entered_records_only",
            "cutoff": cutoff,
            "from_on": from_on,
            "through_on": through_on,
            "counts": counts,
            "inventory": inventory,
            "period": _serialize(period),
            "daily": [
                {"occurred_on": date.fromisoformat(occurred_on), **_serialize(values)}
                for occurred_on, values in daily.items()
            ],
        }
