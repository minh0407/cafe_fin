"""Numeric filter index selection with exact values and published-row semantics."""

import io
import threading
import time
from uuid import uuid4

import pytest
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    runtime = Runtime(
        tmp_path / "numeric-filter", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("filter-admin", "synthetic-filter-password")
    actor = runtime.auth.authenticate(session["access_token"])
    runtime.start()
    try:
        yield runtime, actor, AccountingService(runtime)
    finally:
        runtime.close()


def create_book(account):
    _, actor, service = account
    return service.create_book(
        actor,
        "Numeric filter",
        [
            {"id": "code", "name": "Code", "kind": "text", "required": True},
            {"id": "amount", "name": "Amount", "kind": "money", "precision": 19},
            {"id": "qty", "name": "Quantity", "kind": "decimal", "scale": 3},
            {"id": "day", "name": "Day", "kind": "date"},
        ],
        {},
        key(),
    )


def add(account, book_id, code, amount, qty="1.000", day="2026-02-01", **extra):
    _, actor, service = account
    return service.create_row(
        actor, book_id, {"code": code, "amount": amount, "qty": qty, "day": day} | extra, key()
    )


@pytest.mark.parametrize("kind", ["integer", "decimal", "money", "formula"])
def test_numeric_operators_use_book_bound_number_index_without_cell_correlation(account, kind):
    runtime, actor, service = account
    columns = [
        {"id": "code", "name": "Code", "kind": "text", "required": True},
        {"id": "source", "name": "Source", "kind": "integer"},
        {"id": "value", "name": "Value", "kind": kind, "scale": 3 if kind == "decimal" else 2},
    ]
    if kind == "formula":
        columns[-1]["formula"] = "=B{row}*2"
    book = service.create_book(actor, "Index plan", columns, {}, key())
    for code, value in (("negative", "-1"), ("zero", "0"), ("positive", "2")):
        values = {"code": code, "source": value}
        if kind != "formula":
            values["value"] = value
        service.create_row(actor, book["id"], values, key())
    expected = {"eq": ["zero"], "gte": ["zero", "positive"], "lte": ["negative", "zero"]}
    for op, codes in expected.items():
        observed = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            if (
                statement.lstrip().upper().startswith("SELECT")
                and "accounting_cells" in statement
                and "accounting_entries" in statement
            ):
                observed.append((statement, parameters))

        event.listen(runtime.database.engine, "before_cursor_execute", capture)
        try:
            result = service.list_rows(
                actor, book["id"], filters=[{"column_id": "value", "op": op, "value": "0"}]
            )
        finally:
            event.remove(runtime.database.engine, "before_cursor_execute", capture)
        assert result["total"] == len(codes)
        assert [row["values"]["code"] for row in result["items"]] == codes
        assert len(observed) == 2  # Whole-dataset count and the requested row page.
        with runtime.reader() as connection:
            for sql, parameters in observed:
                assert "accounting_cells.book_id =" in sql
                assert "accounting_cells.row_id = accounting_entries.id" not in sql
                plan = [
                    row[3]
                    for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, parameters)
                ]
                assert any("accounting_cells_number" in detail for detail in plan)
                assert not any(
                    "accounting_cells" in detail and "row_id=?" in detail for detail in plan
                )
                assert any("core_import_attempts" in detail for detail in plan)
                assert any("CORRELATED SCALAR SUBQUERY" in detail for detail in plan)


def test_numeric_intersection_stays_in_book_exact_and_counts_whole_pages_with_deletion(account):
    _, actor, service = account
    book, other = create_book(account), create_book(account)
    add(account, book["id"], "match-low", "10.00", "1.000")
    mid = add(account, book["id"], "match-mid", "20.00", "2.000", "2026-02-02")
    large = add(account, book["id"], "match-high", "90071992547409.93", "3.000", "2026-02-03")
    add(account, book["id"], "skip-text", "30.00", "1.000")
    add(account, book["id"], "match-null", None, "1.000")
    deleted = add(account, book["id"], "match-deleted", "25.00", "2.000", "2026-02-02")
    service.mutate_row(actor, deleted["id"], deleted["version"], key(), action="delete")
    add(account, other["id"], "match-other-book", "20.00", "2.000")
    filters = [
        {"column_id": "amount", "op": "gte", "value": "10"},
        {"column_id": "qty", "op": "lte", "value": "2.000"},
        {"column_id": "code", "op": "contains", "value": "match"},
    ]
    result = service.list_rows(actor, book["id"], page=2, page_size=1, filters=filters)
    assert result["total"] == 2
    assert [row["id"] for row in result["items"]] == [mid["id"]]
    assert result["page"] == 2 and result["page_size"] == 1
    assert service.list_rows(actor, book["id"], filters=filters, deleted=True)["total"] == 3
    dated = service.list_rows(
        actor,
        book["id"],
        filters=filters + [{"column_id": "day", "op": "gte", "value": "2026-02-02"}],
    )
    assert [row["id"] for row in dated["items"]] == [mid["id"]]
    exact = service.list_rows(
        actor,
        book["id"],
        filters=[{"column_id": "amount", "op": "eq", "value": "90071992547409.93"}],
    )
    assert [row["id"] for row in exact["items"]] == [large["id"]]
    assert exact["items"][0]["values"]["amount"] == "90071992547409.93"


def test_numeric_null_and_missing_new_nullable_cell_keep_existing_filter_semantics(account):
    _, actor, service = account
    book = create_book(account)
    old = add(account, book["id"], "old-missing-bonus", "1.00")
    book = service.update_schema(
        actor,
        book["id"],
        book["version"],
        book["columns"]
        + [{"id": "bonus", "name": "New nullable number", "kind": "decimal", "scale": 3}],
        {},
        key(),
    )
    null = add(account, book["id"], "explicit-null-bonus", "1.00", bonus=None)
    zero = add(account, book["id"], "zero-bonus", "1.00", bonus="0")
    positive = add(account, book["id"], "positive-bonus", "1.00", bonus="2")
    unfiltered = service.list_rows(actor, book["id"])
    assert unfiltered["total"] == 4
    assert {row["id"] for row in unfiltered["items"]} == {
        old["id"],
        null["id"],
        zero["id"],
        positive["id"],
    }
    result = service.list_rows(
        actor, book["id"], filters=[{"column_id": "bonus", "op": "gte", "value": "0"}]
    )
    assert {row["id"] for row in result["items"]} == {zero["id"], positive["id"]}
    nulls = service.list_rows(
        actor, book["id"], filters=[{"column_id": "bonus", "op": "eq", "value": None}]
    )
    assert [row["id"] for row in nulls["items"]] == [null["id"]]
    assert old["id"] not in {row["id"] for row in nulls["items"]}
    for op in ("gte", "lte"):
        with pytest.raises(CoreError) as error:
            service.list_rows(
                actor, book["id"], filters=[{"column_id": "bonus", "op": op, "value": None}]
            )
        assert error.value.code == "FILTER_INVALID"
    assert {
        row["id"]
        for row in service.list_rows(
            actor, book["id"], filters=[{"column_id": "bonus", "op": "empty"}]
        )["items"]
    } == {old["id"], null["id"]}
    assert [
        row["id"]
        for row in service.list_rows(
            actor, book["id"], filters=[{"column_id": "bonus", "op": "contains", "value": "2"}]
        )["items"]
    ] == [positive["id"]]


def wait(account, batch_id):
    _, actor, service = account
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch = service.get_batch(actor, batch_id)
        state = batch["job"]["state"]
        if state == "COMPLETED" and batch["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "RECOVERABLE", "CANCELLED"}:
            assert state == "COMPLETED", batch.get("error_code")
            return batch
        time.sleep(0.01)
    pytest.fail("numeric filter import deadline exceeded")


def test_numeric_id_set_cannot_reveal_pending_cells_before_atomic_publication(account, monkeypatch):
    runtime, actor, service = account
    book = create_book(account)
    foreground = add(account, book["id"], "foreground", "10.25")
    stored = runtime.files.put(
        io.BytesIO(b"code,amount,qty,day\npending,10.25,1.000,2026-02-01\n"),
        category="workbooks",
        original_name="synthetic-filter.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    batch = service.create_batch(actor, book["id"], stored.id, {}, key())
    batch = wait(account, batch["id"])
    batch = service.mapping(
        actor,
        batch["id"],
        batch["version"],
        {"code": "A", "amount": "B", "qty": "C", "day": "D"},
        {},
        key(),
    )
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait(account, batch["id"])
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "commit_pending":
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    filters = [{"column_id": "amount", "op": "eq", "value": "10.25"}]
    try:
        service.confirm(
            actor,
            batch["id"],
            {
                "expected_version": batch["version"],
                "staging_revision": batch["revision"],
                "mapping_revision": batch["mapping_revision"],
                "decision_revision": batch["decision_revision"],
                "validation_token": batch["validation_token"],
                "mode": "valid_rows_only",
                "request_key": key(),
            },
        )
        assert entered.wait(10)
        before = service.list_rows(actor, book["id"], filters=filters, page_size=1)
        assert before["total"] == 1
        assert [row["id"] for row in before["items"]] == [foreground["id"]]
        assert service.list_rows(actor, book["id"], filters=filters, deleted=True)["total"] == 1
    finally:
        release.set()
    wait(account, batch["id"])
    after = service.list_rows(actor, book["id"], filters=filters, page=2, page_size=1)
    assert after["total"] == 2
    assert [row["values"]["code"] for row in after["items"]] == ["pending"]
