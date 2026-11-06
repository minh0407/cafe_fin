"""Exact import comparisons, issue-file jobs and constant-size default decisions."""

import csv
import io
import threading
import time
from urllib.parse import quote
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.jobs import AccountingJobs
from cafe_fin.accounting.module import module_manifest
from cafe_fin.core.api import create_app
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import event, select

PREFIX = "/api/v1/accounting"
RANGE = {"from_on": "2026-02-01", "through_on": "2026-02-02"}
ISSUE_COLUMNS = [
    "source_sheet",
    "source_row",
    "source_column",
    "column_id",
    "cell",
    "code",
    "message",
    "severity",
    "raw_value",
    "suggestion",
    "validation_revision",
]


def key():
    return str(uuid4())


@pytest.fixture
def api(tmp_path):
    runtime = Runtime(
        tmp_path / "preview-exports", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("preview-admin", "synthetic-preview-password")
    headers = {
        "X-App-Session": "synthetic-preview-app-session-0123456789",
        "Origin": "http://tauri.localhost",
        "Authorization": "Bearer " + session["access_token"],
    }
    app = create_app(runtime, headers["X-App-Session"], port=48956)
    try:
        with TestClient(
            app, base_url="http://127.0.0.1:48956", raise_server_exceptions=False
        ) as client:
            yield runtime, client, headers
    finally:
        runtime.close()


def call(api, method, path, *, expected=200, **kwargs):
    response = api[1].request(method, PREFIX + path, headers=api[2], **kwargs)
    assert response.status_code == expected, response.text
    return response.json()


def book(api):
    return call(
        api,
        "POST",
        "/books",
        json={
            "name": "Preview test",
            "columns": [
                {"id": "code", "name": "Code", "kind": "text", "required": True},
                {"id": "day", "name": "Day", "kind": "date", "required": True},
                {
                    "id": "amount",
                    "name": "Income",
                    "kind": "money",
                    "precision": 19,
                    "required": True,
                },
                {"id": "currency", "name": "Currency", "kind": "text", "required": True},
            ],
            "semantics": {
                "date_column": "day",
                "income_column": "amount",
                "currency_column": "currency",
            },
            "request_key": key(),
        },
    )


def wait_batch(api, batch_id, expected="COMPLETED"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch = call(api, "GET", f"/import-jobs/{batch_id}")
        state = batch["job"]["state"]
        if state == "COMPLETED" and batch["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"}:
            assert state == expected, batch.get("error_code")
            return batch
        time.sleep(0.01)
    pytest.fail("preview fixture job timed out")


def batch(api, book_id, rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Code", "Day", "Income", "Currency"])
    writer.writerows(rows)
    uploaded = api[1].post(
        "/api/v1/files",
        content=output.getvalue().encode(),
        headers=api[2]
        | {
            "X-File-Name": quote("synthetic-preview.csv"),
            "X-Request-Key": key(),
            "Content-Type": "application/octet-stream",
        },
    )
    assert uploaded.status_code == 200
    imported = call(
        api,
        "POST",
        "/import-jobs",
        json={"book_id": book_id, "file_id": uploaded.json()["id"], "request_key": key()},
    )
    imported = wait_batch(api, imported["id"])
    imported = call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/mapping",
        json={
            "expected_version": imported["version"],
            "mapping": {"code": "A", "day": "B", "amount": "C", "currency": "D"},
            "request_key": key(),
        },
    )
    call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/validate",
        json={"expected_version": imported["version"], "request_key": key()},
    )
    return wait_batch(api, imported["id"])


def patch(api, imported, row, values):
    return call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/patches",
        json={
            "expected_version": imported["version"],
            "patches": [
                {"row_id": row["row_id"], "expected_version": row["revision"], "values": values}
            ],
            "request_key": key(),
        },
    )


def confirm(api, imported):
    return call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/confirm",
        json={
            "expected_version": imported["version"],
            "staging_revision": imported["revision"],
            "mapping_revision": imported["mapping_revision"],
            "decision_revision": imported["decision_revision"],
            "validation_token": imported["validation_token"],
            "mode": "valid_rows_only",
            "request_key": key(),
        },
    )


def wait_export(api, job_id, expected="COMPLETED"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = call(api, "GET", f"/exports/{job_id}")
        if status["state"] in {"FAILED", "CANCELLED", "RECOVERABLE"} or (
            status["state"] == "COMPLETED" and status["file_id"]
        ):
            assert status["state"] == expected, status.get("error_code")
            return status
        time.sleep(0.01)
    pytest.fail("issue export job timed out")


def assert_no_float(value):
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for child in value.values():
            assert_no_float(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_float(child)


def test_preview_exact_separate_currencies_and_revision_guards(api):
    created = book(api)
    for code, amount, currency in (
        ("before-vnd", "90071992547409.93", "VND"),
        ("before-usd", "2.25", "USD"),
    ):
        call(
            api,
            "POST",
            f"/books/{created['id']}/rows",
            json={
                "values": {
                    "code": code,
                    "day": "2026-02-01",
                    "amount": amount,
                    "currency": currency,
                },
                "request_key": key(),
            },
        )
    imported = batch(
        api,
        created["id"],
        [
            ("new-vnd", "2026-02-01", "0.07", "VND"),
            ("new-usd", "2026-02-01", "0.75", "USD"),
            ("bad", "2026-02-01", "invalid", "VND"),
            ("outside", "2026-02-02", "2.00", "VND"),
        ],
    )
    result = call(api, "GET", f"/import-jobs/{imported['id']}/summary", params=RANGE)
    assert result["before"]["totals"]["VND"]["income"] == "90071992547409.93"
    assert result["new_batch"] == {
        "VND": {"income": "0.07", "expense": "0.00", "row_count": 1},
        "USD": {"income": "0.75", "expense": "0.00", "row_count": 1},
    }
    assert result["after"]["VND"]["income"] == "90071992547410.00"
    assert result["after"]["USD"]["income"] == "3.00"
    assert result["staging_revision"] == imported["revision"]
    assert result["validation_token"] == imported["validation_token"]
    assert result["provisional"] is True
    assert_no_float(result)
    bad = call(api, "GET", f"/import-jobs/{imported['id']}/staging", params={"status": "invalid"})[
        "items"
    ][0]
    imported = patch(api, imported, bad, {"amount": "0.01"})
    error = call(api, "GET", f"/import-jobs/{imported['id']}/summary", expected=409, params=RANGE)
    assert error["error"]["code"] == "VALIDATION_REQUIRED"
    call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/validate",
        json={"expected_version": imported["version"], "request_key": key()},
    )
    imported = wait_batch(api, imported["id"])
    columns = [dict(column, name=column["name"] + " renamed") for column in created["columns"]]
    call(
        api,
        "PATCH",
        f"/books/{created['id']}/schema",
        json={
            "expected_version": created["version"],
            "columns": columns,
            "semantics": created["semantics"],
            "request_key": key(),
        },
    )
    error = call(api, "GET", f"/import-jobs/{imported['id']}/summary", expected=409, params=RANGE)
    assert error["error"]["code"] == "SCHEMA_STALE"


def test_pending_preview_is_guarded_and_published_rows_leave_new_projection(api, monkeypatch):
    created = book(api)
    imported = batch(api, created["id"], [("new", "2026-02-01", "1.01", "VND")])
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "commit_pending":
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    try:
        confirm(api, imported)
        assert entered.wait(10)
        error = call(
            api, "GET", f"/import-jobs/{imported['id']}/summary", expected=409, params=RANGE
        )
        assert error["error"]["code"] == "IMPORT_BUSY"
        assert call(api, "GET", f"/books/{created['id']}/summary", params=RANGE)["totals"] == {}
    finally:
        release.set()
    wait_batch(api, imported["id"])
    result = call(api, "GET", f"/import-jobs/{imported['id']}/summary", params=RANGE)
    assert result["new_batch"] == {}
    assert result["before"]["totals"] == result["after"]
    assert result["after"]["VND"]["income"] == "1.01"


def test_global_duplicate_default_is_constant_size_and_preserves_explicit_choices(api):
    created = book(api)
    imported = batch(api, created["id"], [("same", "2026-02-01", "1.01", "VND")] * 4)
    rows = call(api, "GET", f"/import-jobs/{imported['id']}/staging")["items"]
    imported = call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/decisions",
        json={
            "expected_version": imported["version"],
            "decisions": [
                {"row_id": rows[0]["row_id"], "decision": "skip"},
                {"row_id": rows[1]["row_id"], "decision": "keep"},
            ],
            "request_key": key(),
        },
    )
    for default, eligible_count, excluded_count in (("keep", 3, 1), ("skip", 1, 3)):
        updates = []

        def record_updates(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("UPDATE"):
                updates.append(statement.lower())

        event.listen(api[0].database.engine, "before_cursor_execute", record_updates)
        try:
            imported = call(
                api,
                "POST",
                f"/import-jobs/{imported['id']}/decisions",
                json={
                    "expected_version": imported["version"],
                    "decisions": [],
                    "all_pending_duplicates": default,
                    "request_key": key(),
                },
            )
        finally:
            event.remove(api[0].database.engine, "before_cursor_execute", record_updates)
        assert not any("update accounting_staged_rows" in statement for statement in updates)
        assert any("update accounting_batches" in statement for statement in updates)
        assert imported["counts"]["eligible"] == eligible_count
        assert imported["counts"]["excluded"] == excluded_count
        effective = call(api, "GET", f"/import-jobs/{imported['id']}/staging")["items"]
        assert [row["decision"] for row in effective] == ["skip", "keep", default, default]
        with api[0].reader() as connection:
            stored = (
                connection.execute(select(s.stage.c.decision).order_by(s.stage.c.source_row))
                .scalars()
                .all()
            )
        assert stored == ["skip", "keep", None, None]


@pytest.mark.parametrize("format_name", ["csv", "xlsx"])
def test_issue_export_contains_every_unresolved_cell_and_escapes_injection(api, format_name):
    created = book(api)
    imported = batch(
        api,
        created["id"],
        [(f"{index:07d}", "2026-02-01", "=SUM(1,2)", "VND") for index in range(603)],
    )
    bad = call(api, "GET", f"/import-jobs/{imported['id']}/staging", params={"status": "invalid"})[
        "items"
    ][0]
    imported = patch(api, imported, bad, {"amount": "1.25"})
    call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/validate",
        json={"expected_version": imported["version"], "request_key": key()},
    )
    imported = wait_batch(api, imported["id"])
    assert call(api, "GET", f"/import-jobs/{imported['id']}/issues")["total"] == 602
    export = call(
        api,
        "POST",
        f"/import-jobs/{imported['id']}/exports",
        json={"format": format_name, "request_key": key()},
    )
    status = wait_export(api, export["job_id"])
    response = api[1].get(f"/api/v1/files/{status['file_id']}/content", headers=api[2])
    assert response.status_code == 200
    if format_name == "csv":
        decoded_csv = io.StringIO(response.content.decode("utf-8-sig"))
        rows = list(csv.reader(decoded_csv))
        assert rows[0] == ISSUE_COLUMNS
        exported = [dict(zip(rows[0], row, strict=True)) for row in rows[1:]]
        assert {row["raw_value"] for row in exported} == {"'=SUM(1,2)"}
    else:
        workbook = load_workbook(io.BytesIO(response.content), read_only=True, data_only=False)
        try:
            cells = list(workbook.worksheets[0].iter_rows())
            assert [cell.value for cell in cells[0]] == ISSUE_COLUMNS
            assert all(cell.data_type != "f" for row in cells[1:] for cell in row)
            exported = [
                dict(zip(ISSUE_COLUMNS, [cell.value for cell in row], strict=True))
                for row in cells[1:]
            ]
            assert {row["raw_value"] for row in exported} == {"=SUM(1,2)"}
        finally:
            workbook.close()
    assert len(exported) == 602
    assert len({row["cell"] for row in exported}) == 602
    assert {row["source_column"] for row in exported} == {"C"}
    assert {row["column_id"] for row in exported} == {"amount"}
    assert {str(row["validation_revision"]) for row in exported} == {str(imported["revision"])}
    assert f"C{bad['source_row']}" not in {row["cell"] for row in exported}


def test_issue_export_rejects_a_staging_revision_changed_before_worker_read(api, monkeypatch):
    created = book(api)
    imported = batch(api, created["id"], [("bad", "2026-02-01", "invalid", "VND")])
    row = call(api, "GET", f"/import-jobs/{imported['id']}/staging")["items"][0]
    entered, release = threading.Event(), threading.Event()
    original = AccountingJobs.export

    def intercept(worker, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(worker, *args, **kwargs)

    monkeypatch.setattr(AccountingJobs, "export", intercept)
    try:
        export = call(
            api,
            "POST",
            f"/import-jobs/{imported['id']}/exports",
            json={"format": "csv", "request_key": key()},
        )
        assert entered.wait(10)
        patch(api, imported, row, {"amount": "1.25"})
    finally:
        release.set()
    status = wait_export(api, export["job_id"], expected="FAILED")
    assert status["error_code"] == "EXPORT_REVISION_STALE"
    assert status["file_id"] is None
