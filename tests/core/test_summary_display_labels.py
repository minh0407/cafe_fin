from datetime import date, datetime, timezone

import pytest
from cafe_fin.core.contracts import (
    CONTRACT_VERSION,
    BookSummaryDTO,
    InventoryLineDTO,
    InventoryMovementSummaryDTO,
    InventorySummaryDTO,
    MappedBookMetricDTO,
)
from pydantic import ValidationError

PERIOD = {
    "from_on": date(2026, 11, 7),
    "through_on": date(2026, 11, 7),
    "cutoff": datetime(2026, 11, 7, 12, tzinfo=timezone.utc),
}


def stock_line(**changes):
    values = {
        "product_id": "product-1",
        "warehouse_id": "warehouse-1",
        "opening_kg": "0",
        "received_kg": "10.001",
        "issued_kg": "2",
        "closing_kg": "8.001",
    }
    values.update(changes)
    return InventoryLineDTO(**values)


def movement(**changes):
    values = {
        "product_id": "product-1",
        "warehouse_id": "warehouse-1",
        "purchased_kg": "10.001",
        "sold_kg": "2",
        "production_input_kg": "0",
        "production_output_kg": "0",
        "transfer_in_kg": "0",
        "transfer_out_kg": "0",
        "adjustment_in_kg": "0",
        "adjustment_out_kg": "0",
    }
    values.update(changes)
    return InventoryMovementSummaryDTO(**values)


def book(**changes):
    values = {**PERIOD, "book_id": "book-1", "has_valid_money_mapping": True}
    values.update(changes)
    return BookSummaryDTO(**values)


LABEL_FIELDS = (
    (stock_line, "product_name"),
    (stock_line, "warehouse_name"),
    (movement, "product_name"),
    (movement, "warehouse_name"),
    (book, "book_name"),
)


def test_bridge_revision_three_reads_old_inputs_without_mutating_them():
    assert CONTRACT_VERSION == 3
    old_line = {
        "product_id": "product-old",
        "warehouse_id": "warehouse-old",
        "opening_kg": "0",
        "received_kg": "1",
        "issued_kg": "0",
        "closing_kg": "1",
    }
    original = old_line.copy()
    legacy = InventorySummaryDTO(**PERIOD, items=(InventoryLineDTO(**old_line),))
    assert legacy.items[0].product_name is None
    assert legacy.items[0].warehouse_name is None
    assert legacy.breakdown_version is legacy.movement_breakdown is None
    assert old_line == original
    assert book().book_name is None
    assert movement().product_name is None
    assert movement().warehouse_name is None


@pytest.mark.parametrize("factory,field", LABEL_FIELDS)
def test_display_labels_accept_none_unicode_and_exact_character_limit(factory, field):
    assert getattr(factory(**{field: None}), field) is None
    for value in ("Cà phê Đắk Lắk / Kho số 2 / Sổ thu chi 📒", "ắ" * 256):
        assert getattr(factory(**{field: value}), field) == value


@pytest.mark.parametrize("factory,field", LABEL_FIELDS)
@pytest.mark.parametrize("value", ["", " \t\n", "ắ" * 257, 5, True, 1.5, b"name", {}, []])
def test_display_labels_reject_empty_oversized_or_non_string_values(factory, field, value):
    with pytest.raises(ValidationError):
        factory(**{field: value})


@pytest.mark.parametrize("factory,field", LABEL_FIELDS)
def test_display_labels_round_trip_as_frozen_plain_text(factory, field):
    # The DTO carries literal display data, not HTML instructions or executable markup.
    text = '<b>Cà phê & kho</b> <img src=x onerror="alert(1)">'
    value = factory(**{field: text})
    restored = type(value).model_validate_json(value.model_dump_json())
    assert restored == value
    assert getattr(restored, field) == text
    with pytest.raises(ValidationError, match="frozen"):
        setattr(restored, field, "Tên khác")


def test_label_validation_does_not_evaluate_or_coerce_objects():
    class NotDisplayText:
        def __str__(self):
            raise AssertionError("A display label must not evaluate/coerce an object")

    with pytest.raises(ValidationError):
        book(book_name=NotDisplayText())


def test_reconciliation_uses_ids_and_exact_amounts_even_when_display_names_differ():
    huge = f"{10**80 + 1}.001"
    value = InventorySummaryDTO(
        **PERIOD,
        breakdown_version=1,
        items=(stock_line(
            product_name="Cà phê", warehouse_name="Kho chính",
            received_kg=huge, issued_kg="0", closing_kg=huge,
        ),),
        movement_breakdown=(movement(
            product_name="Tên hiển thị khác", warehouse_name=None,
            purchased_kg=huge, sold_kg="0",
        ),),
    )
    assert value.items[0].received_kg == huge
    assert InventorySummaryDTO.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("case", ["wrong_id", "duplicate_scope", "wrong_amount"])
def test_matching_labels_cannot_hide_wrong_scope_or_amount(case):
    names = {"product_name": "Cà phê", "warehouse_name": "Kho chính"}
    detail = (movement(**names),)
    if case == "wrong_id":
        detail = (movement(**names, product_id="another-product"),)
    elif case == "duplicate_scope":
        detail += (movement(product_name="Tên khác", warehouse_name="Kho khác"),)
    else:
        detail = (movement(**names, purchased_kg="10.002"),)
    with pytest.raises(ValidationError):
        InventorySummaryDTO(
            **PERIOD, items=(stock_line(**names),), breakdown_version=1,
            movement_breakdown=detail,
        )


def test_book_name_does_not_supply_mapping_or_change_money_semantics():
    receipt = MappedBookMetricDTO(
        key="thu", amount_vnd="1.00", mapping_revision=1, meaning="cash_receipts"
    )
    assert book(book_name="Sổ tiền mặt", metrics=(receipt,)).metrics == (receipt,)
    with pytest.raises(ValidationError):
        book(book_name="Sổ tiền mặt", has_valid_money_mapping=False, metrics=(receipt,))
    deposit = MappedBookMetricDTO(
        key="coc", amount_vnd="2.00", mapping_revision=1, meaning="cash_receipt_deposits"
    )
    with pytest.raises(ValidationError):
        book(book_name="Sổ tiền mặt", metrics=(receipt, deposit))
