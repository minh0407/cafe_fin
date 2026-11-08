"""One synthetic, request-only HTTP scenario for source and frozen records runtimes.

No app imports, credentials, database access or market-source fixtures belong here.
The caller supplies an authenticated adapter for module-relative resource paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol


class Response(Protocol):
    status_code: int

    def json(self) -> Any: ...


class API(Protocol):
    def request(self, method: str, path: str, *, data=None, params=None) -> Response: ...


_METADATA = frozenset(
    {
        "id",
        "version",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "recorded_at",
        "deleted_at",
        "order_key",
    }
)


def _editable(record):
    return copy.deepcopy({key: value for key, value in record.items() if key not in _METADATA})


def _without_cutoff(value):
    if isinstance(value, dict):
        return {key: _without_cutoff(item) for key, item in value.items() if key != "cutoff"}
    if isinstance(value, list):
        return [_without_cutoff(item) for item in value]
    return value


def _digest(value):
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def exercise(api: API, *, occurred_on: str, request_prefix: str = "records-desktop") -> dict:
    """Exercise a NEW records data root. Failure raises AssertionError immediately.

    The adapter prepends /api/v1/records and owns authentication/timeouts. The
    environment must disable the real market collector before backend startup.
    A fixed farm code makes accidental reuse fail before overwriting any record.
    """
    business_day = date.fromisoformat(occurred_on)
    if business_day.isoformat() != occurred_on or business_day.year < 2000:
        raise ValueError("occurred_on must be a canonical business date from year 2000.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", request_prefix):
        raise ValueError("request_prefix must contain 1–40 safe identifier characters.")
    previous_day = (business_day - timedelta(days=1)).isoformat()
    next_day = (business_day + timedelta(days=1)).isoformat()
    utc_time = datetime.combine(business_day, time(0, 30), tzinfo=timezone(timedelta(hours=7)))
    utc_time = utc_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    checks, tracked = [], []
    code_prefix = request_prefix.upper()

    def call(method, path, *, data=None, params=None):
        response = api.request(method, path, data=data, params=params)
        assert 200 <= response.status_code < 300, (
            f"{method} {path}: unexpected HTTP {response.status_code}"
        )
        result = response.json()
        assert isinstance(result, dict), f"{method} {path}: expected JSON object"
        return result

    def key(label):
        return request_prefix + ":" + label

    def passed(name, **details):
        checks.append({"name": name, "status": "PASS", "details": details})

    def create(resource, data, label):
        record = call("POST", resource, data=data | {"request_key": key(label)})
        tracked.append((resource, record["id"]))
        return record

    def update(resource, record, data, label):
        return call(
            "PUT",
            f"{resource}/{record['id']}",
            data=data
            | {
                "request_key": key(label),
                "expected_version": record["version"],
            },
        )

    def command(record, action, label):
        path = "entries/" + record["id"]
        if action != "delete":
            path += "/" + action
        return call(
            "DELETE" if action == "delete" else "POST",
            path,
            data={
                "request_key": key(label),
                "expected_version": record["version"],
            },
        )

    def list_records(resource):
        return call(
            "GET",
            resource,
            params={
                "page_size": 500,
                "sort": "code",
                "filters": json.dumps({"include_deleted": True}),
            },
        )

    def balances():
        return call(
            "GET", "stock-balances", params={"from_on": previous_day, "through_on": next_day}
        )

    def public_state():
        # A frozen HTTP adapter cannot inspect SQLite audit/request tables. Its
        # rollback proof therefore compares all public documents/history/ledger.
        return _without_cutoff(
            {
                "entries": list_records("entries"),
                "trades": list_records("trades"),
                "payments": list_records("trade-payments"),
                "histories": {
                    resource + "/" + identity: call("GET", f"{resource}/{identity}/history")
                    for resource, identity in tracked
                },
                "ledger": call("GET", "stock-movements", params={"page_size": 500}),
                "balances": balances(),
            }
        )

    def reject_unchanged(name, method, path, data, error_code, *, status=409):
        before = public_state()
        response = api.request(method, path, data=data)
        assert response.status_code == status, (
            f"{name}: expected HTTP {status}, got {response.status_code}"
        )
        envelope = response.json()
        assert envelope["error"]["code"] == error_code, f"{name}: wrong error code"
        assert envelope["request_id"], f"{name}: missing request id"
        after = public_state()
        assert after == before, (
            f"{name}: public documents/history/ledger/balance changed on rejection"
        )
        passed(name, error_code=error_code, public_state_sha256=_digest(before), unchanged=True)

    for resource in (
        "parties",
        "products",
        "products/units",
        "products/warehouses",
        "weighings",
        "entries",
        "trades",
        "trade-payments",
        "price-boards",
        "stock-movements",
    ):
        assert call("GET", resource)["total"] == 0, (
            "The scenario requires a fresh, empty records data root."
        )
    passed("fresh_records_root")

    market_before = call("GET", "market/processed")
    assert market_before["status"] == "NETWORK_DISABLED", (
        "Run the backend with CAFE_FIN_MARKET_NETWORK=0."
    )
    assert market_before["network_available"] is False
    assert market_before["snapshot"] is None and market_before["board_id"] is None
    market_checked = call(
        "POST", "market/processed/check", data={"request_key": key("market-check")}
    )
    assert market_checked["status"] == "NETWORK_DISABLED" and market_checked["attempts"] == 0
    passed(
        "processed_market_network_disabled",
        status=market_checked["status"],
        attempts=0,
        source_url=market_checked["source_url"],
        synthetic_source_applied=False,
    )

    farm = create(
        "parties",
        {
            "code": "F801",
            "name": "Farm kiểm thử Cafe Fin",
            "profile_kind": "farm",
            "type": "person",
            "roles": ["supplier"],
            "farm": {
                "owner_name": "Chủ farm tổng hợp",
                "plots": [
                    {
                        "plot_code": "LO-801",
                        "variety": "Robusta",
                        "area_ha": "1.234",
                        "tree_count": 300,
                    }
                ],
                "surveys": [
                    {"season_year": business_day.year, "grade": 5, "ripeness_pct": "95.125"}
                ],
            },
        },
        "farm",
    )
    company = create(
        "parties",
        {
            "code": code_prefix + "-CO",
            "name": "Công ty kiểm thử Cafe Fin",
            "profile_kind": "customer_company",
            "roles": ["customer"],
            "tax_code": "0312345678",
            "representative": {"name": "Liên hệ tổng hợp"},
            "contacts": [{"kind": "email", "value": "fixture@example.invalid"}],
            "business_license": "GIAY-PHEP-TONG-HOP-801",
            "note": "Dữ liệu tổng hợp, không dùng cho giao dịch thật.",
        },
        "company",
    )
    unit = create("products/units", {"code": code_prefix + "-KG", "name": "Kilôgam"}, "unit")
    raw = create(
        "products",
        {"code": code_prefix + "-RAW", "name": "Quả tươi kiểm thử", "unit_id": unit["id"]},
        "raw-product",
    )
    processed = create(
        "products",
        {
            "code": code_prefix + "-PROCESSED",
            "name": "Hạt chế biến kiểm thử",
            "unit_id": unit["id"],
        },
        "processed-product",
    )
    raw_warehouse = create(
        "products/warehouses",
        {"code": code_prefix + "-RAW-WH", "name": "Kho tươi kiểm thử"},
        "raw-warehouse",
    )
    processed_warehouse = create(
        "products/warehouses",
        {"code": code_prefix + "-PROCESSED-WH", "name": "Kho thành phẩm kiểm thử"},
        "processed-warehouse",
    )
    passed("farm_and_company", farm_code=farm["code"], company_profile=company["profile_kind"])

    weighing = create(
        "weighings",
        {
            "code": code_prefix + "-WEIGH-IN",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "party_id": farm["id"],
            "input_source": "manual",
            "vehicle_plate": "XE-TONG-HOP-801",
            "lines": [
                {
                    "product_id": raw["id"],
                    "quantity_source": "gross_tare",
                    "gross_kg": "1100.250",
                    "tare_kg": "1000.125",
                }
            ],
        },
        "weighing-gross-tare",
    )
    direct_weighing = create(
        "weighings",
        {
            "code": code_prefix + "-WEIGH-OUT",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "party_id": company["id"],
            "input_source": "manual",
            "lines": [
                {"product_id": raw["id"], "quantity_source": "direct_net", "net_kg": "10.001"}
            ],
        },
        "weighing-direct",
    )
    assert weighing["lines"][0]["net_kg"] == "100.125"
    assert (
        direct_weighing["lines"][0]["gross_kg"] is None
        and direct_weighing["lines"][0]["tare_kg"] is None
    )
    assert call("GET", "stock-movements")["total"] == 0 and balances()["items"] == []
    passed(
        "manual_weighings_do_not_move_stock",
        net_in_kg="100.125",
        net_out_kg="10.001",
        missing_weights_preserved=True,
    )

    board_payload = {
        "price_date": occurred_on,
        "price_kind": "purchase_fresh",
        "product_id": None,
        "pricing_method": "grade",
        "grade5_price_vnd": "10000.00",
    }
    preview = call(
        "POST",
        "price-board-preview",
        data={"pricing_method": "grade", "grade5_price_vnd": "10000.00"},
    )
    assert {row["grade"]: row["unit_price_vnd"] for row in preview["grade_prices"]} == {
        5: "10000.00",
        4: "9000.00",
        3: "8100.00",
        2: "7290.00",
        1: "6561.00",
    }
    purchase_board = create("price-boards", board_payload, "purchase-board")
    missing_sale = api.request(
        "GET",
        "price-quote",
        params={"price_kind": "sale", "price_date": occurred_on, "product_id": raw["id"]},
    )
    assert (
        missing_sale.status_code == 422
        and missing_sale.json()["error"]["code"] == "PRICE_NOT_FOUND"
    )
    sale_board = create(
        "price-boards",
        {
            "price_date": occurred_on,
            "price_kind": "sale",
            "product_id": raw["id"],
            "pricing_method": "flat",
            "flat_price_vnd": "20000.00",
        },
        "sale-board",
    )
    purchase_quote = call(
        "GET",
        "price-quote",
        params={
            "price_kind": "purchase_fresh",
            "price_date": occurred_on,
            "product_id": raw["id"],
            "grade": 5,
        },
    )
    sale_quote = call(
        "GET",
        "price-quote",
        params={"price_kind": "sale", "price_date": occurred_on, "product_id": raw["id"]},
    )
    assert (
        purchase_quote["unit_price_vnd"] == "10000.00"
        and sale_quote["unit_price_vnd"] == "20000.00"
    )
    passed(
        "purchase_fresh_manual_sale_separate",
        purchase_grade5_vnd="10000.00",
        sale_flat_vnd="20000.00",
        sale_did_not_fallback_to_purchase=True,
    )

    def trade_line(quantity, quote, *, farm_id=None, grade=None):
        return {
            "farm_id": farm_id,
            "product_id": raw["id"],
            "quantity_kg": quantity,
            "bag_count": 2,
            "grade": grade,
            "pricing_mode": "daily",
            "price_kind": quote["price_kind"],
            "price_date": occurred_on,
            "price_snapshot": copy.deepcopy(quote),
            "unit_price_vnd": quote["unit_price_vnd"],
        }

    inbound = create(
        "trades",
        {
            "code": code_prefix + "-BUY",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "direction": "inbound",
            "party_id": farm["id"],
            "weighing_id": weighing["id"],
            "lines": [trade_line("100.125", purchase_quote, farm_id=farm["id"], grade=5)],
        },
        "inbound",
    )
    outbound = create(
        "trades",
        {
            "code": code_prefix + "-SELL",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "direction": "outbound",
            "party_id": company["id"],
            "weighing_id": direct_weighing["id"],
            "lines": [trade_line("10.001", sale_quote)],
        },
        "outbound",
    )
    assert call("GET", "stock-movements")["total"] == 0 and balances()["items"] == []
    assert call("GET", "trade-payments")["total"] == 0
    passed("trades_do_not_create_stock_or_payments")

    updated_purchase_board = update(
        "price-boards",
        purchase_board,
        _editable(purchase_board) | {"grade5_price_vnd": "11000.00"},
        "edit-purchase-board",
    )
    updated_sale_board = update(
        "price-boards",
        sale_board,
        _editable(sale_board) | {"flat_price_vnd": "21000.00"},
        "edit-sale-board",
    )
    current_purchase_quote = call(
        "GET",
        "price-quote",
        params={
            "price_kind": "purchase_fresh",
            "price_date": occurred_on,
            "product_id": raw["id"],
            "grade": 5,
        },
    )
    current_sale_quote = call(
        "GET",
        "price-quote",
        params={"price_kind": "sale", "price_date": occurred_on, "product_id": raw["id"]},
    )
    assert (
        current_purchase_quote["unit_price_vnd"]
        == updated_purchase_board["grade5_price_vnd"]
        == "11000.00"
    )
    assert (
        current_sale_quote["unit_price_vnd"] == updated_sale_board["flat_price_vnd"] == "21000.00"
    )
    inbound = update(
        "trades", inbound, _editable(inbound) | {"note": "Giữ giá mua đã ghi"}, "edit-buy-note"
    )
    outbound = update(
        "trades", outbound, _editable(outbound) | {"note": "Giữ giá bán đã ghi"}, "edit-sale-note"
    )
    assert inbound["lines"][0]["price_snapshot"] == purchase_quote
    assert outbound["lines"][0]["price_snapshot"] == sale_quote
    assert inbound["lines"][0]["unit_price_vnd"] == "10000.00"
    assert outbound["lines"][0]["unit_price_vnd"] == "20000.00"
    price_proof = {
        "purchase_saved_snapshot": purchase_quote,
        "sale_saved_snapshot": sale_quote,
        "purchase_after_edit": inbound["lines"][0]["price_snapshot"],
        "sale_after_edit": outbound["lines"][0]["price_snapshot"],
        "purchase_current_quote": current_purchase_quote,
        "sale_current_quote": current_sale_quote,
        "purchase_current_board_version": updated_purchase_board["version"],
        "sale_current_board_version": updated_sale_board["version"],
    }
    passed(
        "trade_prices_frozen_after_board_edits",
        original_purchase_version=purchase_quote["price_board_version"],
        original_sale_version=sale_quote["price_board_version"],
    )

    def stock_line(quantity, direction="in", *, product=raw, warehouse=raw_warehouse):
        return {
            "product_id": product["id"],
            "warehouse_id": warehouse["id"],
            "quantity_kg": quantity,
            "direction": direction,
        }

    receipt_payload = {
        "code": code_prefix + "-RECEIPT",
        "occurred_on": occurred_on,
        "occurred_at": utc_time,
        "entry_type": "receipt",
        "status": "draft",
        "party_id": farm["id"],
        "trade_id": inbound["id"],
        "weighing_id": weighing["id"],
        "lines": [stock_line("100.125")],
    }
    receipt = create("entries", receipt_payload, "receipt-create")
    assert (
        call("POST", "entries", data=receipt_payload | {"request_key": key("receipt-create")})
        == receipt
    )
    assert balances()["items"] == []
    draft = copy.deepcopy(receipt)
    receipt = command(draft, "post", "receipt-post")
    assert command(draft, "post", "receipt-post") == receipt
    assert receipt["status"] == "posted" and call("GET", "stock-movements")["total"] == 1
    passed("draft_post_and_idempotent_retries", posted_quantity_kg="100.125", effective_movements=1)
    issue = create(
        "entries",
        {
            "code": code_prefix + "-ISSUE",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "entry_type": "issue",
            "status": "posted",
            "party_id": company["id"],
            "trade_id": outbound["id"],
            "weighing_id": direct_weighing["id"],
            "lines": [stock_line("10.001", "out")],
        },
        "issue",
    )
    production = create(
        "entries",
        {
            "code": code_prefix + "-PRODUCTION",
            "occurred_on": occurred_on,
            "occurred_at": utc_time,
            "entry_type": "production",
            "status": "posted",
            "note": "Nguyên liệu 20.123; thành phẩm 19.111; hao hụt 1.012 kg tổng hợp.",
            "lines": [
                stock_line("20.123", "out"),
                stock_line("19.111", product=processed, warehouse=processed_warehouse),
            ],
        },
        "production",
    )
    passed(
        "receipt_issue_production",
        receipt_kg="100.125",
        issue_kg="10.001",
        production_input_kg="20.123",
        production_output_kg="19.111",
    )

    receipt_before_edit = copy.deepcopy(receipt)
    receipt = update(
        "entries",
        receipt,
        _editable(receipt) | {"note": "Sửa diễn giải, giữ lượng và lịch sử"},
        "receipt-note",
    )
    reject_unchanged(
        "stale_version",
        "PUT",
        "entries/" + receipt["id"],
        _editable(receipt)
        | {
            "expected_version": receipt_before_edit["version"],
            "request_key": key("reject-stale-version"),
        },
        "VERSION_CONFLICT",
    )
    conflicting = copy.deepcopy(receipt_payload)
    conflicting["lines"][0]["quantity_kg"] = "100.124"
    reject_unchanged(
        "same_key_different_payload",
        "POST",
        "entries",
        conflicting | {"request_key": key("receipt-create")},
        "IDEMPOTENCY_CONFLICT",
    )
    reject_unchanged(
        "over_issue",
        "POST",
        "entries",
        {
            "code": code_prefix + "-TOO-MUCH",
            "occurred_on": occurred_on,
            "entry_type": "issue",
            "status": "posted",
            "lines": [stock_line("70.002", "out")],
            "request_key": key("reject-over-issue"),
        },
        "STOCK_NEGATIVE",
    )
    reject_unchanged(
        "duplicate_consumption_lines",
        "POST",
        "entries",
        {
            "code": code_prefix + "-DUPLICATE",
            "occurred_on": occurred_on,
            "entry_type": "issue",
            "status": "posted",
            "lines": [stock_line("35.001", "out"), stock_line("35.001", "out")],
            "request_key": key("reject-duplicate-consumption"),
        },
        "STOCK_NEGATIVE",
    )
    for name, data in (
        ("decrease_receipt", {"lines": [stock_line("30.123")]}),
        ("move_receipt_after_issue", {"occurred_on": next_day, "occurred_at": None}),
    ):
        reject_unchanged(
            name,
            "PUT",
            "entries/" + receipt["id"],
            _editable(receipt)
            | data
            | {"expected_version": receipt["version"], "request_key": key("reject-" + name)},
            "STOCK_NEGATIVE",
        )
    for action in ("delete", "cancel"):
        path = "entries/" + receipt["id"] + ("/cancel" if action == "cancel" else "")
        reject_unchanged(
            action + "_receipt",
            "POST" if action == "cancel" else "DELETE",
            path,
            {
                "expected_version": receipt["version"],
                "request_key": key("reject-" + action + "-receipt"),
            },
            "STOCK_NEGATIVE",
        )
    reject_unchanged(
        "edit_issue_over_stock",
        "PUT",
        "entries/" + issue["id"],
        _editable(issue)
        | {
            "lines": [stock_line("100.126", "out")],
            "expected_version": issue["version"],
            "request_key": key("reject-edit-issue"),
        },
        "STOCK_NEGATIVE",
    )
    reject_unchanged(
        "backdate_issue",
        "PUT",
        "entries/" + issue["id"],
        _editable(issue)
        | {
            "occurred_on": previous_day,
            "occurred_at": None,
            "expected_version": issue["version"],
            "request_key": key("reject-backdate-issue"),
        },
        "STOCK_NEGATIVE",
    )

    issue = command(issue, "delete", "delete-main-issue")
    temporary = create(
        "entries",
        {
            "code": code_prefix + "-TEMPORARY",
            "occurred_on": occurred_on,
            "entry_type": "issue",
            "status": "posted",
            "lines": [stock_line("80.002", "out")],
        },
        "temporary-issue",
    )
    reject_unchanged(
        "restore_issue_would_overspend",
        "POST",
        "entries/" + issue["id"] + "/restore",
        {"expected_version": issue["version"], "request_key": key("reject-restore-issue")},
        "STOCK_NEGATIVE",
    )
    command(temporary, "delete", "delete-temporary-issue")
    issue = command(issue, "restore", "restore-main-issue")
    passed(
        "valid_delete_restore_preserves_final_stock",
        issue_version=issue["version"],
        temporary_entry_soft_deleted=True,
    )

    expected_balances = {
        "raw": {
            "product_id": raw["id"],
            "warehouse_id": raw_warehouse["id"],
            "closing_kg": "70.001",
        },
        "processed": {
            "product_id": processed["id"],
            "warehouse_id": processed_warehouse["id"],
            "closing_kg": "19.111",
        },
    }
    final = balances()
    observed = {(row["product_id"], row["warehouse_id"]): row for row in final["items"]}
    assert len(observed) == 2
    observed_balances = {}
    for name, wanted in expected_balances.items():
        actual = observed[(wanted["product_id"], wanted["warehouse_id"])]
        assert actual["closing_kg"] == wanted["closing_kg"]
        observed_balances[name] = {
            field: actual[field] for field in ("product_id", "warehouse_id", "closing_kg")
        }
    assert final["coverage"] == "entered_records_only"
    assert call("GET", "stock-movements")["total"] == 4
    dashboard = call(
        "GET", "records-dashboard", params={"from_on": occurred_on, "through_on": occurred_on}
    )
    assert (
        dashboard["coverage"] == "entered_records_only"
        and dashboard["inventory"]["cutoff"] == dashboard["cutoff"]
    )
    assert dashboard["counts"] == {
        "farms": 1,
        "farm_surveys": 1,
        "customer_companies": 1,
        "inbound_trades": 1,
        "outbound_trades": 1,
    }
    assert dashboard["period"] == {
        "inbound_kg": "100.125",
        "outbound_kg": "10.001",
        "cash_in_vnd": "0.00",
        "cash_out_vnd": "0.00",
        "sales_order_value_vnd": "200020.00",
        "unpriced_sales_orders": 0,
    }
    assert len(dashboard["daily"]) == 1 and dashboard["daily"][0]["occurred_on"] == occurred_on
    processed_boards = call(
        "GET", "price-boards", params={"filters": json.dumps({"price_kind": "purchase_processed"})}
    )
    assert processed_boards["total"] == 0
    market_after = call("GET", "market/processed")
    assert market_after["status"] == "NETWORK_DISABLED" and market_after["snapshot"] is None
    assert market_after["attempts"] == 0 and market_after["board_id"] is None
    assert call("GET", "trades/" + inbound["id"])["lines"][0]["price_snapshot"] == purchase_quote
    assert call("GET", "trades/" + outbound["id"])["lines"][0]["price_snapshot"] == sale_quote
    passed(
        "final_balances_dashboard_and_source_status",
        raw_kg="70.001",
        processed_kg="19.111",
        cash_in_vnd="0.00",
        cash_out_vnd="0.00",
        sales_order_value_vnd="200020.00",
        effective_movements=4,
        network_status="NETWORK_DISABLED",
    )
    return {
        "fixture_version": 1,
        "coverage": "entered_records_only",
        "occurred_on": occurred_on,
        "occurred_at_utc": utc_time,
        "request_prefix": request_prefix,
        "ids": {
            "farm_id": farm["id"],
            "company_id": company["id"],
            "raw_product_id": raw["id"],
            "processed_product_id": processed["id"],
            "raw_warehouse_id": raw_warehouse["id"],
            "processed_warehouse_id": processed_warehouse["id"],
            "weighing_id": weighing["id"],
            "outbound_weighing_id": direct_weighing["id"],
            "purchase_board_id": purchase_board["id"],
            "sale_board_id": sale_board["id"],
            "inbound_trade_id": inbound["id"],
            "outbound_trade_id": outbound["id"],
            "receipt_id": receipt["id"],
            "issue_id": issue["id"],
            "production_id": production["id"],
            "deleted_temporary_entry_id": temporary["id"],
        },
        "expected_balances": expected_balances,
        "observed_balances": observed_balances,
        "checks": checks,
        "price_snapshot_proof": price_proof,
        "market": {
            field: market_after[field]
            for field in (
                "status",
                "network_available",
                "attempts",
                "source_url",
                "board_id",
                "snapshot",
            )
        },
        "dashboard": {
            field: dashboard[field] for field in ("coverage", "counts", "period", "daily")
        },
        "limitations": [
            "Public HTTP rollback proof excludes private audit/request tables.",
            "This scenario does not attest native GUI, installer, clean-client or live market availability.",
        ],
    }
