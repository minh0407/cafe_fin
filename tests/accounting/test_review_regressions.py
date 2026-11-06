"""Independent coordinator findings, converted into passing behavior regressions."""

import io
import zipfile
from datetime import date, datetime, timezone

import pytest
from cafe_fin.accounting.public import AccountingReadProvider
from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import AUDIT
from cafe_fin.core.errors import CoreError
from sqlalchemy import delete
from test_import_regressions import account as account
from test_import_regressions import confirm, key, pause_after_chunk, ready, wait_job
from test_public_api import api as api
from test_public_api import create_book, request, upload


def test_operator_cannot_reuse_admin_source_to_read_private_staging(api):
    book = create_book(api)
    stored = upload(api, b"code,day,amount\nSYNTHETIC-ADMIN-PRIVATE,2026-02-01,77.00\n")
    response = api["client"].post(
        "/api/v1/accounting/import-jobs",
        headers=api["headers"]["operator"],
        json={"book_id": book["id"], "file_id": stored["id"], "profile": {}, "request_key": key()},
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert request(api, "GET", f"/import-jobs?book_id={book['id']}", role="operator")["total"] == 0


@pytest.mark.parametrize("provenance", ["missing", "ambiguous"])
def test_module_file_ingress_and_idempotent_replay_fail_closed_for_bad_provenance(api, provenance):
    book = create_book(api)
    stored = upload(api, b"code,day,amount\nsynthetic,2026-02-01,1.00\n")
    command = {"book_id": book["id"], "file_id": stored["id"], "profile": {}, "request_key": key()}
    original = request(api, "POST", "/import-jobs", json=command)
    runtime, actor = api["runtime"], api["actor"]

    def corrupt_fixture(conn):
        if provenance == "missing":
            conn.execute(
                delete(AUDIT).where(
                    AUDIT.c.entity == "core_file",
                    AUDIT.c.entity_id == stored["id"],
                    AUDIT.c.action == "CREATE",
                )
            )
        else:
            AuditService.record(
                conn,
                actor=actor.id,
                entity="core_file",
                entity_id=stored["id"],
                action="CREATE",
                after={"synthetic_duplicate": True},
            )

    runtime.writer.run(corrupt_fixture)
    result = api["client"].post(
        "/api/v1/accounting/import-jobs", headers=api["headers"]["admin"], json=command
    )
    assert result.status_code == 403 and original["id"]
    result = api["client"].post(
        "/api/v1/accounting/import-jobs",
        headers=api["headers"]["admin"],
        json=command | {"request_key": key(), "allow_duplicate_file": True},
    )
    assert result.status_code == 403


def test_module_file_ingress_rejects_uuid_aliases(api):
    book = create_book(api)
    stored = upload(api, b"code,day,amount\nsynthetic,2026-02-01,1.00\n")
    for alias in (stored["id"].upper(), stored["id"].replace("-", ""), "{" + stored["id"] + "}"):
        result = api["client"].post(
            "/api/v1/accounting/import-jobs",
            headers=api["headers"]["admin"],
            json={"book_id": book["id"], "file_id": alias, "profile": {}, "request_key": key()},
        )
        assert result.status_code == 422 and result.json()["error"]["code"] == "FILE_ID_INVALID"


def test_schema_rename_refused_during_pending_and_after_cancel_then_works_after_publish(
    account, monkeypatch
):
    _, actor, service = account
    book, batch = ready(account, "001,2026-02-01,10.00\n")
    entered, release = pause_after_chunk(monkeypatch, "commit_pending")
    changed = [dict(column) for column in book["columns"]]
    changed[0]["name"] = "Tên hiển thị mới"
    try:
        confirm(service, actor, batch)
        assert entered.wait(10)
        with pytest.raises(CoreError, match="BOOK_IMPORT_LOCKED"):
            service.update_schema(
                actor, book["id"], book["version"], changed, book["semantics"], key()
            )
        service.cancel_resume(actor, batch["id"], "cancel")
        with pytest.raises(CoreError, match="BOOK_IMPORT_LOCKED"):
            service.update_schema(
                actor, book["id"], book["version"], changed, book["semantics"], key()
            )
    finally:
        release.set()
    wait_job(service, actor, batch["id"], expected="CANCELLED")
    service.cancel_resume(actor, batch["id"], "resume")
    wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, book["id"])["total"] == 1
    updated = service.update_schema(
        actor, book["id"], book["version"], changed, book["semantics"], key()
    )
    assert updated["schema_revision"] == 2


def test_calculated_date_serial_does_not_use_stale_iso_date_cache(account):
    runtime, actor, service = account
    book = service.create_book(
        actor,
        "Ngày công thức",
        [dict(id="day", name="Ngày", kind="date", required=True)],
        {},
        key(),
    )
    source = io.BytesIO()
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets><sheet name="Date" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{main}"><sheetData><row r="2"><c r="A2" t="d"><f>2</f><v>2026-01-01T00:00:00</v></c></row></sheetData></worksheet>',
        )
    source.seek(0)
    stored = runtime.files.put(
        source,
        category="workbooks",
        original_name="date-formula.xlsx",
        actor=actor.id,
        request_key=key(),
    )
    batch = service.create_batch(actor, book["id"], stored.id, {}, key())
    batch = wait_job(service, actor, batch["id"])
    batch = service.mapping(actor, batch["id"], batch["version"], {"day": "A"}, {}, key())
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    rows = service.staging_page(actor, batch["id"])["items"]
    assert rows[0]["typed_values"]["day"] == "1900-01-02" and rows[0]["issues"] == []
    assert rows[0]["formulas"]["A"]["cached_value"] == "2026-01-01T00:00:00"
    confirm(service, actor, batch)
    wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, book["id"])["items"][0]["values"]["day"] == "1900-01-02"


def test_inclusive_last_day_single_day_and_vietnam_boundary_in_public_provider(account):
    runtime, actor, service = account
    book = service.create_book(
        actor,
        "Kỳ ngày",
        [dict(id="day", name="Ngày", kind="date"), dict(id="amount", name="Thu", kind="money")],
        {
            "date_column": "day",
            "income_column": "amount",
            "metric_meanings": {"income": "cash_receipts"},
        },
        key(),
    )
    for day, amount in [("2026-02-01", "1.25"), ("2026-02-02", "2.75"), ("2026-02-03", "1000.00")]:
        service.create_row(actor, book["id"], {"day": day, "amount": amount}, key())
    reader = AccountingReadProvider(runtime, actor)
    cutoff = datetime(2026, 2, 2, 17, 0, tzinfo=timezone.utc)
    with runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = AccountingReadProvider(runtime, actor, connection=conn)
        result = bound.book_summary(book["id"], date(2026, 2, 1), date(2026, 2, 2), cutoff=cutoff)
        assert result.metrics[0].amount_vnd == "4.00"
        single = bound.book_summary(book["id"], date(2026, 2, 2), date(2026, 2, 2), cutoff=cutoff)
        assert single.metrics[0].amount_vnd == "2.75" and single.cutoff == cutoff
    assert (
        reader.book_summary(
            book["id"], date(2026, 2, 2), date(2026, 2, 2), cutoff=datetime.now(timezone.utc)
        )
        .metrics[0]
        .amount_vnd
        == "2.75"
    )


def test_date_only_contract_rejects_unhyphenated_dates_instead_of_silent_zero(account):
    _, actor, service = account
    book, _ = ready(account, "001,2026-02-01,10.00\n")
    with pytest.raises(CoreError, match="DATE_RANGE_INVALID"):
        service.summary(actor, book["id"], "20260201", "20260202")


def test_failed_partial_parse_cannot_be_validated_as_if_unread_tail_were_empty(account):
    runtime, actor, service = account
    columns = [dict(id=f"c{i}", name=f"C{i}", kind="text") for i in range(10)]
    book = service.create_book(actor, "Parse completeness", columns, {}, key())
    raw = (
        ",".join(f"C{i}" for i in range(10))
        + "\n"
        + ("ok," * 9 + "ok\n") * 1000
        + ",".join(["x" * 32767] * 10)
        + "\n"
    ).encode()
    stored = runtime.files.put(
        io.BytesIO(raw),
        category="workbooks",
        original_name="partial-parse.csv",
        actor=actor.id,
        request_key=key(),
    )
    batch = service.create_batch(actor, book["id"], stored.id, {}, key())
    batch = wait_job(service, actor, batch["id"], expected="FAILED")
    assert batch["counts"]["source_rows"] == 1000 and batch["error_code"] == "ROW_LIMIT"
    mapping = {f"c{i}": chr(65 + i) for i in range(10)}
    batch = service.mapping(actor, batch["id"], batch["version"], mapping, {}, key())
    with pytest.raises(CoreError, match="PARSE_INCOMPLETE"):
        service.validate(actor, batch["id"], batch["version"], key())
    assert service.list_rows(actor, book["id"])["total"] == 0
    # Explicitly choosing a supported range is a new parse, not silently treating
    # the unread source record as an empty/valid row.
    service.mapping(actor, batch["id"], batch["version"], mapping, {"end_row": 1001}, key())
    batch = wait_job(service, actor, batch["id"])
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    assert batch["counts"]["validated"] == 1000 and batch["counts"]["published_rows"] == 0
