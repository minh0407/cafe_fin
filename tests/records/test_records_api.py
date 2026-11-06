"""Business-level invariants through the actual records router, writer and SQLite WAL."""

import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from cafe_fin.core.contracts import (
    InventorySummaryDTO,
    PartyDTO,
    ReceivableSummaryDTO,
    WeighingDTO,
)


def error(response, code=None):
    assert response.status_code >= 400, response.text
    envelope = response.json()
    assert envelope["request_id"]
    assert set(envelope["error"]) == {"code", "message", "field_errors", "details"}
    if code:
        assert envelope["error"]["code"] == code, envelope
    return envelope["error"]


def snapshot(api):
    """Include domain revisions, ledger, request receipts and audit to prove rollback."""
    with api.runtime.reader() as conn:
        names = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name LIKE 'records_%' OR name IN ('core_audit','core_requests')) ORDER BY name"
        ).scalars().all()
        return {
            name: sorted(
                (tuple(row) for row in conn.exec_driver_sql('SELECT * FROM "' + name + '"')),
                key=repr,
            ) for name in names
        }


def balances(api):
    return {
        (row["product_id"], row["warehouse_id"]): row["closing_kg"]
        for row in api.stock()["items"]
    }


def history_items(api, resource, identity):
    result = api.get(f"{resource}/{identity}/history")
    return result["items"] if isinstance(result, dict) else result


def test_master_crud_multiple_roles_deactivation_and_referenced_history(records_api):
    api = records_api
    masters = api.masters()
    party, product = masters["party"], masters["product"]
    assert str(UUID(party["id"])) == party["id"]
    assert party["roles"] == ["customer", "supplier"]
    entry = api.create("entries", api.entry_data(masters, "10.001"))
    party_payload = {
        "code": party["code"], "name": "Đối tác đã ngừng", "type": party["type"],
        "roles": party["roles"], "contacts": [], "active": False,
    }
    response = api.replace("parties", party, party_payload)
    assert response.status_code == 200, response.text
    assert response.json()["active"] is False
    product_payload = {
        "code": product["code"], "name": "Cà phê ngừng dùng", "unit_id": masters["unit"]["id"],
        "active": False,
    }
    response = api.replace("products", product, product_payload)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == product["version"] + 1
    assert api.get("entries/" + entry["id"])["party_id"] == party["id"]
    assert api.get("entries/" + entry["id"])["lines"][0]["product_id"] == product["id"]
    assert len(history_items(api, "parties", party["id"])) == 2
    assert len(history_items(api, "products", product["id"])) == 2
    assert balances(api)[(product["id"], masters["warehouse"]["id"])] == "10.001"


def test_weighings_two_manual_modes_preserve_missing_values_without_stock_effect(records_api):
    api = records_api
    masters = api.masters()
    before = api.get("stock-movements")
    direct = api.create("weighings", {
        "code": "CAN-TINH", "occurred_on": "2026-11-01", "party_id": masters["party"]["id"],
        "lines": [{"quantity_source": "direct_net", "net_kg": "123.001"}],
    })
    assert direct["lines"][0]["gross_kg"] is None
    assert direct["lines"][0]["tare_kg"] is None
    assert direct["lines"][0]["net_kg"] == "123.001"
    gross = api.create("weighings", {
        "code": "CAN-DAY-RONG", "occurred_on": "2026-11-01",
        "lines": [{"quantity_source": "gross_tare", "gross_kg": "1200.125", "tare_kg": "100.024"}],
    })
    assert gross["lines"][0]["net_kg"] == "1100.101"
    assert api.get("stock-movements") == before
    assert api.stock()["items"] == []


@pytest.mark.parametrize("line", [
    {"quantity_source": "direct_net"},
    {"quantity_source": "gross_tare", "gross_kg": "100.000"},
    {"quantity_source": "gross_tare", "gross_kg": "10.000", "tare_kg": "11.000"},
    {"quantity_source": "direct_net", "net_kg": "1.0001"},
    {"quantity_source": "direct_net", "net_kg": 1.5},
])
def test_invalid_weighing_is_not_replaced_by_fake_zero(records_api, line):
    api = records_api
    before = snapshot(api)
    response = api.request("POST", "weighings", data={
        "request_key": api.key(), "code": "CAN-LOI", "occurred_on": "2026-11-01", "lines": [line],
    })
    error(response)
    assert snapshot(api) == before


def test_receipt_issue_production_exact_ledger_balance_and_breakdown(records_api):
    api = records_api
    masters = api.masters()
    output = api.create("products", {"code": "CP-02", "name": "Cà phê thành phẩm"})
    api.create("entries", api.entry_data(masters, "100.125"))
    api.create("entries", api.entry_data(masters, "10.001", code="PX-01", day="2026-11-02", kind="issue"))
    api.create("entries", {
        "code": "SX-01", "occurred_on": "2026-11-03", "entry_type": "production", "status": "posted",
        "lines": [api.line(masters, "50.123", "out"), api.line(masters, "48.111", product=output)],
    })
    result = balances(api)
    assert result[(masters["product"]["id"], masters["warehouse"]["id"])] == "40.001"
    assert result[(output["id"], masters["warehouse"]["id"])] == "48.111"
    movements = api.get("stock-movements")["items"]
    assert len(movements) == 4
    assert sorted(row["delta_kg"] for row in movements) == ["-10.001", "-50.123", "100.125", "48.111"]
    stock = api.stock()
    assert stock["coverage"] == "entered_records_only"
    assert {row["entry_type"] for row in stock["breakdown"]} == {"receipt", "issue", "production"}


def test_overissue_and_repeated_consumption_lines_are_rejected_atomically(records_api):
    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "50.000"))
    output = api.create("products", {"code": "OUT", "name": "Thành phẩm"})
    for data in (
        api.entry_data(masters, "50.001", code="PX-TOO-MUCH", kind="issue"),
        {
            "code": "SX-REPEAT", "occurred_on": "2026-11-02", "entry_type": "production", "status": "posted",
            "lines": [api.line(masters, "25.000", "out"), api.line(masters, "26.000", "out"),
                      api.line(masters, "49.000", product=output)],
        },
    ):
        before = snapshot(api)
        response = api.request("POST", "entries", data=data | {"request_key": api.key()})
        details = error(response, "STOCK_NEGATIVE")["details"]
        assert details["balance_kg"].startswith("-")
        assert snapshot(api) == before


@pytest.mark.parametrize("mutation", ["reduce", "delete", "cancel", "move_date"])
def test_historical_negative_on_edit_cancel_delete_or_date_move_rolls_back_all(records_api, mutation):
    api = records_api
    masters = api.masters()
    payload = api.entry_data(masters, "10.000", day="2026-11-01")
    receipt = api.create("entries", payload)
    issue = api.create("entries", api.entry_data(masters, "8.000", code="PX", day="2026-11-02", kind="issue"))
    api.create("entries", api.entry_data(masters, "10.000", code="PN-LATER", day="2026-11-03"))
    before = snapshot(api)
    if mutation == "reduce":
        response = api.replace("entries", receipt, payload | {"lines": [api.line(masters, "7.000")]})
    elif mutation == "move_date":
        response = api.replace("entries", receipt, payload | {"occurred_on": "2026-11-03"})
    else:
        response = api.command("entries", receipt, mutation)
    detail = error(response, "STOCK_NEGATIVE")["details"]
    assert detail["occurred_on"] == "2026-11-02"
    assert detail["related_entry_id"] == issue["id"]
    assert snapshot(api) == before
    assert api.get("entries/" + receipt["id"]) == receipt
    assert balances(api)[(masters["product"]["id"], masters["warehouse"]["id"])] == "12.000"


def test_backdated_issue_rejects_negative_prefix_even_with_positive_closing(records_api):
    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "10.000", day="2026-11-03"))
    before = snapshot(api)
    response = api.request("POST", "entries", data=api.entry_data(
        masters, "1.000", code="PX-BACKDATE", day="2026-11-02", kind="issue",
    ) | {"request_key": api.key()})
    error(response, "STOCK_NEGATIVE")
    assert snapshot(api) == before


def test_valid_edit_delete_restore_preserves_history_without_double_effect(records_api):
    api = records_api
    masters = api.masters()
    receipt_data = api.entry_data(masters, "10.000")
    receipt = api.create("entries", receipt_data)
    issue = api.create("entries", api.entry_data(masters, "8.000", code="PX", day="2026-11-02", kind="issue"))
    response = api.replace("entries", receipt, receipt_data | {"lines": [api.line(masters, "9.000")]})
    assert response.status_code == 200, response.text
    history = history_items(api, "entries", receipt["id"])
    assert len(history) == 2
    assert {row["version"]: row["data"]["lines"][0]["quantity_kg"] for row in history} == {
        1: "10.000", 2: "9.000",
    }
    assert list(balances(api).values()) == ["1.000"]
    response = api.command("entries", issue, "delete")
    assert response.status_code == 200, response.text
    deleted = response.json()
    assert deleted["deleted_at"] is not None
    assert list(balances(api).values()) == ["9.000"]
    response = api.command("entries", deleted, "restore")
    assert response.status_code == 200, response.text
    assert response.json()["deleted_at"] is None
    assert list(balances(api).values()) == ["1.000"]
    assert len(api.get("stock-movements")["items"]) == 2
    assert len(history_items(api, "entries", issue["id"])) == 3


def test_restoring_old_issue_cannot_overspend_stock_consumed_since_delete(records_api):
    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "10.000"))
    issue = api.create("entries", api.entry_data(masters, "8.000", code="PX-OLD", day="2026-11-02", kind="issue"))
    response = api.command("entries", issue, "delete")
    assert response.status_code == 200, response.text
    deleted = response.json()
    api.create("entries", api.entry_data(masters, "7.000", code="PX-NEW", day="2026-11-03", kind="issue"))
    before = snapshot(api)
    response = api.command("entries", deleted, "restore")
    error(response, "STOCK_NEGATIVE")
    assert snapshot(api) == before


def test_retry_conflict_stale_version_and_exact_decimal_validation(records_api):
    api = records_api
    masters = api.masters()
    payload = api.entry_data(masters, "10.001")
    key = "receipt-replay"
    entry = api.create("entries", payload, key=key)
    before = snapshot(api)
    assert api.create("entries", payload, key=key) == entry
    assert snapshot(api) == before
    response = api.request("POST", "entries", data=payload | {"request_key": key, "note": "Khác dữ liệu"})
    error(response, "IDEMPOTENCY_CONFLICT")
    assert snapshot(api) == before
    response = api.replace("entries", entry, payload | {"note": "Bản mới"})
    assert response.status_code == 200, response.text
    before = snapshot(api)
    error(api.replace("entries", entry, payload | {"note": "Bản cũ"}), "VERSION_CONFLICT")
    assert snapshot(api) == before
    for value in ("0.0001", "9223372036854775.808", "NaN", "1e3", 1.5):
        response = api.request("POST", "entries", data=api.entry_data(
            masters, value, code="BAD-" + api.key(),
        ) | {"request_key": api.key()})
        error(response)
        assert snapshot(api) == before


def test_draft_does_not_affect_stock_until_explicit_post(records_api):
    api = records_api
    masters = api.masters()
    data = api.entry_data(masters, "10.000") | {"status": "draft"}
    draft = api.create("entries", data)
    assert api.stock()["items"] == []
    assert api.get("stock-movements")["items"] == []
    key = "post-draft-once"
    response = api.command("entries", draft, "post", key=key)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "posted"
    assert list(balances(api).values()) == ["10.000"]
    assert api.command("entries", draft, "post", key=key).json() == response.json()
    assert len(api.get("stock-movements")["items"]) == 1


def test_typed_read_bridge_cutoff_dates_and_no_side_effect(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters = api.masters()
    weighing = api.create("weighings", {
        "code": "CAN-BRIDGE", "occurred_on": "2026-11-01", "party_id": masters["party"]["id"],
        "lines": [{"quantity_source": "direct_net", "net_kg": "10.001"}],
    })
    payload = api.entry_data(masters, "10.001") | {"commercial_amount_vnd": "123456.78"}
    receipt = api.create("entries", payload)
    before_edit = datetime.now(timezone.utc)
    response = api.replace("entries", receipt, payload | {
        "lines": [api.line(masters, "12.001")], "commercial_amount_vnd": "200000.00",
    })
    assert response.status_code == 200, response.text
    api.create("entries", api.entry_data(masters, "2.000", code="PX-NEXT", day="2026-11-02", kind="issue"))
    provider = RecordsReadProvider(api.runtime, api.principal)
    before = snapshot(api)
    party_dto = provider.lookup_party(masters["party"]["id"])
    weighing_dto = provider.get_weighing(weighing["id"])
    assert isinstance(party_dto, PartyDTO)
    assert party_dto.roles == ("customer", "supplier")
    assert isinstance(weighing_dto, WeighingDTO)
    assert weighing_dto.lines[0].gross_kg is None
    assert weighing_dto.lines[0].net_kg == "10.001"
    historic = provider.inventory_summary(date(2026, 11, 1), date(2026, 11, 1), cutoff=before_edit)
    assert isinstance(historic, InventorySummaryDTO)
    assert historic.items[0].closing_kg == "10.001"
    historic_money = provider.receivable_summary(date(2026, 11, 1), cutoff=before_edit)
    assert isinstance(historic_money, ReceivableSummaryDTO)
    assert historic_money.items[0].amount_vnd == "123456.78"
    now = datetime.now(timezone.utc)
    current = provider.inventory_summary(date(2026, 11, 2), date(2026, 11, 2), cutoff=now)
    assert current.coverage == "entered_records_only"
    assert current.items[0].opening_kg == "12.001"
    assert current.items[0].issued_kg == "2.000"
    assert current.items[0].closing_kg == "10.001"
    assert current.cutoff == now
    assert snapshot(api) == before
    # API dates are Vietnam business dates. The equivalent UTC/Vietnam cutoffs agree.
    cutoff_vn = now.astimezone(timezone(timedelta(hours=7)))
    assert provider.inventory_summary(date(2026, 11, 2), date(2026, 11, 2), cutoff=cutoff_vn) == current
    assert provider.lookup_party("00000000-0000-0000-0000-000000000000") is None


def test_server_paging_search_filters_and_invalid_filter_rejection(records_api):
    api = records_api
    masters = api.masters()
    for n in range(3):
        api.create("entries", api.entry_data(masters, "1.000", code=f"PN-{n}", day=f"2026-11-0{n+1}"))
    response = api.get("entries", page=2, page_size=1, sort="code", search="PN-")
    assert response["total"] == 3
    assert response["page"] == 2 and response["page_size"] == 1
    assert response["items"][0]["code"] == "PN-1"
    response = api.get("entries", filters=json.dumps({"from_on": "2026-11-02", "through_on": "2026-11-02"}))
    assert response["total"] == 1
    assert response["items"][0]["occurred_on"] == "2026-11-02"
    error(api.request("GET", "entries", params={"filters": '{"unexpected":true}'}))
    error(api.request("GET", "entries", params={"page_size": 501}))


def test_moving_receipt_to_another_scope_checks_old_and_new_warehouse(records_api):
    api = records_api
    masters = api.masters()
    second = api.create("products/warehouses", {"code": "KHO-02", "name": "Kho thứ hai"})
    payload = api.entry_data(masters, "10.000")
    receipt = api.create("entries", payload)
    api.create("entries", api.entry_data(masters, "5.000", code="PX", day="2026-11-02", kind="issue"))
    before = snapshot(api)
    moved = payload | {"lines": [api.line(masters, "10.000", warehouse=second)]}
    error(api.replace("entries", receipt, moved), "STOCK_NEGATIVE")
    assert snapshot(api) == before


def test_same_scope_production_output_cannot_finance_its_own_consumption(records_api):
    api = records_api
    masters = api.masters()
    before = snapshot(api)
    response = api.request("POST", "entries", data={
        "request_key": api.key(), "code": "SX-KHONG-NGUON", "occurred_on": "2026-11-01",
        "entry_type": "production", "status": "posted",
        "lines": [api.line(masters, "9.000", "in"), api.line(masters, "9.000", "out")],
    })
    error(response, "STOCK_NEGATIVE")
    assert snapshot(api) == before


def test_transfer_requires_matching_product_totals_and_moves_stock_once(records_api):
    api = records_api
    masters = api.masters()
    other = api.create("products/warehouses", {"code": "KHO-02", "name": "Kho đích"})
    api.create("entries", api.entry_data(masters, "10.000"))
    transfer = {
        "code": "CHUYEN-01", "occurred_on": "2026-11-02", "entry_type": "transfer", "status": "posted",
        "lines": [api.line(masters, "3.001", "out"), api.line(masters, "3.001", warehouse=other)],
    }
    api.create("entries", transfer)
    stock = balances(api)
    assert stock[(masters["product"]["id"], masters["warehouse"]["id"])] == "6.999"
    assert stock[(masters["product"]["id"], other["id"])] == "3.001"
    before = snapshot(api)
    bad = transfer | {"code": "CHUYEN-LOI", "lines": [
        api.line(masters, "1.000", "out"), api.line(masters, "1.001", warehouse=other),
    ]}
    error(api.request("POST", "entries", data=bad | {"request_key": api.key()}))
    assert snapshot(api) == before


def test_aggregate_commercial_balance_can_exceed_int64_without_float(records_api):
    api = records_api
    masters = api.masters()
    for n in range(2):
        api.create("entries", api.entry_data(masters, "1.000", code=f"PN-LARGE-{n}") | {
            "commercial_amount_vnd": "92233720368547758.07",
        })
    result = api.get("receivables", as_of="2026-11-01")
    assert result["coverage"] == "entered_records_only"
    assert result["items"] == [{"party_id": masters["party"]["id"], "amount_vnd": "184467440737095516.14"}]
    with api.runtime.reader() as conn:
        tables = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars().all()
        assert not any(name.startswith("accounting_") for name in tables)


def test_operator_can_record_finish_and_edit_without_approval(records_api):
    api = records_api
    masters = api.masters()
    api.runtime.auth.create_user(
        api.principal, username="records-operator", password="synthetic-operator-password",
        role="operator", request_key="operator-account",
    )
    session = api.runtime.auth.login("records-operator", "synthetic-operator-password")
    api.headers = api.headers | {"Authorization": "Bearer " + session["access_token"]}
    payload = api.entry_data(masters, "1.001")
    entry = api.create("entries", payload)
    assert entry["status"] == "posted"
    response = api.replace("entries", entry, payload | {"note": "Nhân viên tự sửa"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "posted"
    assert list(balances(api).values()) == ["1.001"]


@pytest.mark.parametrize("occurred_at,valid", [
    ("2026-11-01T17:00:00Z", True),
    ("2026-11-02T00:00:00+07:00", True),
    ("2026-11-01T16:59:59Z", False),
    ("2026-11-02T17:00:00Z", False),
    ("2026-11-02T00:00:00", False),
])
def test_business_timestamp_is_validated_at_vietnam_midnight(records_api, occurred_at, valid):
    api = records_api
    masters = api.masters()
    data = api.entry_data(masters, "1.000", day="2026-11-02") | {"occurred_at": occurred_at}
    before = snapshot(api)
    response = api.request("POST", "entries", data=data | {"request_key": api.key()})
    if valid:
        assert response.status_code == 200, response.text
        assert response.json()["occurred_on"] == "2026-11-02"
        assert api.stock("2026-11-01", "2026-11-01")["items"] == []
        assert list(balances(api).values()) == ["1.000"]
    else:
        error(response)
        assert snapshot(api) == before


@pytest.mark.parametrize("output_kg,valid", [("9.999", True), ("10.000", True), ("10.001", False)])
def test_production_cannot_increase_weight_without_recorded_input(records_api, output_kg, valid):
    api = records_api
    masters = api.masters()
    output = api.create("products", {"code": "SX-OUT", "name": "Sản phẩm sau chế biến"})
    api.create("entries", api.entry_data(masters, "10.000"))
    before = snapshot(api)
    response = api.request("POST", "entries", data={
        "request_key": api.key(), "code": "SX-INPUT-LIMIT", "occurred_on": "2026-11-02",
        "entry_type": "production", "status": "posted",
        "lines": [api.line(masters, "10.000", "out"), api.line(masters, output_kg, product=output)],
    })
    if valid:
        assert response.status_code == 200, response.text
        result = balances(api)
        assert result[(masters["product"]["id"], masters["warehouse"]["id"])] == "0.000"
        assert result[(output["id"], masters["warehouse"]["id"])] == output_kg
    else:
        error(response)
        assert snapshot(api) == before


def test_exported_openapi_exposes_typed_records_and_decimal_text_contract(records_api):
    # Consumers generate clients from this actual schema; an untyped {} response loses
    # nullable weights, optimistic version fields and the decimal-string guarantee.
    schema = records_api.client.app.openapi()
    components = schema["components"]["schemas"]

    def dereference(value):
        return components[value["$ref"].rsplit("/", 1)[-1]]

    for resource in ("parties", "products", "products/units", "products/warehouses", "weighings", "entries"):
        path = "/api/v1/records/" + resource
        for suffix, methods in (("", ("get", "post")), ("/{document_id}", ("get", "put", "delete")),
                                ("/{document_id}/history", ("get",)), ("/{document_id}/restore", ("post",))):
            for method in methods:
                operation = schema["paths"][path + suffix][method]
                assert operation["security"] == [{"AppSession": [], "LocalUser": []}]
                response = dereference(operation["responses"]["200"]["content"]["application/json"]["schema"])
                assert response["type"] == "object"
                assert response["properties"]
        saved = dereference(schema["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["schema"])
        assert {"id", "version", "order_key"} <= set(saved["required"])
        assert "request_key" not in saved["properties"]
        assert "expected_version" not in saved["properties"]
    weighing_response = schema["paths"]["/api/v1/records/weighings"]["post"]["responses"]["200"]
    weighing = dereference(weighing_response["content"]["application/json"]["schema"])
    weight_line = dereference(weighing["properties"]["lines"]["items"])
    for quantity in ("gross_kg", "tare_kg", "net_kg"):
        assert {item["type"] for item in weight_line["properties"][quantity]["anyOf"]} == {"string", "null"}
    for resource in ("stock-movements", "stock-balances", "receivables"):
        response = schema["paths"]["/api/v1/records/" + resource]["get"]["responses"]["200"]
        assert dereference(response["content"]["application/json"]["schema"])["properties"]
