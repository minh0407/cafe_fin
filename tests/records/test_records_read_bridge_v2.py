"""V2 movement semantics from real records ledger/provider/API, not DTO-only fixtures."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from cafe_fin.core.contracts import InventorySummaryDTO
from cafe_fin.core.db import canonical_json
from sqlalchemy import insert

COMPONENTS = (
    "purchased_kg", "sold_kg", "production_input_kg", "production_output_kg",
    "transfer_in_kg", "transfer_out_kg", "adjustment_in_kg", "adjustment_out_kg",
)
DAY = date(2026, 11, 1)
CUTOFF = datetime(2030, 1, 1, tzinfo=timezone.utc)


def provider(api):
    from cafe_fin.records.module import RecordsReadProvider

    return RecordsReadProvider(api.runtime, api.principal)


def scaled(value):
    whole, _, fraction = value.partition(".")
    return int(whole) * 1000 + int(fraction.ljust(3, "0"))


def expected(**values):
    return dict.fromkeys(COMPONENTS, "0.000") | values


def components(summary):
    assert summary.breakdown_version == 1
    assert summary.movement_breakdown is not None
    totals = {(row.product_id, row.warehouse_id): row for row in summary.items}
    parts = {(row.product_id, row.warehouse_id): row for row in summary.movement_breakdown}
    assert totals.keys() == parts.keys()
    assert len(parts) == len(summary.movement_breakdown) == len(summary.items)
    result = {}
    for scope, row in parts.items():
        data = row.model_dump(exclude={"product_id", "warehouse_id", "product_name", "warehouse_name"})
        assert set(data) == set(COMPONENTS)
        assert all(isinstance(value, str) and not value.startswith("-") for value in data.values())
        total = totals[scope]
        assert sum(scaled(data[key]) for key in (
            "purchased_kg", "production_output_kg", "transfer_in_kg", "adjustment_in_kg",
        )) == scaled(total.received_kg)
        assert sum(scaled(data[key]) for key in (
            "sold_kg", "production_input_kg", "transfer_out_kg", "adjustment_out_kg",
        )) == scaled(total.issued_kg)
        assert scaled(total.opening_kg) + scaled(total.received_kg) - scaled(total.issued_kg) == scaled(total.closing_kg)
        result[scope] = data
    return result


def test_v2_all_eight_components_from_posted_ledger_and_http_preserve_loss_and_transfers(records_api):
    api = records_api
    masters = api.masters()
    output = api.create("products", {"code": "CP-FINISHED", "name": "Thành phẩm"})
    destination = api.create("products/warehouses", {"code": "KHO-02", "name": "Kho nhận"})
    api.create("entries", api.entry_data(masters, "100.125", kind="opening", code="OPEN") | {"note": "Tồn đầu đã nhập"})
    api.create("entries", api.entry_data(masters, "20.001", code="BUY"))
    api.create("entries", api.entry_data(masters, "10.002", kind="issue", code="SELL", day="2026-11-02"))
    api.create("entries", {
        "code": "PRODUCTION", "occurred_on": "2026-11-03", "entry_type": "production", "status": "posted",
        "lines": [api.line(masters, "30.123", "out"), api.line(masters, "28.111", product=output)],
        "note": "Hao hụt 2.012 kg đã nhập",
    })
    api.create("entries", {
        "code": "TRANSFER", "occurred_on": "2026-11-04", "entry_type": "transfer", "status": "posted",
        "lines": [api.line(masters, "5.003", "out"), api.line(masters, "5.003", warehouse=destination)],
    })
    for quantity, direction in (("2.004", "in"), ("1.005", "out")):
        api.create("entries", {
            "code": "ADJUST-" + direction, "occurred_on": "2026-11-05", "entry_type": "adjustment", "status": "posted",
            "note": "Căn cứ điều chỉnh tổng hợp", "lines": [api.line(masters, quantity, direction)],
        })
    summary = provider(api).inventory_summary(DAY, date(2026, 11, 5), cutoff=CUTOFF)
    result = components(summary)
    raw = masters["product"]["id"], masters["warehouse"]["id"]
    assert result == {
        raw: expected(purchased_kg="20.001", sold_kg="10.002", production_input_kg="30.123",
            transfer_out_kg="5.003", adjustment_in_kg="102.129", adjustment_out_kg="1.005"),
        (masters["product"]["id"], destination["id"]): expected(transfer_in_kg="5.003"),
        (output["id"], masters["warehouse"]["id"]): expected(production_output_kg="28.111"),
    }
    assert "opening_entries_in_adjustments" in summary.validation_flags
    raw_total = next(row for row in summary.items if (row.product_id, row.warehouse_id) == raw)
    assert (raw_total.received_kg, raw_total.issued_kg, raw_total.closing_kg) == ("122.130", "46.133", "75.997")
    response = api.get("stock-balances", from_on="2026-11-01", through_on="2026-11-05", cutoff=CUTOFF.isoformat())
    standard = {key: response[key] for key in InventorySummaryDTO.model_fields}
    assert InventorySummaryDTO.model_validate_json(canonical_json(standard)) == summary
    assert {row["entry_type"] for row in response["breakdown"]} == {
        "opening", "receipt", "issue", "production", "transfer", "adjustment",
    }


def test_v2_empty_and_opening_only_scopes_have_known_zero_period_components(records_api):
    api = records_api
    masters = api.masters()
    reader = provider(api)
    empty = reader.inventory_summary(DAY, DAY, cutoff=CUTOFF)
    assert empty.items == ()
    assert empty.breakdown_version == 1 and empty.movement_breakdown == ()
    api.create("entries", api.entry_data(masters, "3.123", kind="opening", code="OPEN-BEFORE") | {"note": "Đã nhập căn cứ"})
    future = api.create("products", {"code": "FUTURE", "name": "Chưa có trong kỳ"})
    api.create("entries", api.entry_data(masters, "2.001", code="FUTURE-RECEIPT", day="2026-11-04") | {
        "lines": [api.line(masters, "2.001", product=future)],
    })
    opening_only = reader.inventory_summary(date(2026, 11, 2), date(2026, 11, 3), cutoff=CUTOFF)
    assert components(opening_only) == {
        (masters["product"]["id"], masters["warehouse"]["id"]): expected(),
    }
    row = opening_only.items[0]
    assert (row.opening_kg, row.received_kg, row.issued_kg, row.closing_kg) == ("3.123", "0.000", "0.000", "3.123")
    assert "opening_entries_in_adjustments" not in opening_only.validation_flags
    assert all(item.product_id != future["id"] for item in opening_only.items)


def test_v2_cutoff_versions_edit_cancel_post_delete_restore_do_not_double_classify(records_api):
    api = records_api
    masters = api.masters()
    payload = api.entry_data(masters, "10.001")
    entry = api.create("entries", payload)
    states = [(datetime.now(timezone.utc), "10.001")]
    response = api.replace("entries", entry, payload | {"lines": [api.line(masters, "12.003")]})
    assert response.status_code == 200, response.text
    entry = response.json()
    states.append((datetime.now(timezone.utc), "12.003"))
    for command, quantity in (("cancel", None), ("post", "12.003"), ("delete", None), ("restore", "12.003")):
        response = api.command("entries", entry, command)
        assert response.status_code == 200, response.text
        entry = response.json()
        states.append((datetime.now(timezone.utc), quantity))
    reader = provider(api)
    for cutoff, quantity in states:
        summary = reader.inventory_summary(DAY, DAY, cutoff=cutoff)
        assert "inventory_movement_classification_unknown" not in summary.validation_flags
        if quantity is None:
            assert summary.items == () and summary.movement_breakdown == ()
            assert summary.breakdown_version == 1
        else:
            assert components(summary) == {
                (masters["product"]["id"], masters["warehouse"]["id"]): expected(purchased_kg=quantity),
            }
            assert summary.items[0].closing_kg == quantity


def test_v2_period_components_aggregate_past_int64_without_overflow_or_float(records_api):
    api = records_api
    masters = api.masters()
    maximum = "9223372036854775.807"
    for n in range(2):
        api.create("entries", api.entry_data(masters, maximum, code=f"REPLENISH-{n}"))
        api.create("entries", api.entry_data(masters, maximum, code=f"CONSUME-{n}", kind="issue"))
    summary = provider(api).inventory_summary(DAY, DAY, cutoff=CUTOFF)
    aggregate = "18446744073709551.614"
    assert components(summary) == {
        (masters["product"]["id"], masters["warehouse"]["id"]): expected(purchased_kg=aggregate, sold_kg=aggregate),
    }
    assert (summary.items[0].received_kg, summary.items[0].issued_kg, summary.items[0].closing_kg) == (aggregate, aggregate, "0.000")
    response = api.get("stock-balances", from_on=DAY.isoformat(), through_on=DAY.isoformat(), cutoff=CUTOFF.isoformat())
    assert response["movement_breakdown"][0]["purchased_kg"] == aggregate
    assert response["movement_breakdown"][0]["sold_kg"] == aggregate


def append_legacy_movement(api, masters, *, entry_type, direction, delta, day="2026-11-02"):
    """Trusted synthetic legacy fixture: append D/R/M only; never rewrite immutable rows."""
    from cafe_fin.records.migrations import DOCUMENTS, MOVEMENTS, REVISIONS

    identity = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def insert_legacy(conn):
        inserted = conn.execute(insert(DOCUMENTS).values(
            id=identity, kind="entries", code_key="legacy-" + identity,
            version=1, created_at=timestamp, created_by=api.principal.id,
        ))
        data = {"id": identity, "version": 1, "status": "posted", "deleted_at": None,
                "occurred_on": day, "entry_type": entry_type, "party_id": None,
                "commercial_amount_vnd": None}
        conn.execute(insert(REVISIONS).values(document_id=identity, version=1, recorded_at=timestamp,
            actor=api.principal.id, action="synthetic_legacy_fixture", data_json=canonical_json(data),
            occurred_on=day, status="posted", commercial_scaled=None, deleted_at=None))
        conn.execute(insert(MOVEMENTS).values(id=str(uuid4()), entry_id=identity, version=1,
            product_id=masters["product"]["id"], warehouse_id=masters["warehouse"]["id"],
            direction=direction, delta_scaled=delta, occurred_on=day,
            order_key=f"{inserted.inserted_primary_key[0]:020d}1", entry_type=entry_type, line_numbers="[1]"))

    api.runtime.writer.run(insert_legacy)


@pytest.mark.parametrize("entry_type,direction,delta", [
    ("unclassified_return", "in", 1000),
    ("receipt", "out", -1000),
    ("receipt", "in", -1000),
    ("receipt", "unclassified_direction", 1000),
])
def test_v2_unknown_period_type_direction_or_sign_yields_null_breakdown_for_all_scopes(records_api, entry_type, direction, delta):
    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "10.000"))
    other = api.create("products/warehouses", {"code": "KNOWN-KHO", "name": "Kho có phân loại"})
    api.create("entries", api.entry_data(masters, "2.000", code="KNOWN", day="2026-11-02") | {
        "lines": [api.line(masters, "2.000", warehouse=other)],
    })
    append_legacy_movement(api, masters, entry_type=entry_type, direction=direction, delta=delta)
    summary = provider(api).inventory_summary(date(2026, 11, 2), date(2026, 11, 2), cutoff=CUTOFF)
    assert len(summary.items) == 2
    assert summary.breakdown_version is None
    assert summary.movement_breakdown is None
    assert "inventory_movement_classification_unknown" in summary.validation_flags
    raw = next(row for row in summary.items if row.warehouse_id == masters["warehouse"]["id"])
    assert raw.opening_kg == "10.000"
    assert (raw.received_kg, raw.issued_kg) == (("1.000", "0.000") if delta > 0 else ("0.000", "1.000"))
    response = api.get("stock-balances", from_on="2026-11-02", through_on="2026-11-02", cutoff=CUTOFF.isoformat())
    assert response["breakdown_version"] is None and response["movement_breakdown"] is None
    assert "inventory_movement_classification_unknown" in response["validation_flags"]


def test_v2_unknown_movement_before_period_is_opening_not_an_invented_period_component(records_api):
    api = records_api
    masters = api.masters()
    append_legacy_movement(api, masters, entry_type="unclassified_return", direction="in", delta=1000, day="2026-11-01")
    api.create("entries", api.entry_data(masters, "2.003", code="KNOWN", day="2026-11-02"))
    summary = provider(api).inventory_summary(date(2026, 11, 2), date(2026, 11, 2), cutoff=CUTOFF)
    assert components(summary) == {
        (masters["product"]["id"], masters["warehouse"]["id"]): expected(purchased_kg="2.003"),
    }
    assert summary.items[0].opening_kg == "1.000"
    assert summary.items[0].closing_kg == "3.003"
    assert "inventory_movement_classification_unknown" not in summary.validation_flags


def test_v2_connection_bound_decomposition_follows_the_callers_snapshot(records_api):
    api = records_api
    masters = api.masters()
    payload = api.entry_data(masters, "10.001")
    entry = api.create("entries", payload)
    reader = provider(api)
    scope = masters["product"]["id"], masters["warehouse"]["id"]
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = reader.bind_connection(conn)
        assert type(bound) is type(reader)
        assert components(bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)) == {scope: expected(purchased_kg="10.001")}
        response = api.replace("entries", entry, payload | {
            "entry_type": "adjustment", "note": "Phân loại lại theo dữ liệu người nhập",
            "lines": [api.line(masters, "15.003")],
        })
        assert response.status_code == 200, response.text
        assert components(bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)) == {scope: expected(purchased_kg="10.001")}
        assert components(reader.inventory_summary(DAY, DAY, cutoff=CUTOFF)) == {scope: expected(adjustment_in_kg="15.003")}
        assert not conn.closed and conn.connection.driver_connection.in_transaction
