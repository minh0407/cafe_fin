"""Synthetic daily pricing through the real authenticated API and SQLite writer."""

import copy
import json

import pytest
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.records.models import Trade
from cafe_fin.records.pricing import LINE_DEFAULTS
from cafe_fin.records.service import RecordsService
from sqlalchemy import select

from .test_records_commerce import commerce, editable, trade_data


def board_data(
    masters,
    *,
    kind="purchase_fresh",
    product=False,
    day="2026-11-01",
    price="100.05",
    method="grade",
):
    return {
        "price_date": day,
        "price_kind": kind,
        "product_id": masters["product"]["id"] if product else None,
        "pricing_method": method,
        "grade5_price_vnd": price if method == "grade" else None,
        "flat_price_vnd": price if method == "flat" else None,
    }


def quote(api, masters, *, kind="purchase_fresh", day="2026-11-01", grade=3):
    params = {"price_kind": kind, "price_date": day, "product_id": masters["product"]["id"]}
    if grade is not None:
        params["grade"] = grade
    return api.get("price-quote", **params)


def daily(masters, value=None, *, code="DAILY-01", direction="inbound"):
    data = trade_data(masters, code=code, direction=direction)
    data["lines"][0].update(
        {
            "pricing_mode": "daily",
            "grade": 3,
            "price_kind": "sale" if direction == "outbound" else "purchase_fresh",
            "price_snapshot": value,
            "unit_price_vnd": value["unit_price_vnd"] if value else None,
        }
    )
    return data


def failed(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code, response.text


def post_trade(api, data):
    return api.request("POST", "trades", data=data | {"request_key": api.key()})


def test_preview_step_half_up_flat_and_zero(records_api):
    api = records_api
    result = api.request(
        "POST", "price-board-preview", data={"pricing_method": "grade", "grade5_price_vnd": "0.05"}
    )
    assert result.status_code == 200
    # Per-step rounding differs from applying 0.9**4 once (0.03).
    assert result.json() == {
        "pricing_method": "grade",
        "flat_price_vnd": None,
        "formula_version": 1,
        "grade_prices": [{"grade": grade, "unit_price_vnd": "0.05"} for grade in (5, 4, 3, 2, 1)],
    }
    for price in ("0", "92233720368547758.07"):
        result = api.request(
            "POST", "price-board-preview", data={"pricing_method": "flat", "flat_price_vnd": price}
        )
        assert result.status_code == 200
        assert result.json()["flat_price_vnd"] == (price + ".00" if price == "0" else price)


@pytest.mark.parametrize(
    "price", ["-0.01", "1.001", "92233720368547758.08", "1e3", "NaN", "Infinity", 12.5, True]
)
def test_preview_rejects_precision_overflow_and_non_decimal_text(records_api, price):
    response = records_api.request(
        "POST", "price-board-preview", data={"pricing_method": "grade", "grade5_price_vnd": price}
    )
    assert response.status_code == 422


def test_board_crud_keys_history_filters_and_soft_deleted_uniqueness(records_api):
    api = records_api
    masters = commerce(api)
    data = board_data(masters)
    board = api.create("price-boards", data, key="board-create")
    assert board["code"] == "purchase_fresh:2026-11-01:all"
    assert board["grade5_price_vnd"] == "100.05"
    assert api.create("price-boards", data, key="board-create") == board
    assert (
        api.request("POST", "price-boards", data=data | {"request_key": api.key()}).status_code
        == 409
    )
    for override in (
        {"price_date": "2026-11-02"},
        {"price_kind": "purchase_processed"},
        {"product_id": masters["product"]["id"]},
    ):
        failed(
            api.replace("price-boards", board, editable(board) | override),
            422,
            "PRICE_KEY_IMMUTABLE",
        )
    updated = api.replace(
        "price-boards", board, editable(board) | {"grade5_price_vnd": "200.00"}
    ).json()
    assert updated["version"] == 2
    assert api.replace("price-boards", board, data).status_code == 409
    deleted = api.command("price-boards", updated, "delete").json()
    assert api.get("price-boards")["total"] == 0
    assert (
        api.request("POST", "price-boards", data=data | {"request_key": api.key()}).status_code
        == 409
    )
    restored = api.command("price-boards", deleted, "restore").json()
    assert restored["version"] == 4
    api.create(
        "price-boards",
        board_data(masters, kind="sale", product=True, day="2026-11-02", method="flat"),
    )
    filters = {
        "price_kind": "sale",
        "price_date": "2026-11-02",
        "product_id": masters["product"]["id"],
    }
    rows = api.get("price-boards", filters=json.dumps(filters), sort="-price_date", page_size=1)
    assert rows["total"] == 1 and rows["items"][0]["price_kind"] == "sale"
    history = api.get(f"price-boards/{board['id']}/history")["items"]
    assert [row["action"] for row in history] == ["restore", "delete", "update", "create"]
    assert history[-1]["data"]["grade5_price_vnd"] == "100.05"
    with api.runtime.reader() as conn:
        assert len(conn.execute(select(AUDIT).where(AUDIT.c.entity_id == board["id"])).all()) == 4


def test_lookup_exact_day_priority_separate_sale_and_grade_requirement(records_api):
    api = records_api
    masters = commerce(api)
    common = api.create("price-boards", board_data(masters))
    assert quote(api, masters)["price_board_id"] == common["id"]
    failed(
        api.request(
            "GET",
            "price-quote",
            params={"price_kind": "purchase_fresh", "price_date": "2026-11-02"},
        ),
        422,
        "PRICE_NOT_FOUND",
    )
    failed(
        api.request(
            "GET",
            "price-quote",
            params={"price_kind": "purchase_fresh", "price_date": "2026-11-01"},
        ),
        422,
        "PRICE_GRADE_REQUIRED",
    )
    product = api.create("price-boards", board_data(masters, product=True, price="200.00"))
    assert quote(api, masters)["unit_price_vnd"] == "162.00"
    assert quote(api, masters)["price_board_id"] == product["id"]
    deactivated = api.replace("price-boards", product, editable(product) | {"active": False}).json()
    assert quote(api, masters)["price_board_id"] == common["id"]
    assert deactivated["active"] is False
    failed(
        api.request(
            "GET",
            "price-quote",
            params={
                "price_kind": "sale",
                "price_date": "2026-11-01",
                "product_id": masters["product"]["id"],
            },
        ),
        422,
        "PRICE_NOT_FOUND",
    )
    assert (
        api.request(
            "POST",
            "price-boards",
            data=board_data(masters, kind="sale", method="flat") | {"request_key": api.key()},
        ).status_code
        == 422
    )
    sale = api.create(
        "price-boards", board_data(masters, kind="sale", product=True, method="flat", price="500")
    )
    sale_quote = quote(api, masters, kind="sale", grade=None)
    assert sale_quote["unit_price_vnd"] == "500.00" and sale_quote["grade"] is None
    assert sale_quote["price_board_id"] == sale["id"]


def test_daily_authoritative_price_and_exact_order_value(records_api):
    api = records_api
    masters = commerce(api)
    api.create(
        "price-boards", board_data(masters, kind="sale", product=True, method="flat", price="0.01")
    )
    value = quote(api, masters, kind="sale")
    data = daily(masters, value, direction="outbound")
    data["lines"][0]["quantity_kg"] = "0.001"
    trade = api.create("trades", data)
    assert trade["lines"][0]["unit_price_vnd"] == "0.01"
    assert trade["lines"][0]["price_date"] == data["occurred_on"]
    assert (
        api.get("records-dashboard", from_on="2026-11-01", through_on="2026-11-01")["period"][
            "sales_order_value_vnd"
        ]
        == "0.00001"
    )
    assert api.get("stock-movements")["total"] == 0
    for price in ("0.02", "0"):
        bad = copy.deepcopy(data)
        bad["lines"][0]["unit_price_vnd"] = price
        failed(post_trade(api, bad), 422, "PRICE_MISMATCH")
    no_snapshot = daily(masters, direction="outbound", code="SERVER-QUOTE")
    assert api.create("trades", no_snapshot)["lines"][0]["price_snapshot"] == value
    bad = daily(masters, direction="outbound")
    bad["lines"][0]["price_kind"] = "purchase_fresh"
    failed(post_trade(api, bad), 422, "PRICE_KIND_MISMATCH")


@pytest.mark.parametrize("change", ["update", "deactivate", "delete"])
def test_frozen_snapshot_survives_board_change_but_new_line_stale_fails(records_api, change):
    api = records_api
    masters = commerce(api)
    board = api.create("price-boards", board_data(masters))
    value = quote(api, masters)
    trade = api.create("trades", daily(masters, value))
    if change == "delete":
        assert api.command("price-boards", board, "delete").status_code == 200
    else:
        override = {"grade5_price_vnd": "999.99"} if change == "update" else {"active": False}
        assert api.replace("price-boards", board, editable(board) | override).status_code == 200
    edit = editable(trade)
    edit["lines"][0].update({"quantity_kg": "2.345", "bag_count": 4, "note": "Giữ giá đã xác nhận"})
    updated = api.replace("trades", trade, edit)
    assert updated.status_code == 200, updated.text
    assert updated.json()["lines"][0]["price_snapshot"] == value
    tampered = copy.deepcopy(edit)
    tampered["lines"][0]["unit_price_vnd"] = "0.01"
    failed(api.replace("trades", updated.json(), tampered), 422, "PRICE_MISMATCH")
    history = api.get(f"price-boards/{board['id']}/history")["items"]
    historical = next(
        row["data"] for row in history if row["version"] == value["price_board_version"]
    )
    assert historical["grade5_price_vnd"] == "100.05"
    failed(post_trade(api, daily(masters, value, code="STALE-COPY")), 409, "PRICE_CHANGED")
    # A duplicated historical line cannot consume the same saved permission twice.
    duplicate = copy.deepcopy(edit)
    duplicate["lines"].append(copy.deepcopy(edit["lines"][0]))
    failed(api.replace("trades", updated.json(), duplicate), 409, "PRICE_CHANGED")
    nulled = copy.deepcopy(edit)
    nulled["lines"][0]["price_snapshot"] = None
    failed(api.replace("trades", updated.json(), nulled), 422, "PRICE_SNAPSHOT_REQUIRED")


@pytest.mark.parametrize(
    "field,value",
    [
        ("unit_price_vnd", "0.01"),
        ("price_board_version", 9000),
        ("formula_version", 2),
        ("product_id", None),
        ("grade", 5),
    ],
)
def test_forged_snapshots_rejected_on_create_and_update(records_api, field, value):
    api = records_api
    masters = commerce(api)
    api.create("price-boards", board_data(masters))
    valid = quote(api, masters)
    trade = api.create("trades", daily(masters, valid))
    forged = valid | {field: value}
    data = daily(masters, forged, code="FORGED")
    assert post_trade(api, data).status_code == 422
    assert api.replace("trades", trade, data).status_code == 422


def test_reorder_criteria_change_explicit_date_and_no_null_refresh(records_api):
    api = records_api
    masters = commerce(api)
    board = api.create("price-boards", board_data(masters))
    first = quote(api, masters)
    second = quote(api, masters, grade=4)
    data = daily(masters, first)
    other = copy.deepcopy(data["lines"][0])
    other.update({"grade": 4, "unit_price_vnd": second["unit_price_vnd"], "price_snapshot": second})
    data["lines"].append(other)
    trade = api.create("trades", data)
    board = api.replace(
        "price-boards", board, editable(board) | {"grade5_price_vnd": "500.00"}
    ).json()
    edit = editable(trade)
    edit["lines"].reverse()
    reordered = api.replace("trades", trade, edit)
    assert reordered.status_code == 200, reordered.text
    assert [line["price_snapshot"] for line in reordered.json()["lines"]] == [second, first]
    edit = editable(reordered.json())
    edit["occurred_on"] = "2026-11-02"
    failed(api.replace("trades", reordered.json(), edit), 409, "PRICE_CHANGED")
    # Day changed with explicit price_date: fresh quote for that selected day is valid.
    for line in edit["lines"]:
        fresh = quote(api, masters, grade=line["grade"])
        line.update({"price_snapshot": fresh, "unit_price_vnd": fresh["unit_price_vnd"]})
    changed = api.replace("trades", reordered.json(), edit)
    assert changed.status_code == 200, changed.text
    bad_grade = editable(changed.json())
    bad_grade["lines"][0]["grade"] = 5
    failed(api.replace("trades", changed.json(), bad_grade), 422, "PRICE_SNAPSHOT_INVALID")
    bad_grade["lines"][0]["price_snapshot"] = None
    failed(api.replace("trades", changed.json(), bad_grade), 422, "PRICE_SNAPSHOT_REQUIRED")


def test_refreshed_quote_changes_grade_then_delete_restore_and_retry(records_api):
    api = records_api
    masters = commerce(api)
    board = api.create("price-boards", board_data(masters, kind="purchase_processed"))
    value = quote(api, masters, kind="purchase_processed")
    data = daily(masters, value)
    data["lines"][0]["price_kind"] = "purchase_processed"
    trade = api.create("trades", data, key="daily-create-retry")
    board = api.replace(
        "price-boards", board, editable(board) | {"grade5_price_vnd": "200.00"}
    ).json()
    assert api.create("trades", data, key="daily-create-retry") == trade
    fresh = quote(api, masters, kind="purchase_processed", grade=5)
    edit = editable(trade)
    edit["lines"][0].update(
        {"grade": 5, "price_snapshot": fresh, "unit_price_vnd": fresh["unit_price_vnd"]}
    )
    updated = api.replace("trades", trade, edit)
    assert updated.status_code == 200, updated.text
    assert updated.json()["lines"][0]["unit_price_vnd"] == "200.00"
    api.command("price-boards", board, "delete")
    deleted = api.command("trades", updated.json(), "delete")
    assert deleted.status_code == 200, deleted.text
    restored = api.command("trades", deleted.json(), "restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["lines"][0]["price_snapshot"] == fresh


def test_legacy_trade_request_fingerprint_and_revisions_are_unchanged(records_api, monkeypatch):
    import cafe_fin.records.service as records_service

    api = records_api
    masters = commerce(api)
    data = trade_data(masters)
    legacy = Trade.model_validate(data | {"request_key": "legacy-trade"}).model_dump(
        mode="json", exclude={"request_key", "expected_version"}
    )
    for line in legacy["lines"]:
        for field in LINE_DEFAULTS:
            line.pop(field)
    normalizer = records_service.normalize_trade
    monkeypatch.setattr(records_service, "normalize_trade", lambda *args: None)
    original = RecordsService(api.runtime)._execute(
        "trades", legacy, api.principal, "legacy-trade", None, None, "create"
    )
    monkeypatch.setattr(records_service, "normalize_trade", normalizer)
    assert "pricing_mode" not in original["lines"][0]
    replayed = api.create("trades", data, key="legacy-trade")
    assert replayed["id"] == original["id"] and replayed["lines"][0]["pricing_mode"] == "manual"
    assert (
        api.get(f"trades/{original['id']}/history")["items"][0]["data"]["lines"][0][
            "price_snapshot"
        ]
        is None
    )
    with api.runtime.reader() as conn:
        assert (
            len(
                conn.execute(select(REQUESTS).where(REQUESTS.c.request_key == "legacy-trade")).all()
            )
            == 1
        )
