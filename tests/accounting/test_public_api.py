"""Public HTTP boundaries, derived files and caller-owned report snapshots."""

import csv
import hashlib
import io
import json
import threading
import time
import zipfile
from datetime import date, datetime, timezone
from urllib.parse import quote
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.api import create_app
from cafe_fin.core.db import AUDIT
from cafe_fin.core.jobs import JobContext
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

ROOT = "/api/v1/accounting"
COLUMNS = [
    {"id": "code", "name": "Mã", "kind": "text", "required": True},
    {"id": "day", "name": "Ngày", "kind": "date", "required": True},
    {"id": "amount", "name": "Thu", "kind": "money", "precision": 19, "required": True},
]
SEMANTICS = {"date_column": "day", "income_column": "amount"}


def key():
    return str(uuid4())


@pytest.fixture
def api(tmp_path):
    runtime = Runtime(
        tmp_path / "public-api", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("accounting-admin", "synthetic-public-password")
    actor = runtime.auth.authenticate(session["access_token"])
    runtime.auth.create_user(
        actor,
        username="accounting-operator",
        password="synthetic-operator-password",
        role="operator",
        request_key=key(),
    )
    operator_session = runtime.auth.login("accounting-operator", "synthetic-operator-password")
    app_token, port = "synthetic-public-app-session-0123456789", 48955
    common = {"X-App-Session": app_token, "Origin": "http://tauri.localhost"}
    headers = {
        "admin": common | {"Authorization": "Bearer " + session["access_token"]},
        "operator": common | {"Authorization": "Bearer " + operator_session["access_token"]},
    }
    app = create_app(runtime, app_token, port=port)
    try:
        with TestClient(
            app, base_url=f"http://127.0.0.1:{port}", raise_server_exceptions=False
        ) as client:
            yield {"runtime": runtime, "client": client, "headers": headers, "actor": actor}
    finally:
        runtime.close()


def request(api, method, path, *, role="admin", expected=200, **kwargs):
    response = api["client"].request(method, ROOT + path, headers=api["headers"][role], **kwargs)
    assert response.status_code == expected, (response.status_code, response.text)
    return response.json()


def create_book(api):
    return request(
        api,
        "POST",
        "/books",
        json={"name": "Sổ API", "columns": COLUMNS, "semantics": SEMANTICS, "request_key": key()},
    )


def create_row(api, book_id, code, amount, *, role="operator"):
    return request(
        api,
        "POST",
        f"/books/{book_id}/rows",
        role=role,
        json={
            "values": {"code": code, "day": "2026-02-01", "amount": amount},
            "request_key": key(),
        },
    )


def upload(api, data, filename="Nguồn kế toán.csv", *, role="admin"):
    response = api["client"].post(
        "/api/v1/files",
        content=data,
        headers=api["headers"][role]
        | {
            "X-File-Name": quote(filename),
            "X-Request-Key": key(),
            "Content-Type": "application/octet-stream",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_batch(api, batch_id, expected="COMPLETED"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch = request(api, "GET", f"/import-jobs/{batch_id}")
        job = batch.get("job", {})
        if job.get("state") == "COMPLETED" and batch["state"] in (
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        ):
            time.sleep(0.01)
            continue
        if job.get("state") in ("COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"):
            assert job["state"] == expected, batch
            return batch
        time.sleep(0.01)
    pytest.fail("public import status did not finish")


def parsed_batch(api, book_id, data=b"code,day,amount\n001,2026-02-01,10\n"):
    stored = upload(api, data)
    batch = request(
        api,
        "POST",
        "/import-jobs",
        json={"book_id": book_id, "file_id": stored["id"], "request_key": key()},
    )
    return stored, wait_batch(api, batch["id"])


def ready_batch(api, book_id):
    stored, batch = parsed_batch(api, book_id)
    batch = request(
        api,
        "POST",
        f"/import-jobs/{batch['id']}/mapping",
        json={
            "expected_version": batch["version"],
            "mapping": {"code": "A", "day": "B", "amount": "C"},
            "request_key": key(),
        },
    )
    request(
        api,
        "POST",
        f"/import-jobs/{batch['id']}/validate",
        json={"expected_version": batch["version"], "request_key": key()},
    )
    return stored, wait_batch(api, batch["id"])


def export_bytes(api, book_id, format_name):
    result = request(
        api, "POST", f"/books/{book_id}/exports", json={"format": format_name, "request_key": key()}
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = request(api, "GET", f"/exports/{result['job_id']}")
        if status["state"] in ("FAILED", "CANCELLED", "RECOVERABLE"):
            pytest.fail(str(status))
        if status["state"] == "COMPLETED" and status["file_id"]:
            break
        time.sleep(0.01)
    assert status["state"] == "COMPLETED"
    assert status["derived"] and status["numeric_encoding"] == (
        "numeric_up_to_15_digits_else_exact_text" if format_name == "xlsx" else "exact_text"
    )
    response = api["client"].get(
        f"/api/v1/files/{status['file_id']}/content", headers=api["headers"]["admin"]
    )
    assert response.status_code == 200
    return result, status, response.content


def test_typed_payload_errors_and_admin_configuration_restore_permissions(api):
    book = create_book(api)
    denied = request(
        api,
        "POST",
        "/books",
        role="operator",
        expected=403,
        json={"name": "Forbidden", "columns": COLUMNS, "request_key": key()},
    )
    assert denied["error"]["code"] == "PERMISSION_DENIED"
    request(
        api,
        "PATCH",
        f"/books/{book['id']}/schema",
        role="operator",
        expected=403,
        json={
            "expected_version": book["version"],
            "columns": COLUMNS,
            "semantics": SEMANTICS,
            "request_key": key(),
        },
    )
    for payload in (
        {"values": {"amount": 1.25}, "request_key": key()},
        {"values": {}, "request_key": key(), "unknown": True},
    ):
        invalid = request(api, "POST", f"/books/{book['id']}/rows", expected=422, json=payload)
        assert invalid["error"]["code"] == "VALIDATION_ERROR"
        assert invalid["error"]["field_errors"] and invalid["request_id"]
    row = create_row(api, book["id"], "0001", "12.25")
    deleted = request(
        api,
        "POST",
        f"/rows/{row['id']}/delete",
        role="operator",
        json={"expected_version": row["version"], "request_key": key()},
    )
    request(
        api,
        "POST",
        f"/rows/{row['id']}/restore",
        role="operator",
        expected=403,
        json={"expected_version": deleted["version"], "request_key": key()},
    )
    restored = request(
        api,
        "POST",
        f"/rows/{row['id']}/restore",
        json={"expected_version": deleted["version"], "request_key": key()},
    )
    assert restored["deleted_at"] is None


def test_crud_paging_exact_numeric_sort_filters_conflicts_and_audit(api):
    book = create_book(api)
    created = [
        create_row(api, book["id"], code, amount)
        for code, amount in (
            ("0001", "90071992547409.93"),
            ("0002", "2.00"),
            ("0003", "10.00"),
            ("0004", "-1.25"),
        )
    ]
    page = request(
        api,
        "GET",
        f"/books/{book['id']}/rows",
        params={"sort": "amount:asc", "page_size": 2, "page": 2},
    )
    assert page["total"] == 4
    assert [row["values"]["amount"] for row in page["items"]] == ["10.00", "90071992547409.93"]
    filtered = request(
        api,
        "GET",
        f"/books/{book['id']}/rows",
        params={
            "filters": json.dumps([{"column_id": "amount", "op": "gte", "value": "10"}]),
            "sort": "amount:desc",
        },
    )
    assert filtered["total"] == 2
    for params in (
        {"sort": "amount;DROP TABLE accounting_books:asc"},
        {"filters": '[{"column_id":"code","op":"sql","value":"x"}]'},
        {"page_size": 501},
    ):
        request(api, "GET", f"/books/{book['id']}/rows", expected=400, params=params)
    revised = request(
        api,
        "PATCH",
        f"/rows/{created[0]['id']}",
        role="operator",
        json={"expected_version": 1, "values": {"amount": "42.50"}, "request_key": key()},
    )
    conflict = request(
        api,
        "PATCH",
        f"/rows/{created[0]['id']}",
        role="operator",
        expected=409,
        json={"expected_version": 1, "values": {"amount": "0"}, "request_key": key()},
    )
    assert conflict["error"]["code"] == "VERSION_CONFLICT"
    assert request(api, "GET", f"/rows/{created[0]['id']}")["version"] == revised["version"]
    with api["runtime"].reader() as connection:
        records = (
            connection.execute(
                select(AUDIT).where(
                    AUDIT.c.entity == "accounting_row", AUDIT.c.entity_id == created[0]["id"]
                )
            )
            .mappings()
            .all()
        )
    assert {record["action"] for record in records} == {"create", "update"}
    updated = next(record for record in records if record["action"] == "update")
    assert json.loads(updated["before_json"])["values"]["amount"] == "90071992547409.93"
    assert json.loads(updated["after_json"])["values"]["amount"] == "42.50"


def test_batch_scope_original_bytes_and_module_job_mutations_are_protected(api):
    book = create_book(api)
    original = "\ufeffMã,Ngày,Thu\r\n0001,2026-02-01,12.25\r\n".encode()
    stored, batch = parsed_batch(api, book["id"], original)
    assert stored["sha256"] == hashlib.sha256(original).hexdigest()
    assert stored["size"] == len(original)
    assert stored["original_name"] == "Nguồn kế toán.csv"
    assert stored["category"] == "workbooks"
    assert "relative_key" not in stored
    response = api["client"].get(
        f"/api/v1/files/{stored['id']}/content", headers=api["headers"]["admin"]
    )
    assert response.content == original
    assert response.headers["X-Content-SHA256"] == stored["sha256"]
    for suffix in ("", "/staging", "/issues", "/duplicates"):
        denied = request(
            api, "GET", f"/import-jobs/{batch['id']}{suffix}", role="operator", expected=403
        )
        assert denied["error"]["code"] == "PERMISSION_DENIED"
    request(
        api,
        "POST",
        f"/import-jobs/{batch['id']}/cancel",
        role="operator",
        expected=403,
        json={"request_key": key()},
    )
    listed = request(api, "GET", "/import-jobs", role="operator", params={"book_id": book["id"]})
    assert listed["total"] == 0
    for action in ("cancel", "resume"):
        response = api["client"].post(
            f"/api/v1/jobs/{batch['job_id']}/{action}", headers=api["headers"]["operator"]
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MODULE_JOB_ENDPOINT_REQUIRED"
    # File endpoints use the global files.read permission; accounting batch scope is separate.
    no_auth = api["client"].get(
        f"/api/v1/files/{stored['id']}/content",
        headers={
            "X-App-Session": api["headers"]["admin"]["X-App-Session"],
            "Origin": "http://tauri.localhost",
        },
    )
    assert no_auth.status_code == 401


def test_other_actor_cannot_read_accounting_core_job_status(api):
    book = create_book(api)
    _, batch = parsed_batch(api, book["id"])
    response = api["client"].get(
        f"/api/v1/jobs/{batch['job_id']}", headers=api["headers"]["operator"]
    )
    assert response.status_code == 403


@pytest.mark.parametrize("suffix", ["", "/content"])
def test_personal_source_file_actor_boundary_requires_shared_core_policy(api, suffix):
    stored = upload(api, b"code,day,amount\n001,2026-02-01,10\n")
    response = api["client"].get(
        f"/api/v1/files/{stored['id']}{suffix}", headers=api["headers"]["operator"]
    )
    assert response.status_code == 403


@pytest.mark.parametrize("format_name", ["csv", "xlsx"])
def test_derived_export_preserves_exact_values_and_blocks_formula_injection(api, format_name):
    book = create_book(api)
    create_row(api, book["id"], '=WEBSERVICE("https://not-called.invalid")', "90071992547409.93")
    create_row(api, book["id"], "000007", "-12.25")
    result, _, content = export_bytes(api, book["id"], format_name)
    request(api, "GET", f"/exports/{result['job_id']}", role="operator", expected=403)
    if format_name == "csv":
        rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
        assert rows[1] == [
            '\'=WEBSERVICE("https://not-called.invalid")',
            "2026-02-01",
            "90071992547409.93",
        ]
        assert rows[2] == ["000007", "2026-02-01", "-12.25"]
    else:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
        try:
            rows = list(workbook.active.iter_rows())
            assert rows[1][0].value == '=WEBSERVICE("https://not-called.invalid")'
            assert rows[1][0].data_type == "s"
            assert rows[1][2].value == "90071992547409.93"
            assert rows[1][2].data_type == "s"
            assert rows[2][0].value == "000007"
            assert rows[2][2].data_type == "n"
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                xml = archive.read("xl/worksheets/sheet1.xml")
            assert b"<v>-12.25</v>" in xml
            assert b"<f>" not in xml
            assert "Phạm vi xuất" in workbook.sheetnames
        finally:
            workbook.close()


def test_pending_import_hidden_in_http_rows_summary_and_derived_export(api, monkeypatch):
    book = create_book(api)
    _, batch = ready_batch(api, book["id"])
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
        request(
            api,
            "POST",
            f"/import-jobs/{batch['id']}/confirm",
            json={
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
        status = request(api, "GET", f"/import-jobs/{batch['id']}")
        assert status["counts"]["pending"] == 1
        assert status["counts"]["published_rows"] == 0
        assert request(api, "GET", f"/books/{book['id']}/rows")["total"] == 0
        assert (
            request(
                api,
                "GET",
                f"/books/{book['id']}/summary",
                params={"from_on": "2026-02-01", "through_on": "2026-02-02"},
            )["totals"]
            == {}
        )
        with api["runtime"].reader() as connection:
            pending_id = connection.execute(select(s.entries.c.id)).scalar_one()
        request(api, "GET", f"/rows/{pending_id}", expected=404)
        request(api, "POST", f"/import-jobs/{batch['id']}/cancel", json={"request_key": key()})
    finally:
        release.set()
    wait_batch(api, batch["id"], expected="CANCELLED")
    _, _, data = export_bytes(api, book["id"], "csv")
    exported_rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert exported_rows == [["Mã", "Ngày", "Thu"]]


def test_connection_bound_read_provider_keeps_caller_snapshot_and_transaction(api, monkeypatch):
    runtime, actor = api["runtime"], api["actor"]
    book = create_book(api)
    create_row(api, book["id"], "0001", "10.25")
    cutoff = datetime.now(timezone.utc)
    with runtime.reader() as connection:
        connection.exec_driver_sql("BEGIN")
        connection.execute(
            select(s.books.c.data_revision).where(s.books.c.id == book["id"])
        ).scalar_one()
        before_transaction = connection.get_transaction()
        AccountingService(runtime).create_row(
            actor, book["id"], {"code": "0002", "day": "2026-02-01", "amount": "20.75"}, key()
        )
        provider = AccountingReadProvider(runtime, actor, connection=connection)
        with monkeypatch.context() as scoped:

            def forbidden(*args, **kwargs):
                pytest.fail("bound provider changed caller connection or opened a new reader")

            scoped.setattr(runtime, "reader", forbidden)
            for method in ("close", "commit", "rollback"):
                scoped.setattr(connection, method, forbidden)
            snapshot = provider.book_summary(
                book["id"], date(2026, 2, 1), date(2026, 2, 2), cutoff=cutoff
            )
        assert {metric.key: metric.amount_vnd for metric in snapshot.metrics}["income"] == "10.25"
        assert connection.get_transaction() is before_transaction
        assert connection.in_transaction() and not connection.closed
        assert len(connection.execute(select(s.entries.c.id)).all()) == 1
    latest = AccountingReadProvider(runtime, actor).book_summary(
        book["id"], date(2026, 2, 1), date(2026, 2, 2), cutoff=datetime.now(timezone.utc)
    )
    assert {metric.key: metric.amount_vnd for metric in latest.metrics}["income"] == "31.00"


def test_invalid_summary_dates_are_a_client_error(api):
    book = create_book(api)
    result = request(
        api,
        "GET",
        f"/books/{book['id']}/summary",
        expected=400,
        params={"from_on": "not-a-date", "through_on": "2026-02-02"},
    )
    assert result["error"]["code"] == "DATE_RANGE_INVALID"


def test_duplicate_decision_requires_typed_row_and_action(api):
    book = create_book(api)
    _, batch = parsed_batch(api, book["id"])
    result = request(
        api,
        "POST",
        f"/import-jobs/{batch['id']}/decisions",
        expected=422,
        json={"expected_version": batch["version"], "decisions": [{}], "request_key": key()},
    )
    assert result["error"]["code"] == "VALIDATION_ERROR"
