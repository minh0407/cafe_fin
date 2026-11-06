from datetime import date, datetime, timezone

import pytest
from cafe_fin.core.contracts import (
    BookSummaryDTO,
    InventoryLineDTO,
    InventoryMovementSummaryDTO,
    InventorySummaryDTO,
    MappedBookMetricDTO,
)
from pydantic import ValidationError

PERIOD = dict(
    from_on=date(2026, 11, 6),
    through_on=date(2026, 11, 6),
    cutoff=datetime(2026, 11, 6, 12, tzinfo=timezone.utc),
)


def movement(product="bean", warehouse="A", **changes):
    values = dict.fromkeys(
        (
            "purchased_kg",
            "sold_kg",
            "production_input_kg",
            "production_output_kg",
            "transfer_in_kg",
            "transfer_out_kg",
            "adjustment_in_kg",
            "adjustment_out_kg",
        ),
        "0",
    )
    values.update(changes)
    return InventoryMovementSummaryDTO(product_id=product, warehouse_id=warehouse, **values)


def line(product="bean", warehouse="A", opening="0", received="0", issued="0", closing="0"):
    return InventoryLineDTO(
        product_id=product,
        warehouse_id=warehouse,
        opening_kg=opening,
        received_kg=received,
        issued_kg=issued,
        closing_kg=closing,
    )


def test_inventory_categories_reconcile_without_counting_production_or_transfer_as_purchase():
    summary = InventorySummaryDTO(
        **PERIOD,
        breakdown_version=1,
        items=(
            line(received="11", issued="6", closing="5"),
            line(warehouse="B", received="2", issued="1", closing="1"),
            line(product="roasted", received="3", closing="3"),
        ),
        movement_breakdown=(
            movement(
                purchased_kg="10",
                production_input_kg="4",
                transfer_out_kg="2",
                adjustment_in_kg="1",
            ),
            movement(warehouse="B", transfer_in_kg="2", adjustment_out_kg="1"),
            movement(product="roasted", production_output_kg="3"),
        ),
    )
    assert sum(int(part.purchased_kg) for part in summary.movement_breakdown) == 10
    assert sum(int(item.received_kg) for item in summary.items) == 16
    # Production is allowed to lose kg; transfer cancels only across both warehouses.
    assert summary.movement_breakdown[0].production_input_kg == "4"
    assert summary.movement_breakdown[2].production_output_kg == "3"
    assert (
        summary.movement_breakdown[0].transfer_out_kg
        == summary.movement_breakdown[1].transfer_in_kg
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"movement_breakdown": ()},
        {"movement_breakdown": (movement(), movement())},
        {"movement_breakdown": (movement(warehouse="B"),)},
        {"movement_breakdown": (movement(purchased_kg="1"),)},
        {"movement_breakdown": (movement(sold_kg="1"),)},
        {"items": (line(closing="1"),)},
        {"items": (line(), line())},
        {"breakdown_version": None},
        {"breakdown_version": True},
        {"breakdown_version": 1.0},
        {"breakdown_version": 2},
    ],
)
def test_inventory_rejects_partial_duplicate_or_inconsistent_breakdown(changes):
    values = dict(PERIOD, items=(line(),), breakdown_version=1, movement_breakdown=(movement(),))
    values.update(changes)
    with pytest.raises(ValidationError):
        InventorySummaryDTO(**values)


@pytest.mark.parametrize("value", ["-0.001", "1.0001", "1e3", 0.5])
def test_movement_components_require_nonnegative_exact_text(value):
    with pytest.raises(ValidationError):
        movement(purchased_kg=value)


def test_unknown_breakdown_stays_null_and_large_aggregate_is_exact():
    legacy = InventorySummaryDTO(**PERIOD, items=(line(),))
    assert legacy.breakdown_version is legacy.movement_breakdown is None
    with pytest.raises(ValidationError):
        InventorySummaryDTO(**PERIOD, movement_breakdown=())
    InventorySummaryDTO(**PERIOD, breakdown_version=1, movement_breakdown=())
    huge = str(10**80 + 1) + ".001"
    value = InventorySummaryDTO(
        **PERIOD,
        items=(line(received=huge, closing=huge),),
        breakdown_version=1,
        movement_breakdown=(movement(purchased_kg=huge),),
    )
    assert value.items[0].closing_kg == huge
    with pytest.raises(ValidationError):
        InventorySummaryDTO(
            **PERIOD,
            items=(line(received=huge, closing=str(10**80) + ".001"),),
            breakdown_version=1,
            movement_breakdown=(movement(purchased_kg=huge),),
        )


def metric(key, amount, meaning=None):
    return MappedBookMetricDTO(key=key, amount_vnd=amount, mapping_revision=1, meaning=meaning)


def book(*metrics, **changes):
    values = dict(PERIOD, book_id="book-A", has_valid_money_mapping=True, metrics=metrics)
    values.update(changes)
    return BookSummaryDTO(**values)


def test_money_meaning_is_explicit_and_deposits_are_subsets_of_cash_totals():
    unknown = metric("income", "-1")
    assert unknown.meaning is None  # A key alone does not turn arbitrary data into cash.
    value = book(
        metric("thu", "100", "cash_receipts"),
        metric("coc_thu", "20", "cash_receipt_deposits"),
        metric("chi", "40", "cash_payments"),
        metric("coc_chi", "5", "cash_payment_deposits"),
        metric("bu_tru", "7", "noncash_offsets"),
        unknown,
    )
    by_meaning = {item.meaning: item.amount_vnd for item in value.metrics}
    assert by_meaning["cash_receipts"] == "100"
    assert by_meaning["cash_receipt_deposits"] == "20"
    assert by_meaning["noncash_offsets"] == "7"


@pytest.mark.parametrize(
    "metrics",
    [
        (metric("a", "1", "cash_receipts"), metric("b", "2", "cash_receipts")),
        (metric("a", "1", "cash_receipts"), metric("b", "2", "cash_receipt_deposits")),
        (metric("a", "1", "cash_payments"), metric("b", "2", "cash_payment_deposits")),
    ],
)
def test_money_rejects_ambiguous_totals_or_deposits_over_total(metrics):
    with pytest.raises(ValidationError):
        book(*metrics)


def test_known_money_metrics_require_valid_mapping_and_nonnegative_amounts():
    with pytest.raises(ValidationError):
        metric("a", "-1", "cash_receipts")
    with pytest.raises(ValidationError):
        book(metric("a", "1", "cash_receipts"), has_valid_money_mapping=False)
    huge = str(10**80) + ".01"
    with pytest.raises(ValidationError):
        book(
            metric("a", huge, "cash_receipts"),
            metric("b", str(10**80) + ".02", "cash_receipt_deposits"),
        )
