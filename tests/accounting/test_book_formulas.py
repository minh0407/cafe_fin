"""Persisted templates bind logical columns and only their current stable row."""

import pytest
from cafe_fin.accounting.validation import normalize_value
from cafe_fin.core.errors import CoreError
from test_import_regressions import account as account
from test_import_regressions import key


def test_formula_templates_recompute_on_crud_and_ignore_display_reorder(account):
    _, actor, service = account
    columns = [
        dict(id="amount", name="Tiền", kind="money"),
        dict(id="calculated", name="Tính", kind="formula", scale=2, formula="=ROUND(A{row}*1.1,2)"),
    ]
    book = service.create_book(actor, "Công thức", columns, {}, key())
    row = service.create_row(actor, book["id"], {"amount": "1005.00"}, key())
    assert row["values"]["calculated"] == "1105.50"
    row = service.mutate_row(actor, row["id"], row["version"], key(), {"amount": "1005.01"})
    assert row["values"]["calculated"] == "1105.51"
    book = service.update_schema(
        actor, book["id"], book["version"], list(reversed(book["columns"])), {}, key()
    )
    row2 = service.create_row(actor, book["id"], {"amount": "10.00"}, key())
    assert row2["logical_row"] == 2 and row2["values"]["calculated"] == "11.00"
    service.mutate_row(actor, row["id"], row["version"], key(), action="delete")
    row3 = service.create_row(actor, book["id"], {"amount": "20.00"}, key())
    assert row3["logical_row"] == 3 and row3["values"]["calculated"] == "22.00"


def test_cross_row_book_template_rejected_before_it_can_become_stale(account):
    _, actor, service = account
    with pytest.raises(CoreError, match="FORMULA_BOOK_SCOPE"):
        service.create_book(
            actor,
            "Scope",
            [
                dict(id="amount", name="Tiền", kind="money"),
                dict(id="formula", name="Tính", kind="formula", formula="=A1+1"),
            ],
            {},
            key(),
        )


def test_native_iso_datetime_uses_business_timezone_without_guessing_text():
    col = dict(id="day", name="Ngày", kind="date")
    assert (
        normalize_value("ignored", col, date_meta={"iso_date": "2026-02-01T18:30:00+00:00"})[0]
        == "2026-02-02"
    )
    assert (
        normalize_value("ignored", col, date_meta={"iso_date": "2026-02-01T00:00:00"})[0]
        == "2026-02-01"
    )
