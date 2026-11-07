"""Synthetic farm/trade workflows use the real SQLite writer and HTTP API."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from cafe_fin.core.db import AUDIT, REQUESTS, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.records.service import RecordsService
from sqlalchemy import select


def editable(record):
    return {
        key: value
        for key, value in record.items()
        if key
        not in {
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
    }


def commerce(api):
    masters = api.masters()
    farm = api.create(
        "parties",
        {
            "code": "F001",
            "name": "Farm tổng hợp",
            "profile_kind": "farm",
            "farm": {
                "owner_name": "Chủ vườn tổng hợp",
                "owner_id_card": "synthetic-id",
                "plots": [
                    {
                        "plot_code": "LO-01",
                        "area_ha": "1.234",
                        "tree_count": 300,
                        "tree_age": 4,
                        "variety": "Robusta",
                    }
                ],
                "surveys": [{"season_year": 2026, "grade": 3, "ripeness_pct": "90.125"}],
            },
        },
    )
    customer = api.create(
        "parties",
        {
            "code": "CT-01",
            "name": "Công ty tổng hợp",
            "profile_kind": "customer_company",
            "tax_code": "SYNTHETIC-MST",
            "representative": {"name": "Liên hệ tổng hợp"},
            "business_license": "SYNTHETIC-LICENSE",
        },
    )
    return masters | {"farm": farm, "customer": customer}


def trade_data(masters, *, direction="inbound", code="TRADE-01", quantity="10.000", price="100.25"):
    return {
        "code": code,
        "occurred_on": "2026-11-01",
        "direction": direction,
        "party_id": masters["customer"]["id"] if direction == "outbound" else None,
        "lines": [
            {
                "farm_id": masters["farm"]["id"] if direction == "inbound" else None,
                "product_id": masters["product"]["id"],
                "quantity_kg": quantity,
                "unit_price_vnd": price,
                "bag_count": 2,
                "grade": 3,
            }
        ],
    }


def linked_entry(
    api, masters, trade, quantity, *, code="SHIP-01", day="2026-11-02", status="posted"
):
    kind = "receipt" if trade["direction"] == "inbound" else "issue"
    data = api.entry_data(masters, quantity, code=code, day=day, kind=kind)
    return data | {
        "trade_id": trade["id"],
        "status": status,
        "party_id": trade["party_id"] if kind == "issue" else masters["farm"]["id"],
    }


def payment_data(masters, trade, *, code="PAY-01", amount="123.45"):
    return {
        "code": code,
        "occurred_on": "2026-11-01",
        "trade_id": trade["id"],
        "party_id": (masters["customer"] if trade["direction"] == "outbound" else masters["farm"])[
            "id"
        ],
        "amount_vnd": amount,
        "method": "bank_transfer",
        "reference": "synthetic reference",
    }


def test_farm_profile_code_immutability_precision_and_filters(records_api):
    api = records_api
    masters = commerce(api)
    farm = masters["farm"]
    assert farm["farm"]["plots"][0]["area_ha"] == "1.234"
    assert farm["farm"]["surveys"][0]["ripeness_pct"] == "90.125"
    for code in ("AB", "ABC-", "ABCDE"):
        response = api.request(
            "POST",
            "parties",
            data=editable(farm)
            | {
                "code": code,
                "request_key": api.key(),
            },
        )
        assert response.status_code == 422, response.text
    normalized = api.create(
        "parties", {"code": " abc1 ", "name": "Normalized Farm", "profile_kind": "farm"}
    )
    assert normalized["code"] == "ABC1"
    optional_plot = {
        "code": " f003 ",
        "name": "Optional plot",
        "profile_kind": "farm",
        "farm": {"plots": [{"area_ha": "0.001"}]},
    }
    created_plot = api.create("parties", optional_plot, key="normalized-farm-retry")
    assert api.create("parties", optional_plot, key="normalized-farm-retry") == created_plot
    assert created_plot["farm"]["plots"][0]["plot_code"] is None
    unchanged = api.replace("parties", farm, editable(farm) | {"code": " f001 "})
    assert unchanged.status_code == 200
    farm = unchanged.json()
    duplicate = api.request("POST", "parties", data=editable(farm) | {"request_key": api.key()})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CODE_CONFLICT"
    changed = api.replace("parties", farm, editable(farm) | {"code": "F002"})
    assert changed.status_code == 422
    assert changed.json()["error"]["code"] == "FARM_CODE_IMMUTABLE"
    data = editable(farm)
    data["farm"]["surveys"][0]["ripeness_pct"] = "100.001"
    assert api.replace("parties", farm, data).status_code == 422
    data["farm"]["surveys"][0]["ripeness_pct"] = "99.9999"
    assert api.replace("parties", farm, data).status_code == 422
    assert api.get("parties", filters=json.dumps({"profile_kind": "farm"}))["total"] == 3
    assert api.get("parties", filters=json.dumps({"profile_kind": "general"}))["total"] == 1
    # Same MST is allowed; no speculative uniqueness constraint.
    api.create("parties", editable(masters["customer"]) | {"code": "CT-02"})


def test_outbound_company_requirements_and_trade_validation(records_api):
    api = records_api
    masters = commerce(api)
    incomplete = api.create(
        "parties", {"code": "CT-X", "name": "Chưa đủ", "profile_kind": "customer_company"}
    )
    data = trade_data(masters, direction="outbound") | {"party_id": incomplete["id"]}
    bad = api.request("POST", "trades", data=data | {"request_key": api.key()})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "CUSTOMER_INCOMPLETE"
    for field, value in (
        ("quantity_kg", "0"),
        ("quantity_kg", "1.0001"),
        ("unit_price_vnd", "-1"),
        ("unit_price_vnd", "0.001"),
        ("quantity_kg", 1.5),
        ("bag_count", -1),
        ("grade", 6),
    ):
        data = trade_data(masters)
        data["lines"][0][field] = value
        assert (
            api.request("POST", "trades", data=data | {"request_key": api.key()}).status_code == 422
        )
    data = trade_data(masters)
    data["lines"][0]["farm_id"] = masters["party"]["id"]
    assert api.request("POST", "trades", data=data | {"request_key": api.key()}).status_code == 422
    trade = api.create("trades", trade_data(masters, direction="outbound"))
    assert api.get("stock-movements")["total"] == 0  # Orders never move inventory.
    assert api.get("trades", filters=json.dumps({"direction": "outbound"}))["total"] == 1
    data = editable(masters["customer"]) | {"tax_code": None}
    assert api.replace("parties", masters["customer"], data).status_code == 422
    assert api.get(f"trades/{trade['id']}")["version"] == 1


def test_shipment_caps_edits_restore_trade_identity_and_chronological_stock(records_api):
    api = records_api
    masters = commerce(api)
    trade = api.create("trades", trade_data(masters))
    first = api.create("entries", linked_entry(api, masters, trade, "6"))
    second_data = linked_entry(api, masters, trade, "4", code="SHIP-02", day="2026-11-03")
    second = api.create("entries", second_data)
    over = linked_entry(api, masters, trade, "0.001", code="SHIP-OVER")
    assert api.request("POST", "entries", data=over | {"request_key": api.key()}).status_code == 409
    assert (
        api.replace(
            "entries",
            first,
            editable(first)
            | {
                "lines": [api.line(masters, "7")],
            },
        ).status_code
        == 409
    )
    reduced = trade_data(masters, quantity="9")
    assert api.replace("trades", trade, reduced).status_code == 409
    assert (
        api.replace("trades", trade, trade_data(masters, direction="outbound")).status_code == 409
    )
    assert api.command("trades", trade, "delete").status_code == 409
    assert (
        api.replace("trades", trade, trade_data(masters) | {"status": "cancelled"}).status_code
        == 409
    )
    # Releasing a shipment frees the cap; restoring the old one cannot over-deliver.
    deleted_second = api.command("entries", second, "delete").json()
    api.create("entries", linked_entry(api, masters, trade, "4", code="SHIP-03"))
    assert api.command("entries", deleted_second, "restore").status_code == 409
    issue = api.create(
        "entries", api.entry_data(masters, "9", code="ISSUE-01", day="2026-11-04", kind="issue")
    )
    # Old receipt deletion, reducing quantity, cancellation and moving after issue all preserve chronology.
    for command in ("delete", "cancel"):
        response = api.command("entries", first, command)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STOCK_NEGATIVE"
    for override in ({"occurred_on": "2026-11-05"}, {"lines": [api.line(masters, "4")]}):
        response = api.replace("entries", first, editable(first) | override)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STOCK_NEGATIVE"
    assert api.get(f"entries/{issue['id']}")["version"] == 1
    assert api.get(f"entries/{first['id']}")["version"] == 1
    assert api.get("entries", filters=json.dumps({"trade_id": trade["id"]}))["total"] == 2


def test_links_direction_company_and_unallocated_inbound_product(records_api):
    api = records_api
    masters = commerce(api)
    inbound_data = trade_data(masters)
    inbound_data["lines"][0]["product_id"] = None
    inbound = api.create("trades", inbound_data)
    receipt = linked_entry(api, masters, inbound, "1")
    assert (
        api.request("POST", "entries", data=receipt | {"request_key": api.key()}).status_code == 409
    )
    wrong = receipt | {"entry_type": "issue", "status": "draft"}
    assert (
        api.request("POST", "entries", data=wrong | {"request_key": api.key()}).status_code == 409
    )
    allocated = api.create("trades", trade_data(masters, code="ALLOCATED"))
    wrong_farm = linked_entry(api, masters, allocated, "1") | {
        "party_id": masters["customer"]["id"]
    }
    assert (
        api.request("POST", "entries", data=wrong_farm | {"request_key": api.key()}).status_code
        == 409
    )
    api.create(
        "entries", linked_entry(api, masters, allocated, "1", code="GROUPED") | {"party_id": None}
    )
    other_farm = api.create(
        "parties", {"code": "F002", "name": "Farm thứ hai", "profile_kind": "farm"}
    )
    changed_farm = editable(allocated)
    changed_farm["lines"][0]["farm_id"] = other_farm["id"]
    assert api.replace("trades", allocated, changed_farm).status_code == 409
    outbound = api.create("trades", trade_data(masters, direction="outbound", code="OUTBOUND"))
    wrong = linked_entry(api, masters, outbound, "1", status="draft") | {
        "party_id": masters["party"]["id"]
    }
    assert (
        api.request("POST", "entries", data=wrong | {"request_key": api.key()}).status_code == 409
    )
    draft = api.create(
        "entries", linked_entry(api, masters, outbound, "2", code="DRAFT", status="draft")
    )
    assert api.command("trades", outbound, "delete").status_code == 409
    assert api.command("entries", draft, "post").json()["error"]["code"] == "STOCK_NEGATIVE"


def test_payments_decimal_retry_version_history_delete_restore(records_api):
    api = records_api
    masters = commerce(api)
    trade = api.create("trades", trade_data(masters))
    data = payment_data(masters, trade)
    payment = api.create("trade-payments", data, key="payment-retry")
    assert api.create("trade-payments", data, key="payment-retry") == payment
    assert payment["amount_vnd"] == "123.45"
    assert api.get("stock-movements")["total"] == 0
    bad = api.request(
        "POST",
        "trade-payments",
        data=data
        | {
            "amount_vnd": "123.46",
            "request_key": "payment-retry",
        },
    )
    assert bad.status_code == 409
    for amount in ("0", "-1", "1.001", "92233720368547758.08", 1.5):
        assert (
            api.request(
                "POST",
                "trade-payments",
                data=data
                | {
                    "code": api.key(),
                    "amount_vnd": amount,
                    "request_key": api.key(),
                },
            ).status_code
            == 422
        )
    wrong = api.request(
        "POST",
        "trade-payments",
        data=data
        | {
            "code": "WRONG",
            "party_id": masters["customer"]["id"],
            "request_key": api.key(),
        },
    )
    assert wrong.status_code == 409
    updated = api.replace("trade-payments", payment, data | {"amount_vnd": "124.01"}).json()
    assert api.replace("trade-payments", payment, data).status_code == 409
    assert api.command("trades", trade, "delete").status_code == 409
    removed = api.command("trade-payments", updated, "delete").json()
    deleted_trade = api.command("trades", trade, "delete").json()
    assert api.command("trade-payments", removed, "restore").status_code == 409
    api.command("trades", deleted_trade, "restore")
    restored = api.command("trade-payments", removed, "restore").json()
    assert restored["version"] == 4
    history = api.get(f"trade-payments/{payment['id']}/history")
    assert [row["action"] for row in history["items"]] == ["restore", "delete", "update", "create"]
    assert api.get("trade-payments", filters=json.dumps({"trade_id": trade["id"]}))["total"] == 1
    with api.runtime.reader() as conn:
        audits = conn.execute(select(AUDIT).where(AUDIT.c.entity_id == payment["id"])).all()
        assert len(audits) == 4
        receipts = conn.execute(
            select(REQUESTS).where(REQUESTS.c.request_key == "payment-retry")
        ).all()
        assert len(receipts) == 1


def test_two_real_writers_cannot_over_ship_one_trade(records_api):
    api = records_api
    masters = commerce(api)
    trade = api.create("trades", trade_data(masters))
    database2 = Database(api.runtime.database.path, create=False)
    writer2 = WriteCoordinator(database2)
    runtime2 = SimpleNamespace(
        database=database2, reader=database2.read, writer=writer2, auth=api.runtime.auth
    )
    barrier = threading.Barrier(2)

    def ship(runtime, code):
        barrier.wait(timeout=10)
        try:
            return RecordsService(runtime).save(
                "entries",
                linked_entry(api, masters, trade, "7", code=code),
                actor=api.principal,
                request_key=code,
            )
        except CoreError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(ship, runtime, code)
                for runtime, code in ((api.runtime, "CONCURRENT-1"), (runtime2, "CONCURRENT-2"))
            ]
            results = [future.result(timeout=20) for future in futures]
        assert sum(isinstance(result, dict) for result in results) == 1
        assert [result.code for result in results if isinstance(result, CoreError)] == [
            "TRADE_CONFLICT"
        ]
        assert api.get("entries")["total"] == 1
        assert api.get("stock-movements")["total"] == 1
        assert api.stock()["items"][0]["closing_kg"] == "7.000"
    finally:
        writer2.close()
        database2.close()


def test_outbound_caps_by_product_across_warehouses_and_repeated_lines(records_api):
    api = records_api
    masters = commerce(api)
    warehouse2 = api.create("products/warehouses", {"code": "W-02", "name": "Kho tổng hợp 2"})
    product2 = api.create("products", {"code": "P-02", "name": "Hàng tổng hợp 2"})
    api.create("entries", api.entry_data(masters, "20", code="SUPPLY-A"))
    api.create(
        "entries",
        api.entry_data(masters, "20", code="SUPPLY-B")
        | {"lines": [api.line(masters, "20", warehouse=warehouse2)]},
    )
    api.create(
        "entries",
        api.entry_data(masters, "10", code="SUPPLY-C")
        | {"lines": [api.line(masters, "10", product=product2)]},
    )
    trade = api.create("trades", trade_data(masters, direction="outbound"))
    api.create(
        "entries",
        linked_entry(api, masters, trade, "6", code="MULTI-WAREHOUSE")
        | {
            "lines": [
                api.line(masters, "3", "out"),
                api.line(masters, "3", "out", warehouse=warehouse2),
            ]
        },
    )
    api.create("entries", linked_entry(api, masters, trade, "4", code="FINAL-SHIPMENT"))
    for product in (masters["product"], product2):
        response = api.request(
            "POST",
            "entries",
            data=linked_entry(api, masters, trade, "0.001", code="EXCEEDS")
            | {
                "lines": [api.line(masters, "0.001", "out", product=product)],
                "request_key": api.key(),
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "TRADE_CONFLICT"
    # Prices/notes may change without changing the shipment's business identity.
    revised = editable(trade)
    revised["lines"][0]["unit_price_vnd"] = "200.50"
    assert api.replace("trades", trade, revised).status_code == 200


def test_pre_increment_revision_and_pending_request_replay_stay_compatible(
    records_api, monkeypatch
):
    import cafe_fin.records.service as records_service

    api = records_api
    service = RecordsService(api.runtime)
    masters = api.masters()
    old_party = editable(masters["party"]) | {"code": "LEGACY", "name": "Legacy synthetic"}
    for field in ("profile_kind", "farm", "business_license"):
        old_party.pop(field, None)
    old_entry = api.entry_data(masters, "2", code="LEGACY-ENTRY")
    # A synthetic pre-upgrade writer keeps v1 JSON/receipt without additive fields;
    # immutable revisions are never rewritten to manufacture upgrade coverage.
    normalize = records_service.normalize_commerce
    monkeypatch.setattr(records_service, "normalize_commerce", lambda *args: None)
    party = service._execute(
        "parties", old_party, api.principal, "legacy-party-replay", None, None, "create"
    )
    entry = service._execute(
        "entries",
        old_entry
        | {
            "occurred_at": None,
            "physical_actor": None,
            "note": None,
            "weighing_id": None,
            "commercial_amount_vnd": None,
            "lines": [old_entry["lines"][0] | {"note": None}],
        },
        api.principal,
        "legacy-entry-replay",
        None,
        None,
        "create",
    )
    monkeypatch.setattr(records_service, "normalize_commerce", normalize)
    assert "profile_kind" not in party and "trade_id" not in entry
    replayed = api.create("parties", old_party, key="legacy-party-replay")
    assert replayed["id"] == party["id"]
    assert replayed["profile_kind"] == "general"
    replayed_entry = api.create("entries", old_entry, key="legacy-entry-replay")
    assert replayed_entry["id"] == entry["id"]
    assert replayed_entry["trade_id"] is None
    assert api.get(f"parties/{party['id']}")["farm"] is None
    assert api.get(f"entries/{entry['id']}/history")["items"][0]["data"]["trade_id"] is None
    deleted = api.command("entries", entry, "delete").json()
    assert api.command("entries", deleted, "restore").status_code == 200
    assert api.get("stock-movements")["total"] == 1
