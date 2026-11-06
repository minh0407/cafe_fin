from datetime import date, datetime, timezone

import pytest
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.core.errors import CoreError

from tests.accounting.test_import_regressions import account as account
from tests.accounting.test_import_regressions import key


def create(service, actor, meanings=None):
    return service.create_book(
        actor,
        "Ý nghĩa",
        [
            dict(id="day", name="Ngày", kind="date"),
            dict(id="amount", name="Tiền", kind="money"),
            dict(id="currency", name="Tiền tệ", kind="text"),
            dict(id="group", name="Nhóm", kind="text"),
        ],
        dict(
            date_column="day",
            income_column="amount",
            currency_column="currency",
            group_columns=["group"],
        )
        | ({"metric_meanings": meanings} if meanings is not None else {}),
        key(),
    )


def capture(runtime, actor, book):
    return AccountingReadProvider(runtime, actor).book_summary(
        book["id"], date(2026, 2, 1), date(2026, 2, 2), cutoff=datetime.now(timezone.utc)
    )


def test_unknown_meaning_kept_unknown_and_absent_expense_not_invented(account):
    runtime, actor, service = account
    book = create(service, actor)
    service.create_row(
        actor,
        book["id"],
        {"day": "2026-02-01", "amount": "10.25", "currency": "VND", "group": "A"},
        key(),
    )
    result = capture(runtime, actor, book)
    assert len(result.metrics) == 1 and result.metrics[0].meaning is None
    assert result.metrics[0].amount_vnd == "10.25"
    assert "METRIC_MEANING_UNKNOWN:income" in result.validation_flags


def test_known_meaning_only_after_explicit_mapping_and_groups_stay_separate(account):
    runtime, actor, service = account
    book = create(service, actor, {"income": "cash_receipts"})
    for currency, amount, group in [
        ("VND", "1.25", "A"),
        ("USD", "900.00", "A"),
        ("VND", "2.75", "B"),
    ]:
        service.create_row(
            actor,
            book["id"],
            {"day": "2026-02-01", "amount": amount, "currency": currency, "group": group},
            key(),
        )
    result = capture(runtime, actor, book)
    assert result.metrics[0].meaning == "cash_receipts" and result.metrics[0].amount_vnd == "4.00"
    assert "NON_VND_CURRENCIES_OMITTED" in result.validation_flags
    summary = service.summary(actor, book["id"], "2026-02-01", "2026-02-02")
    assert len(summary["groups"]) == 3 and summary["totals"]["USD"]["income"] == "900.00"


def test_signed_refund_not_mislabeled_nonnegative_cash(account):
    runtime, actor, service = account
    book = create(service, actor, {"income": "cash_receipts"})
    service.create_row(
        actor, book["id"], {"day": "2026-02-01", "amount": "-1.25", "currency": "VND"}, key()
    )
    result = capture(runtime, actor, book)
    assert result.metrics[0].amount_vnd == "-1.25" and result.metrics[0].meaning is None
    assert "NEGATIVE_METRIC_REQUIRES_CLASSIFICATION:income" in result.validation_flags


def test_duplicate_known_meanings_rejected_until_one_derived_total_configured(account):
    _, actor, service = account
    with pytest.raises(CoreError, match="METRIC_MEANING_DUPLICATE"):
        create(service, actor, {"income": "cash_receipts", "expense": "cash_receipts"})


def test_public_total_not_blocked_by_interactive_group_count_limit(account):
    runtime, actor, service = account
    book = create(service, actor, {"income": "cash_receipts"})
    for index in range(1001):
        service.create_row(
            actor,
            book["id"],
            {"day": "2026-02-01", "amount": "0.01", "currency": "VND", "group": str(index)},
            key(),
        )
    with pytest.raises(CoreError, match="REPORT_GROUP_LIMIT"):
        service.summary(actor, book["id"], "2026-02-01", "2026-02-01")
    result = capture(runtime, actor, book)
    assert result.metrics[0].amount_vnd == "10.01" and result.metrics[0].meaning == "cash_receipts"
