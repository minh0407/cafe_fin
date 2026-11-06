"""Real file-backed SQLite and worker regressions for import publication."""

import io
import json
import threading
import time
import zipfile
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.jobs import AccountingJobs
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import attempts, claims, manifest_rows
from cafe_fin.core.jobs import JobContext, JobInterrupted
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from openpyxl import Workbook
from sqlalchemy import func, select


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    from cafe_fin.accounting.module import module_manifest

    runtime = Runtime(
        tmp_path / "accounting-regression",
        initialize=True,
        modules=ModuleRegistry((module_manifest(),)),
    )
    session = runtime.auth.setup("accounting-admin", "synthetic-regression-password")
    actor = runtime.auth.authenticate(session["access_token"])
    service = AccountingService(runtime)
    runtime.start()
    try:
        yield runtime, actor, service
    finally:
        runtime.close()


def wait_job(service, actor, batch_id, *, expected="COMPLETED"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        batch = service.get_batch(actor, batch_id)
        job = batch.get("job", {})
        if job.get("state") == "COMPLETED" and batch["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue  # A status read can straddle the worker's publication transaction.
        if job.get("state") in ("COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"):
            assert job["state"] == expected, (job, batch)
            return batch
        time.sleep(0.01)
    pytest.fail("accounting worker did not reach terminal state")


def book(service, actor, *, business_key=False):
    return service.create_book(
        actor,
        "Sổ kiểm thử",
        [
            {"id": "code", "name": "Mã", "kind": "text", "required": True},
            {"id": "day", "name": "Ngày", "kind": "date", "required": True},
            {"id": "amount", "name": "Thu", "kind": "money", "required": True},
        ],
        {"date_column": "day", "income_column": "amount"}
        | ({"business_key_columns": ["code"]} if business_key else {}),
        key(),
    )


def ready(account, data, *, business_key=False):
    runtime, actor, service = account
    created = book(service, actor, business_key=business_key)
    stored = runtime.files.put(
        io.BytesIO(("Mã,Ngày,Thu\n" + data).encode("utf-8-sig")),
        category="workbooks",
        original_name="synthetic-source.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    batch = service.create_batch(actor, created["id"], stored.id, {}, key())
    batch = wait_job(service, actor, batch["id"])
    batch = service.mapping(
        actor,
        batch["id"],
        batch["version"],
        {"code": "A", "day": "B", "amount": "C"},
        {},
        key(),
    )
    service.validate(actor, batch["id"], batch["version"], key())
    return created, wait_job(service, actor, batch["id"])


def confirm(service, actor, batch):
    return service.confirm(
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


def pause_after_chunk(monkeypatch, phase):
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == phase and not entered.is_set():
            entered.set()
            assert release.wait(10), "test did not release paused worker"
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    return entered, release


def test_partial_import_fix_then_confirm_preserves_original_lineage(account):
    runtime, actor, service = account
    created, batch = ready(account, "001,2026-02-01,10.25\n002,2026-02-01,bad\n")
    assert batch["counts"]["valid"] == 1
    confirm(service, actor, batch)
    batch = wait_job(service, actor, batch["id"])
    assert batch["state"] == "PARTIALLY_COMMITTED"
    original = service.list_rows(actor, created["id"])["items"][0]
    invalid = service.staging_page(actor, batch["id"], status="invalid")["items"][0]
    batch = service.patch_staging(
        actor,
        batch["id"],
        batch["version"],
        [
            {
                "row_id": invalid["row_id"],
                "expected_version": invalid["revision"],
                "values": {"amount": "20.75"},
            }
        ],
        key(),
    )
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    confirm(service, actor, batch)
    batch = wait_job(service, actor, batch["id"])
    rows = service.list_rows(actor, created["id"])
    assert rows["total"] == 2
    assert original["id"] in {row["id"] for row in rows["items"]}
    assert batch["counts"]["published_rows"] == 2
    assert (
        service.summary(actor, created["id"], "2026-02-01", "2026-02-02")["totals"]["VND"]["income"]
        == "31.00"
    )
    with runtime.reader() as connection:
        assert connection.execute(select(func.count()).select_from(claims)).scalar_one() == 2
        assert (
            connection.execute(
                select(func.count()).select_from(attempts).where(attempts.c.state == "PUBLISHED")
            ).scalar_one()
            == 2
        )


def test_pending_rows_hidden_cancel_then_resume_publishes_once(account, monkeypatch):
    runtime, actor, service = account
    created, batch = ready(account, "001,2026-02-01,10\n002,2026-02-01,20\n")
    entered, release = pause_after_chunk(monkeypatch, "commit_pending")
    try:
        confirm(service, actor, batch)
        assert entered.wait(10)
        assert service.list_rows(actor, created["id"])["total"] == 0
        assert service.summary(actor, created["id"], "2026-02-01", "2026-02-02")["totals"] == {}
        with runtime.reader() as connection:
            assert connection.execute(select(func.count()).select_from(s.entries)).scalar_one() == 2
            pending_id = connection.execute(select(s.entries.c.id).limit(1)).scalar_one()
        with pytest.raises(CoreError) as error:
            service.mutate_row(actor, pending_id, 1, key(), action="delete")
        assert error.value.code == "ROW_NOT_FOUND"
        service.cancel_resume(actor, batch["id"], "cancel")
    finally:
        release.set()
    batch = wait_job(service, actor, batch["id"], expected="CANCELLED")
    assert batch["counts"]["pending"] == 2
    assert service.list_rows(actor, created["id"])["total"] == 0
    service.cancel_resume(actor, batch["id"], "resume")
    batch = wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, created["id"])["total"] == 2
    assert batch["counts"]["published_rows"] == 2
    with runtime.reader() as connection:
        assert connection.execute(select(func.count()).select_from(claims)).scalar_one() == 2


def test_cancel_validation_after_partial_publish_does_not_cancel_published_attempt(
    account, monkeypatch
):
    runtime, actor, service = account
    created, batch = ready(account, "001,2026-02-01,10\n002,2026-02-01,bad\n")
    confirm(service, actor, batch)
    batch = wait_job(service, actor, batch["id"])
    published_attempt = batch["attempt_id"]
    entered, release = pause_after_chunk(monkeypatch, "normalize")
    try:
        service.validate(actor, batch["id"], batch["version"], key())
        assert entered.wait(10)
        service.cancel_resume(actor, batch["id"], "cancel")
    finally:
        release.set()
    batch = wait_job(service, actor, batch["id"], expected="CANCELLED")
    assert service.list_rows(actor, created["id"])["total"] == 1
    with runtime.reader() as connection:
        assert (
            connection.execute(
                select(attempts.c.state).where(attempts.c.id == published_attempt)
            ).scalar_one()
            == "PUBLISHED"
        )
    service.cancel_resume(actor, batch["id"], "resume")
    wait_job(service, actor, batch["id"])


def test_skipped_business_key_duplicate_does_not_block_kept_row(account):
    _, actor, service = account
    created, batch = ready(account, "001,2026-02-01,10\n001,2026-02-01,20\n", business_key=True)
    assert batch["counts"]["conflicts"] == 2
    staged = service.staging_page(actor, batch["id"])["items"]
    batch = service.decisions(
        actor,
        batch["id"],
        batch["version"],
        [{"row_id": staged[1]["row_id"], "decision": "skip"}],
        None,
        key(),
    )
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    kept = next(
        row
        for row in service.staging_page(actor, batch["id"])["items"]
        if row["row_id"] == staged[0]["row_id"]
    )
    assert not any(issue["code"] == "BUSINESS_KEY_CONFLICT" for issue in kept["issues"])
    confirm(service, actor, batch)
    wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, created["id"])["total"] == 1


def test_failed_validation_can_be_patched_and_revalidated(account, monkeypatch):
    _, actor, service = account
    created, batch = ready(account, "001,2026-02-01,bad\n")
    original = AccountingJobs._stage_values
    fail_once = True

    def interrupted(worker, *args, **kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise CoreError(
                "SYNTHETIC_VALIDATION_INTERRUPTION", "Synthetic recoverable probe.", 503
            )
        return original(worker, *args, **kwargs)

    monkeypatch.setattr(AccountingJobs, "_stage_values", interrupted)
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"], expected="FAILED")
    row = service.staging_page(actor, batch["id"])["items"][0]
    batch = service.patch_staging(
        actor,
        batch["id"],
        batch["version"],
        [
            {
                "row_id": row["row_id"],
                "expected_version": row["revision"],
                "values": {"amount": "42.00"},
            }
        ],
        key(),
    )
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    confirm(service, actor, batch)
    wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, created["id"])["items"][0]["values"]["amount"] == "42.00"


def test_crud_request_replay_and_version_conflicts(account):
    _, actor, service = account
    created = book(service, actor)
    request_key = key()
    values = {"code": "0001", "day": "2026-02-01", "amount": "12.25"}
    first = service.create_row(actor, created["id"], values, request_key)
    assert service.create_row(actor, created["id"], values, request_key) == first
    with pytest.raises(CoreError) as error:
        service.create_row(actor, created["id"], values | {"amount": "99"}, request_key)
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    request_key = key()
    revised = service.mutate_row(actor, first["id"], 1, request_key, values={"amount": "13.25"})
    assert (
        service.mutate_row(actor, first["id"], 1, request_key, values={"amount": "13.25"})
        == revised
    )
    with pytest.raises(CoreError) as error:
        service.mutate_row(actor, first["id"], 1, key(), values={"amount": "20.00"})
    assert error.value.status == 409
    request_key = key()
    deleted = service.mutate_row(
        actor, first["id"], revised["version"], request_key, action="delete"
    )
    assert (
        service.mutate_row(actor, first["id"], revised["version"], request_key, action="delete")
        == deleted
    )
    assert service.list_rows(actor, created["id"])["total"] == 0
    request_key = key()
    restored = service.mutate_row(
        actor, first["id"], deleted["version"], request_key, action="restore"
    )
    assert (
        service.mutate_row(actor, first["id"], deleted["version"], request_key, action="restore")
        == restored
    )
    assert service.list_rows(actor, created["id"])["total"] == 1


def test_snapshot_lock_and_cancelled_worker_cannot_publish(account, monkeypatch):
    runtime, actor, service = account
    created, batch = ready(account, "001,2026-02-01,10\n")
    row = service.staging_page(actor, batch["id"])["items"][0]
    entered, release = threading.Event(), threading.Event()
    original = JobContext.commit_chunk
    held = []

    def intercept(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "commit_pending" and not held:
            held.append(context)
            entered.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", intercept)
    effects = []
    try:
        confirm(service, actor, batch)
        assert entered.wait(10)
        current = service.get_batch(actor, batch["id"])
        with pytest.raises(CoreError):
            service.patch_staging(
                actor,
                batch["id"],
                current["version"],
                [
                    {
                        "row_id": row["row_id"],
                        "expected_version": row["revision"],
                        "values": {"amount": "999.00"},
                    }
                ],
                key(),
            )
        with runtime.reader() as connection:
            snapshot = json.loads(
                connection.execute(
                    select(manifest_rows.c.snapshot_json).where(
                        manifest_rows.c.manifest_id == current["manifest_id"]
                    )
                ).scalar_one()
            )
        assert snapshot["typed_values"]["amount"] == "10.00"
        service.cancel_resume(actor, batch["id"], "cancel")
        with pytest.raises(JobInterrupted):
            held[0].finalize(lambda connection: effects.append("stale publication"))
        assert not effects
        current = service.get_batch(actor, batch["id"])
        with pytest.raises(CoreError) as error:
            service.patch_staging(
                actor,
                batch["id"],
                current["version"],
                [
                    {
                        "row_id": row["row_id"],
                        "expected_version": row["revision"],
                        "values": {"amount": "999.00"},
                    }
                ],
                key(),
            )
        assert error.value.code == "IMPORT_ATTEMPT_LOCKED"
    finally:
        release.set()
    wait_job(service, actor, batch["id"], expected="CANCELLED")
    service.cancel_resume(actor, batch["id"], "resume")
    wait_job(service, actor, batch["id"])
    assert service.list_rows(actor, created["id"])["items"][0]["values"]["amount"] == "10.00"
    with pytest.raises(JobInterrupted):
        held[0].finalize(lambda connection: effects.append("old generation publication"))
    assert not effects


def test_formula_import_preserves_raw_cache_and_calculated_provenance(account):
    runtime, actor, service = account
    created = book(service, actor)
    source = io.BytesIO()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Mã", "Ngày", "Thu"])
    worksheet.append(["0001", "2026-02-01", "=SUM(1,2)"])
    workbook.save(source)
    workbook.close()
    rewritten = io.BytesIO()
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(rewritten, "w", zipfile.ZIP_DEFLATED) as output,
    ):
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                assert b"<f>SUM(1,2)</f><v></v>" in content
                content = content.replace(
                    b"<f>SUM(1,2)</f><v></v>", b"<f>SUM(1,2)</f><v>999.25</v>"
                )
            output.writestr(entry.filename, content)
    rewritten.seek(0)
    stored = runtime.files.put(
        rewritten,
        category="workbooks",
        original_name="formula-source.xlsx",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    batch = service.create_batch(actor, created["id"], stored.id, {}, key())
    batch = wait_job(service, actor, batch["id"])
    batch = service.mapping(
        actor, batch["id"], batch["version"], {"code": "A", "day": "B", "amount": "C"}, {}, key()
    )
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    with runtime.reader() as connection:
        stage = (
            connection.execute(select(s.stage).where(s.stage.c.batch_id == batch["id"]))
            .mappings()
            .one()
        )
        assert json.loads(stage.formulas_json)["C"]["cached_value"] == "999.25"
        calculation = json.loads(stage.metadata_json)["calculations"]["amount"]
        assert calculation["calculation_status"] == "supported_calculated"
        assert calculation["cached_value"] == "999.25"
        assert calculation["calculated_value"] == "3"
    confirm(service, actor, batch)
    wait_job(service, actor, batch["id"])
    result = service.list_rows(actor, created["id"])["items"][0]
    assert result["values"]["amount"] == "3.00"
    assert result["formulas"]["amount"]["calculation_status"] == "supported_calculated"
    assert result["formulas"]["amount"]["cached_value"] == "999.25"
    assert runtime.files.get(stored.id).sha256 == stored.sha256


def test_duplicate_decision_cannot_exclude_a_published_source(account):
    _, actor, service = account
    _, batch = ready(account, "001,2026-02-01,10\n002,2026-02-01,bad\n")
    confirm(service, actor, batch)
    batch = wait_job(service, actor, batch["id"])
    imported = service.staging_page(actor, batch["id"], status="imported")["items"][0]
    batch = service.decisions(
        actor,
        batch["id"],
        batch["version"],
        [{"row_id": imported["row_id"], "decision": "skip"}],
        None,
        key(),
    )
    imported_after = service.staging_page(actor, batch["id"], status="imported")["items"][0]
    assert imported_after["decision"] is None
    service.validate(actor, batch["id"], batch["version"], key())
    batch = wait_job(service, actor, batch["id"])
    assert batch["counts"]["published_rows"] == 1
    assert batch["counts"]["excluded"] == 0


def test_superseded_failed_parse_cannot_resume_into_reparsed_staging(account, monkeypatch):
    runtime, actor, service = account
    created = book(service, actor)
    original = JobContext.commit_chunk
    fail_once = True

    def interrupt_after_committed_parse(context, *args, **kwargs):
        nonlocal fail_once
        result = original(context, *args, **kwargs)
        if kwargs["phase"] == "parse" and fail_once:
            fail_once = False
            raise CoreError(
                "SYNTHETIC_AFTER_PARSE_COMMIT", "Synthetic crash after durable chunk.", 503
            )
        return result

    monkeypatch.setattr(JobContext, "commit_chunk", interrupt_after_committed_parse)
    data = "Mã,Ngày,Thu\n" + "".join(f"{i:04d},2026-02-01,1\n" for i in range(1001))
    stored = runtime.files.put(
        io.BytesIO(data.encode()),
        category="workbooks",
        original_name="superseded.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    batch = service.create_batch(actor, created["id"], stored.id, {}, key())
    batch = wait_job(service, actor, batch["id"], expected="FAILED")
    old_job_id = batch["job_id"]
    assert batch["counts"]["source_rows"] == 500
    service.mapping(
        actor,
        batch["id"],
        batch["version"],
        {"code": "A", "day": "B", "amount": "C"},
        {"start_row": 3},
        key(),
    )
    batch = wait_job(service, actor, batch["id"])
    assert batch["counts"]["source_rows"] == 1000
    runtime.jobs.resume(old_job_id, authorize=service.authorize(actor))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        old = runtime.jobs.status(old_job_id)
        if old["state"] in ("FAILED", "COMPLETED", "CANCELLED"):
            break
        time.sleep(0.01)
    assert old["state"] == "FAILED"
    assert old["error_code"] == "JOB_SUPERSEDED"
    assert service.get_batch(actor, batch["id"])["state"] == "READY_FOR_MAPPING"
    assert service.staging_page(actor, batch["id"])["total"] == 1000
