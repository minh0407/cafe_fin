"""Optional literal book labels share the authoritative summary snapshot."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event, select, update


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    runtime = Runtime(
        tmp_path / "bridge-v3-names", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("names-admin", "synthetic-names-password")
    actor = runtime.auth.authenticate(session["access_token"])
    try:
        yield runtime, actor, AccountingService(runtime)
    finally:
        runtime.close()


def create_book(account, *, mapped=True):
    _, actor, service = account
    created = service.create_book(
        actor,
        "Initial label",
        [
            {"id": "day", "name": "Day", "kind": "date"},
            {"id": "amount", "name": "Amount", "kind": "money"},
            {"id": "note", "name": "Note", "kind": "text"},
        ],
        {
            "date_column": "day",
            "income_column": "amount",
            "metric_meanings": {"income": "cash_receipts"},
        }
        if mapped
        else {},
        key(),
    )
    service.create_row(
        actor,
        created["id"],
        {
            "day": "2026-02-01",
            "amount": "10.25",
            "note": "Never infer the book name from this note",
        },
        key(),
    )
    return created


def seed_name(account, book_id, name):
    runtime, actor, _ = account

    def rename(connection):
        runtime.auth.authorize(connection, actor, "accounting.configure")
        connection.execute(update(s.books).where(s.books.c.id == book_id).values(name=name))

    runtime.writer.run(rename)


def summary(provider, book_id):
    return provider.book_summary(
        book_id, date(2026, 2, 1), date(2026, 2, 1), cutoff=datetime.now(timezone.utc)
    )


def test_literal_unicode_markup_spaces_and_boundary_names_preserve_identity(account):
    runtime, actor, service = account
    names = [
        "X",
        'Sổ cà phê Đắk Lắk <b>Thu & chi</b> "nguyên văn"',
        "  Sổ giữ nguyên khoảng trắng  ",
        "Đ" * 256,
    ]
    provider = AccountingReadProvider(runtime, actor)
    identities = []
    for name in names:
        created = create_book(account)
        seed_name(account, created["id"], name)
        source = service.summary(actor, created["id"], "2026-02-01", "2026-02-01")
        result = summary(provider, created["id"])
        assert source["book_name"] == name
        assert result.book_name == name
        assert result.book_id == created["id"]
        assert result.model_dump(mode="json")["book_name"] == name
        assert {metric.key: metric.amount_vnd for metric in result.metrics}["income"] == "10.25"
        with runtime.reader() as connection:
            assert (
                connection.execute(
                    select(s.books.c.name).where(s.books.c.id == created["id"])
                ).scalar_one()
                == name
            )
        identities.append(result.book_id)
    assert len(set(identities)) == len(names)


def test_unmapped_summary_still_carries_literal_book_name(account):
    runtime, actor, service = account
    created = create_book(account, mapped=False)
    name = "Sổ chưa ánh xạ <literal>"
    seed_name(account, created["id"], name)
    source = service.summary(actor, created["id"], "2026-02-01", "2026-02-01")
    result = summary(AccountingReadProvider(runtime, actor), created["id"])
    assert source["book_name"] == name
    assert source["has_valid_money_mapping"] is False
    assert result.book_name == name
    assert result.has_valid_money_mapping is False
    assert result.metrics == ()
    assert "MONEY_MAPPING_REQUIRED" in result.validation_flags


def test_invalid_legacy_stored_names_return_none_without_saved_rewrite(account):
    runtime, actor, service = account
    created = create_book(account)
    provider = AccountingReadProvider(runtime, actor)
    for invalid in ("", " \t\n", "Đ" * 257, b"legacy blob label"):
        seed_name(account, created["id"], invalid)
        assert (
            service.summary(actor, created["id"], "2026-02-01", "2026-02-01")["book_name"] is None
        )
        result = summary(provider, created["id"])
        assert result.book_name is None
        assert {metric.key: metric.amount_vnd for metric in result.metrics}["income"] == "10.25"
        with runtime.reader() as connection:
            assert (
                connection.execute(
                    select(s.books.c.name).where(s.books.c.id == created["id"])
                ).scalar_one()
                == invalid
            )


def test_legacy_summary_missing_or_invalid_optional_label_is_not_inferred_or_coerced(
    account, monkeypatch
):
    runtime, actor, service = account
    created = create_book(account)
    original = AccountingService.summary
    missing = object()
    selected = [missing]

    def legacy_result(worker, *args, **kwargs):
        result = original(worker, *args, **kwargs)
        if selected[0] is missing:
            result.pop("book_name")
        else:
            result["book_name"] = selected[0]
        return result

    monkeypatch.setattr(AccountingService, "summary", legacy_result)
    for legacy in (missing, None, 123, True, {"name": "not a string"}, ["not a string"]):
        selected[0] = legacy
        result = summary(AccountingReadProvider(runtime, actor), created["id"])
        assert result.book_name is None
        assert result.book_id == created["id"]
    with runtime.reader() as connection:
        assert (
            connection.execute(
                select(s.books.c.name).where(s.books.c.id == created["id"])
            ).scalar_one()
            == "Initial label"
        )


def test_caller_snapshot_keeps_old_name_and_totals_without_extra_reader_or_transaction_changes(
    account, monkeypatch
):
    runtime, actor, service = account
    created = create_book(account)
    old_name, new_name = "Sổ cũ <Đắk Lắk>", "  Sổ mới <b>Giữ nguyên</b>  "
    seed_name(account, created["id"], old_name)
    cutoff = datetime.now(timezone.utc)
    with runtime.reader() as connection:
        connection.exec_driver_sql("BEGIN")
        assert (
            connection.execute(
                select(s.books.c.name).where(s.books.c.id == created["id"])
            ).scalar_one()
            == old_name
        )
        transaction = connection.get_transaction()
        # Foreground writes use the serialized writer while the caller retains
        # a WAL read snapshot. No new public rename workflow is introduced.
        seed_name(account, created["id"], new_name)
        service.create_row(
            actor,
            created["id"],
            {"day": "2026-02-01", "amount": "20.75", "note": "Foreground note is not a label"},
            key(),
        )
        book_reads = []

        def observe_book_read(conn, cursor, statement, parameters, context, executemany):
            if (
                statement.lstrip().upper().startswith("SELECT")
                and "FROM accounting_books" in statement
            ):
                book_reads.append(statement)

        def forbidden(*args, **kwargs):
            pytest.fail("bound label read opened another reader or changed caller transaction")

        event.listen(connection, "before_cursor_execute", observe_book_read)
        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(runtime, "reader", forbidden)
                for method in ("close", "commit", "rollback"):
                    scoped.setattr(connection, method, forbidden)
                result = AccountingReadProvider(runtime, actor, connection=connection).book_summary(
                    created["id"], date(2026, 2, 1), date(2026, 2, 1), cutoff=cutoff
                )
        finally:
            event.remove(connection, "before_cursor_execute", observe_book_read)
        assert result.book_name == old_name
        assert {metric.key: metric.amount_vnd for metric in result.metrics}["income"] == "10.25"
        assert len(book_reads) == 1
        assert connection.get_transaction() is transaction
        assert connection.in_transaction() and not connection.closed
        assert (
            connection.execute(
                select(s.books.c.name).where(s.books.c.id == created["id"])
            ).scalar_one()
            == old_name
        )
    fresh = summary(AccountingReadProvider(runtime, actor), created["id"])
    assert fresh.book_name == new_name
    assert {metric.key: metric.amount_vnd for metric in fresh.metrics}["income"] == "31.00"
