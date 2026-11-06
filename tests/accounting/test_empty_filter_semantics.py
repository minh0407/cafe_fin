"""HTTP empty-filter regression: absent historical cells are logically blank.

Prepared while a frozen benchmark runs. Do not execute until the parent releases
the benchmark and applies the separate op-empty-only service patch.
"""

import io
import json
import threading
import time
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.api import create_app
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import func, select


def key():
    return str(uuid4())


@pytest.fixture
def api(tmp_path):
    runtime = Runtime(
        tmp_path / "empty-filter", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("empty-admin", "synthetic-empty-filter-password")
    actor = runtime.auth.authenticate(session["access_token"])
    headers = {
        "X-App-Session": "synthetic-empty-filter-app-session-012345",
        "Origin": "http://tauri.localhost",
        "Authorization": "Bearer " + session["access_token"],
    }
    app = create_app(runtime, headers["X-App-Session"], port=48957)
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:48957", raise_server_exceptions=False
        ) as client:
            yield runtime, actor, AccountingService(runtime), client, headers
    finally:
        runtime.close()


def rows(api, book_id, filters=None, *, expected=200, **params):
    query = dict(params)
    if filters is not None:
        query["filters"] = json.dumps(filters)
    response = api[3].get(f"/api/v1/accounting/books/{book_id}/rows", params=query, headers=api[4])
    assert response.status_code == expected, response.text
    return response.json()


def fixture_book(api, kind):
    _, actor, service, _, _ = api
    created = service.create_book(
        actor,
        "Empty filter",
        [{"id": "code", "name": "Code", "kind": "text", "required": True}],
        {},
        key(),
    )
    old = service.create_row(actor, created["id"], {"code": "OLD-BEFORE-ADD"}, key())
    created = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "optional", "name": "Optional", "kind": kind}],
        {},
        key(),
    )
    null = service.create_row(actor, created["id"], {"code": "NEW-NULL", "optional": None}, key())
    blank = service.create_row(actor, created["id"], {"code": "NEW-BLANK", "optional": ""}, key())
    value = {"text": "present", "date": "2026-02-01", "money": "1.25"}[kind]
    populated = service.create_row(
        actor, created["id"], {"code": "NEW-VALUE", "optional": value}, key()
    )
    zero = None
    if kind in ("text", "money"):
        zero = service.create_row(actor, created["id"], {"code": "ZERO", "optional": "0"}, key())
    deleted = service.create_row(
        actor, created["id"], {"code": "DELETED-NULL", "optional": None}, key()
    )
    service.mutate_row(actor, deleted["id"], deleted["version"], key(), action="delete")
    return created, old, null, blank, populated, zero, deleted


@pytest.mark.parametrize("kind", ["text", "date", "money"])
def test_http_empty_includes_historical_missing_null_and_blank_without_backfill(api, kind):
    runtime, actor, service, _, _ = api
    created, old, null, blank, populated, zero, deleted = fixture_book(api, kind)
    other = service.create_book(actor, "Other book", created["columns"], {}, key())
    other_null = service.create_row(
        actor, other["id"], {"code": "OTHER-NULL", "optional": None}, key()
    )
    unfiltered = rows(api, created["id"])
    expected_ids = {old["id"], null["id"], blank["id"], populated["id"]}
    if zero:
        expected_ids.add(zero["id"])
    assert {row["id"] for row in unfiltered["items"]} == expected_ids
    assert (
        next(row for row in unfiltered["items"] if row["id"] == old["id"])["values"].get("optional")
        is None
    )
    empty = [{"column_id": "optional", "op": "empty"}]
    actual = rows(api, created["id"], empty)
    assert actual["total"] == 3
    assert {row["id"] for row in actual["items"]} == {old["id"], null["id"], blank["id"]}
    assert other_null["id"] not in {row["id"] for row in actual["items"]}
    for page, row_id in enumerate((old["id"], null["id"], blank["id"]), 1):
        result = rows(api, created["id"], empty, page=page, page_size=1)
        assert result["total"] == 3
        assert [row["id"] for row in result["items"]] == [row_id]
    assert rows(api, created["id"], empty, page=4, page_size=1)["items"] == []
    including_deleted = rows(api, created["id"], empty, deleted=True)
    assert including_deleted["total"] == 4
    assert {row["id"] for row in including_deleted["items"]} == {
        old["id"],
        null["id"],
        blank["id"],
        deleted["id"],
    }
    intersection = rows(
        api, created["id"], empty + [{"column_id": "code", "op": "contains", "value": "NEW-"}]
    )
    assert {row["id"] for row in intersection["items"]} == {null["id"], blank["id"]}
    # Equality to null is a separate existing contract; only op=empty changes.
    eq_null = rows(api, created["id"], [{"column_id": "optional", "op": "eq", "value": None}])
    assert {row["id"] for row in eq_null["items"]} == (
        {null["id"], blank["id"]} if kind == "money" else set()
    )
    unsupported = rows(
        api, created["id"], [{"column_id": "optional", "op": "not_empty"}], expected=400
    )
    assert unsupported["error"]["code"] == "FILTER_INVALID"
    with runtime.reader() as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(s.cells)
                .where(s.cells.c.row_id == old["id"], s.cells.c.column_id == "optional")
            ).scalar_one()
            == 0
        )
        original = connection.execute(
            select(s.entries.c.values_json, s.entries.c.version).where(s.entries.c.id == old["id"])
        ).one()
    assert json.loads(original.values_json) == {"code": "OLD-BEFORE-ADD"}
    assert original.version == old["version"]


def wait(api, batch_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        imported = api[2].get_batch(api[1], batch_id)
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
    pytest.fail("empty filter pending/publication deadline exceeded")


@pytest.mark.parametrize("kind", ["text", "date", "money"])
def test_http_empty_never_reveals_pending_rows_and_includes_them_after_publication(
    api, monkeypatch, kind
):
    runtime, actor, service, _, _ = api
    created, old, null, blank, _, _, _ = fixture_book(api, kind)
    stored = runtime.files.put(
        io.BytesIO(b"code,optional\nPENDING-NULL,\n"),
        category="workbooks",
        original_name="synthetic-empty.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    imported = service.create_batch(actor, created["id"], stored.id, {}, key())
    imported = wait(api, imported["id"])
    imported = service.mapping(
        actor, imported["id"], imported["version"], {"code": "A", "optional": "B"}, {}, key()
    )
    service.validate(actor, imported["id"], imported["version"], key())
    imported = wait(api, imported["id"])
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "commit_pending":
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    empty = [{"column_id": "optional", "op": "empty"}]
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
        pending = rows(api, created["id"], empty)
        assert pending["total"] == 3
        assert {row["id"] for row in pending["items"]} == {old["id"], null["id"], blank["id"]}
        assert rows(api, created["id"], empty, deleted=True)["total"] == 4
    finally:
        release.set()
    wait(api, imported["id"])
    published = rows(api, created["id"], empty, page=4, page_size=1)
    assert published["total"] == 4
    assert [row["values"]["code"] for row in published["items"]] == ["PENDING-NULL"]
