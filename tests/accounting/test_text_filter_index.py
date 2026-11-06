"""Text/date indexed ID sets preserve filtering and publication semantics."""

import io
import threading
import time
from uuid import uuid4

import pytest
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    runtime = Runtime(
        tmp_path / "text-filter", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("text-filter-admin", "synthetic-text-filter-password")
    actor = runtime.auth.authenticate(session["access_token"])
    runtime.start()
    try:
        yield runtime, actor, AccountingService(runtime)
    finally:
        runtime.close()


def book(account):
    _, actor, service = account
    return service.create_book(
        actor,
        "Text/date filter",
        [
            {"id": "code", "name": "Code", "kind": "text", "required": True},
            {"id": "note", "name": "Note", "kind": "text"},
            {"id": "day", "name": "Day", "kind": "date"},
            {"id": "amount", "name": "Amount", "kind": "money", "precision": 19},
        ],
        {},
        key(),
    )


def add(account, book_id, code, note, day="2026-02-01", amount="10.00", **extra):
    _, actor, service = account
    return service.create_row(
        actor, book_id, {"code": code, "note": note, "day": day, "amount": amount} | extra, key()
    )


@pytest.mark.parametrize("kind", ["text", "date"])
def test_text_date_comparisons_use_text_index_without_correlated_cells_lookup(account, kind):
    runtime, actor, service = account
    created = service.create_book(
        actor,
        "Comparison plans",
        [
            {"id": "code", "name": "Code", "kind": "text", "required": True},
            {"id": "selected", "name": "Selected", "kind": kind},
        ],
        {},
        key(),
    )
    values = ["A", "M", "Z"] if kind == "text" else ["2026-01-01", "2026-02-01", "2026-03-01"]
    for code, value in zip(["first", "middle", "last"], values, strict=True):
        service.create_row(actor, created["id"], {"code": code, "selected": value}, key())
    expected = {"eq": ["middle"], "gte": ["middle", "last"], "lte": ["first", "middle"]}
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
                actor,
                created["id"],
                filters=[{"column_id": "selected", "op": op, "value": values[1]}],
            )
        finally:
            event.remove(runtime.database.engine, "before_cursor_execute", capture)
        assert result["total"] == len(codes)
        assert [row["values"]["code"] for row in result["items"]] == codes
        assert len(observed) == 2
        with runtime.reader() as connection:
            for sql, parameters in observed:
                assert "accounting_cells.book_id =" in sql
                assert "accounting_cells.row_id = accounting_entries.id" not in sql
                plan = [
                    row[3]
                    for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, parameters)
                ]
                assert any("accounting_cells_text" in detail for detail in plan)
                assert not any(
                    "accounting_cells" in detail and "row_id=?" in detail for detail in plan
                )
                assert any("core_import_attempts" in detail for detail in plan)
                assert any("CORRELATED SCALAR SUBQUERY" in detail for detail in plan)


def test_contains_escapes_literal_percent_underscore_slash_and_unicode(account):
    _, actor, service = account
    created = book(account)
    notes = {
        "percent": "100% cà phê",
        "underscore": "mã_đợt",
        "plain": "100x cà phê",
        "unicode": "Đắk Lắk / a_b%",
        "slash": "a/b",
        "quote": "x' OR 1=1 --",
    }
    for code, note in notes.items():
        add(account, created["id"], code, note)
    for literal, expected in (
        ("%", {"percent", "unicode"}),
        ("_", {"underscore", "unicode"}),
        ("Đắk Lắk", {"unicode"}),
        ("a/b", {"slash"}),
        ("x' OR 1=1 --", {"quote"}),
    ):
        result = service.list_rows(
            actor,
            created["id"],
            filters=[{"column_id": "note", "op": "contains", "value": literal}],
        )
        assert result["total"] == len(expected)
        assert {row["values"]["code"] for row in result["items"]} == expected


@pytest.mark.parametrize("kind", ["text", "date"])
def test_empty_matches_present_null_and_missing_new_nullable_cells(account, kind):
    _, actor, service = account
    created = book(account)
    old = add(account, created["id"], "old-missing", "old")
    created = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_nullable", "name": "New nullable", "kind": kind}],
        {},
        key(),
    )
    null = add(account, created["id"], "explicit-null", "null", new_nullable=None)
    blank = add(account, created["id"], "explicit-blank", "blank", new_nullable="")
    value = "value" if kind == "text" else "2026-02-01"
    present = add(account, created["id"], "present", "present", new_nullable=value)
    unfiltered = service.list_rows(actor, created["id"])
    assert unfiltered["total"] == 4
    assert {row["id"] for row in unfiltered["items"]} == {
        old["id"],
        null["id"],
        blank["id"],
        present["id"],
    }
    empty = service.list_rows(
        actor, created["id"], filters=[{"column_id": "new_nullable", "op": "empty"}]
    )
    assert {row["id"] for row in empty["items"]} == {old["id"], null["id"], blank["id"]}
    assert empty["total"] == 3
    equal = service.list_rows(
        actor, created["id"], filters=[{"column_id": "new_nullable", "op": "eq", "value": value}]
    )
    assert [row["id"] for row in equal["items"]] == [present["id"]]
    # Preserve existing text/date equality: a blank argument is text "", while
    # the dedicated empty operator checks null/empty stored cells.
    assert (
        service.list_rows(
            actor, created["id"], filters=[{"column_id": "new_nullable", "op": "eq", "value": None}]
        )["total"]
        == 0
    )


def test_text_date_numeric_intersection_is_book_bound_with_whole_dataset_page_counts(account):
    _, actor, service = account
    created, other = book(account), book(account)
    first = add(account, created["id"], "code-a", "Đắk %_lô", "2026-02-01", "10.00")
    second = add(account, created["id"], "code-b", "Đắk %_lô", "2026-02-02", "20.00")
    add(account, created["id"], "code-c", "Đắk %_lô", "2026-03-01", "30.00")
    add(account, created["id"], "code-d", "Đắk xx lô", "2026-02-02", "40.00")
    add(account, created["id"], "code-e", "Đắk %_lô", "2026-02-02", None)
    deleted = add(account, created["id"], "code-f", "Đắk %_lô", "2026-02-02", "25.00")
    service.mutate_row(actor, deleted["id"], deleted["version"], key(), action="delete")
    add(account, other["id"], "code-other", "Đắk %_lô", "2026-02-02", "20.00")
    filters = [
        {"column_id": "note", "op": "contains", "value": "%_"},
        {"column_id": "day", "op": "gte", "value": "2026-02-01"},
        {"column_id": "day", "op": "lte", "value": "2026-02-28"},
        {"column_id": "amount", "op": "gte", "value": "10"},
    ]
    for page, expected in ((1, [first["id"]]), (2, [second["id"]]), (3, [])):
        result = service.list_rows(actor, created["id"], filters=filters, page=page, page_size=1)
        assert result["total"] == 2
        assert [row["id"] for row in result["items"]] == expected
    assert service.list_rows(actor, created["id"], filters=filters, deleted=True)["total"] == 3
    descending = service.list_rows(actor, created["id"], filters=filters, sort="amount:desc")
    assert [row["id"] for row in descending["items"]] == [second["id"], first["id"]]


def wait(account, batch_id):
    _, actor, service = account
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        imported = service.get_batch(actor, batch_id)
        state = imported["job"]["state"]
        if state == "COMPLETED" and imported["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "RECOVERABLE", "CANCELLED"}:
            assert state == "COMPLETED", imported.get("error_code")
            return imported
        time.sleep(0.01)
    pytest.fail("text filter publication deadline exceeded")


def test_text_id_set_preserves_pending_hidden_until_published(account, monkeypatch):
    runtime, actor, service = account
    created = book(account)
    foreground = add(account, created["id"], "match", "foreground")
    stored = runtime.files.put(
        io.BytesIO(b"code,note,day,amount\nmatch,source,2026-02-01,20.00\n"),
        category="workbooks",
        original_name="synthetic-text-filter.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    imported = service.create_batch(actor, created["id"], stored.id, {}, key())
    imported = wait(account, imported["id"])
    imported = service.mapping(
        actor,
        imported["id"],
        imported["version"],
        {"code": "A", "note": "B", "day": "C", "amount": "D"},
        {},
        key(),
    )
    service.validate(actor, imported["id"], imported["version"], key())
    imported = wait(account, imported["id"])
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "commit_pending":
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    filters = [{"column_id": "code", "op": "eq", "value": "match"}]
    try:
        service.confirm(
            actor,
            imported["id"],
            {
                "expected_version": imported["version"],
                "staging_revision": imported["revision"],
                "mapping_revision": imported["mapping_revision"],
                "decision_revision": imported["decision_revision"],
                "validation_token": imported["validation_token"],
                "mode": "valid_rows_only",
                "request_key": key(),
            },
        )
        assert entered.wait(10)
        pending = service.list_rows(actor, created["id"], filters=filters, page_size=1)
        assert pending["total"] == 1
        assert [row["id"] for row in pending["items"]] == [foreground["id"]]
        assert service.list_rows(actor, created["id"], filters=filters, deleted=True)["total"] == 1
    finally:
        release.set()
    wait(account, imported["id"])
    published = service.list_rows(actor, created["id"], filters=filters, page=2, page_size=1)
    assert published["total"] == 2
    assert [row["values"]["note"] for row in published["items"]] == ["source"]
