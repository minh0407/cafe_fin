"""Synthetic boundary regressions; execute only after the hardening freeze.

Row/chunk tests assert accepted/rejected payloads and transaction results. They do
not claim a measured process-RSS bound or a million-row performance result.
"""

import csv
import hashlib
import io
import random
import string
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from cafe_fin.accounting import parsers
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobInterrupted
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event, func, select

ROW_BYTES = 256 * 1024
CHUNK_BYTES = 4 * 1024**2
CELL_CHARS = 32767
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    runtime = Runtime(
        tmp_path / "hardening-app", initialize=True, modules=ModuleRegistry((module_manifest(),))
    )
    session = runtime.auth.setup("hardening-admin", "synthetic-hardening-password")
    actor = runtime.auth.authenticate(session["access_token"])
    runtime.start()
    try:
        yield runtime, actor, AccountingService(runtime)
    finally:
        runtime.close()


def wait(account, batch_id, expected="COMPLETED"):
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
        if state in {"COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"}:
            assert state == expected, batch.get("error_code")
            return batch
        time.sleep(0.01)
    pytest.fail("hardening test job deadline exceeded")


def make_book(account, *, business_key=False, text_columns=None):
    _, actor, service = account
    columns = (
        [
            {"id": f"c{index}", "name": f"Column {index}", "kind": "text"}
            for index in range(text_columns)
        ]
        if text_columns
        else [
            {"id": "code", "name": "Code", "kind": "text", "required": True},
            {"id": "day", "name": "Day", "kind": "date", "required": True},
            {"id": "amount", "name": "Amount", "kind": "money", "required": True},
        ]
    )
    return service.create_book(
        actor,
        "Hardening test",
        columns,
        {"business_key_columns": ["code"]} if business_key else {},
        key(),
    )


def store_source(account, source, filename):
    runtime, actor, service = account
    if isinstance(source, Path):
        with source.open("rb") as stream:
            return runtime.files.put(
                stream,
                category="workbooks",
                original_name=filename,
                actor=actor.id,
                request_key=key(),
                authorize=service.authorize(actor),
            )
    return runtime.files.put(
        io.BytesIO(source),
        category="workbooks",
        original_name=filename,
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )


def parsed(account, book_id, source, filename="source.csv", profile=None, expected="COMPLETED"):
    _, actor, service = account
    stored = store_source(account, source, filename)
    batch = service.create_batch(actor, book_id, stored.id, profile or {}, key())
    return stored, wait(account, batch["id"], expected)


def ready(account, book_id, amounts):
    _, actor, service = account
    source = "code,day,amount\n" + "".join(f"same,2026-02-01,{amount}\n" for amount in amounts)
    _, batch = parsed(account, book_id, source.encode())
    batch = service.mapping(
        actor, batch["id"], batch["version"], {"code": "A", "day": "B", "amount": "C"}, {}, key()
    )
    service.validate(actor, batch["id"], batch["version"], key())
    return wait(account, batch["id"])


def keep(account, batch):
    _, actor, service = account
    return service.decisions(actor, batch["id"], batch["version"], [], "keep", key())


def confirm(account, batch):
    _, actor, service = account
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


def test_identical_explicit_business_keys_are_reviewable_duplicates_in_file_and_database(account):
    _, actor, service = account
    book = make_book(account, business_key=True)
    batch = ready(account, book["id"], ["1.00", "1"])
    assert batch["counts"]["valid"] == 2
    assert batch["counts"]["conflicts"] == 0
    assert batch["counts"]["potential_duplicates"] == 2
    assert batch["counts"]["eligible"] == 0
    batch = keep(account, batch)
    assert batch["counts"]["eligible"] == 2
    confirm(account, batch)
    batch = wait(account, batch["id"])
    assert service.list_rows(actor, book["id"])["total"] == 2
    again = ready(account, book["id"], ["1.000"])
    assert again["counts"]["valid"] == 1
    assert again["counts"]["conflicts"] == 0
    assert again["counts"]["potential_duplicates"] == 1
    again = keep(account, again)
    confirm(account, again)
    wait(account, again["id"])
    assert service.list_rows(actor, book["id"])["total"] == 3


@pytest.mark.parametrize("scope", ["same_file", "published_database"])
def test_different_payload_with_same_explicit_key_stays_conflict_even_after_keep(account, scope):
    _, actor, service = account
    book = make_book(account, business_key=True)
    if scope == "published_database":
        previous = ready(account, book["id"], ["1.00"])
        confirm(account, previous)
        wait(account, previous["id"])
    batch = ready(account, book["id"], ["1.00", "2.00"] if scope == "same_file" else ["2.00"])
    assert batch["counts"]["conflicts"] == (2 if scope == "same_file" else 1)
    assert batch["counts"]["valid"] == 0
    batch = keep(account, batch)
    assert batch["counts"]["eligible"] == 0
    with pytest.raises(CoreError) as error:
        confirm(account, batch)
    assert error.value.code == "NO_ELIGIBLE_ROWS"
    assert service.list_rows(actor, book["id"])["total"] == (0 if scope == "same_file" else 1)


def letter(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def xlsx_bytes(cells, *, shared_xml=None):
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets><sheet name="Synthetic" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        row = (
            "".join(
                f'<c r="{column}2" t="inlineStr"><is><t>{value}</t></is></c>'
                for column, value in cells.items()
            )
            if shared_xml is None
            else '<c r="A2" t="s"><v>0</v></c>'
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData><row r="2">{row}</row></sheetData></worksheet>',
        )
        if shared_xml is not None:
            archive.writestr("xl/sharedStrings.xml", shared_xml)
    return source.getvalue()


def wide_source(kind, values):
    if kind == "xlsx":
        return xlsx_bytes({letter(index): value for index, value in enumerate(values, 1)})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([f"c{index}" for index in range(len(values))])
    writer.writerow(values)
    return output.getvalue().encode()


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
@pytest.mark.parametrize("text,columns", [("ascii", 10), ("utf8", 5)])
def test_parser_combined_row_utf8_budget_is_separate_from_per_cell_limit(
    tmp_path, kind, text, columns
):
    # Each cell satisfies 32,767 characters. The combined row exceeds 256 KiB.
    cell = "a" * CELL_CHARS if text == "ascii" else "ế" * CELL_CHARS
    assert len(cell) == CELL_CHARS
    assert len(cell.encode()) * columns > ROW_BYTES
    path = tmp_path / f"wide.{kind}"
    path.write_bytes(wide_source(kind, [cell] * columns))
    before = hashlib.sha256(path.read_bytes()).digest()
    with pytest.raises(parsers.ParserError) as error:
        list(parsers.iter_rows(path, path.name, {}))
    assert error.value.code == "ROW_LIMIT"
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_parser_allows_256_columns_when_sparse_small_payload_fits(tmp_path, kind):
    values = ["000001"] + [""] * 254 + ["ok"]
    source = wide_source(kind, values) if kind == "csv" else xlsx_bytes({"A": "000001", "IV": "ok"})
    path = tmp_path / f"sparse.{kind}"
    path.write_bytes(source)
    row = next(parsers.iter_rows(path, path.name, {}))
    assert row.values["A"] == "000001"
    assert row.values["IV"] == "ok"
    assert row.source_row == 2


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_parser_accepts_exact_combined_row_byte_boundary(tmp_path, kind):
    values = ["a" * CELL_CHARS] * 8 + ["b" * 8]
    assert sum(len(value.encode("utf-8")) for value in values) == ROW_BYTES
    path = tmp_path / f"boundary.{kind}"
    path.write_bytes(wide_source(kind, values))
    rows = list(parsers.iter_rows(path, path.name, {}))
    assert len(rows) == 1
    assert [rows[0].values[letter(index)] for index in range(1, 10)] == values


def test_parser_row_budget_includes_formula_text_in_addition_to_values(tmp_path):
    source = io.BytesIO(xlsx_bytes({}))
    rewritten = io.BytesIO()
    expression = "1+" * 14_999 + "1"
    assert len(expression) < CELL_CHARS
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(rewritten, "w", zipfile.ZIP_STORED) as output,
    ):
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                cells = "".join(
                    f'<c r="{letter(index)}2"><f>{expression}</f><v>1</v></c>'
                    for index in range(1, 10)
                )
                content = f'<worksheet xmlns="{MAIN}"><sheetData><row r="2">{cells}</row></sheetData></worksheet>'.encode()
            output.writestr(entry.filename, content)
    path = tmp_path / "formula-row.xlsx"
    path.write_bytes(rewritten.getvalue())
    with pytest.raises(parsers.ParserError) as error:
        list(parsers.iter_rows(path, path.name, {}))
    assert error.value.code == "ROW_LIMIT"


def shared_source(unsafe):
    xml = f'<sst xmlns="{MAIN}"><si><t>000007</t></si></sst>'
    if unsafe:
        xml = (
            '<!DOCTYPE sst [<!ENTITY forbidden "blocked">]>'
            + f'<sst xmlns="{MAIN}"><si><t>&forbidden;</t></si></sst>'
        )
    return xlsx_bytes({}, shared_xml=xml)


def track_temporary_directories(monkeypatch):
    original = parsers.tempfile.TemporaryDirectory
    directories = []

    def tracked(*args, **kwargs):
        requested = kwargs.get("dir", args[2] if len(args) > 2 else None)
        temporary = original(*args, **kwargs)
        directories.append((requested, Path(temporary.name)))
        return temporary

    monkeypatch.setattr(parsers.tempfile, "TemporaryDirectory", tracked)
    return directories


@pytest.mark.parametrize("unsafe", [False, True])
def test_shared_string_spool_trusts_explicit_temp_directory_and_cleans_on_success_or_error(
    tmp_path, monkeypatch, unsafe
):
    trusted, untrusted = tmp_path / "app" / "imports", tmp_path / "client-selected"
    trusted.mkdir(parents=True)
    untrusted.mkdir()
    path = tmp_path / "shared.xlsx"
    path.write_bytes(shared_source(unsafe))
    before = hashlib.sha256(path.read_bytes()).digest()
    directories = track_temporary_directories(monkeypatch)
    if unsafe:
        with pytest.raises(parsers.ParserError) as error:
            list(parsers.iter_rows(path, path.name, {"temp_dir": str(untrusted)}, temp_dir=trusted))
        assert error.value.code == "UNSAFE_XML"
    else:
        assert list(
            parsers.iter_rows(path, path.name, {"temp_dir": str(untrusted)}, temp_dir=trusted)
        )[0].values == {"A": "000007"}
    assert directories
    assert all(
        requested is not None and Path(requested).resolve().is_relative_to(trusted.resolve())
        for requested, _ in directories
    )
    assert all(not directory.exists() for _, directory in directories)
    assert not list(untrusted.iterdir())
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("unsafe", [False, True])
def test_application_parse_places_shared_spool_under_imports_ignoring_profile_temp_directory(
    account, tmp_path, monkeypatch, unsafe
):
    runtime, _, _ = account
    book = make_book(account, text_columns=1)
    outside = tmp_path / "client-parser-temp"
    outside.mkdir()
    directories = track_temporary_directories(monkeypatch)
    stored, imported = parsed(
        account,
        book["id"],
        shared_source(unsafe),
        "shared.xlsx",
        profile={"temp_dir": str(outside)},
        expected="FAILED" if unsafe else "COMPLETED",
    )
    if unsafe:
        assert imported["error_code"] == "UNSAFE_XML"
    trusted = runtime.root.resolve_key("imports").resolve()
    assert directories
    assert all(
        requested is not None and Path(requested).resolve().is_relative_to(trusted)
        for requested, _ in directories
    )
    assert all(not directory.exists() for _, directory in directories)
    assert not list(outside.iterdir())
    with runtime.files.read(stored.id) as source:
        assert hashlib.sha256(source.read()).hexdigest() == stored.sha256


def test_manual_create_and_merged_update_enforce_same_row_budget_atomically(account):
    _, actor, service = account
    book = make_book(account, text_columns=10)
    value = "a" * CELL_CHARS
    with pytest.raises(CoreError) as error:
        service.create_row(actor, book["id"], {f"c{index}": value for index in range(10)}, key())
    assert error.value.code == "ROW_LIMIT"
    row = service.create_row(actor, book["id"], {f"c{index}": value for index in range(6)}, key())
    with pytest.raises(CoreError) as error:
        service.mutate_row(
            actor,
            row["id"],
            row["version"],
            key(),
            values={f"c{index}": value for index in range(6, 10)},
        )
    assert error.value.code == "ROW_LIMIT"
    current = service.list_rows(actor, book["id"])["items"]
    assert len(current) == 1
    assert current[0]["version"] == 1
    assert current[0]["values"]["c6"] is None


def test_staging_budget_checks_merged_edits_and_failed_patch_is_atomic(account):
    runtime, actor, service = account
    book = make_book(account, text_columns=10)
    _, imported = parsed(account, book["id"], wide_source("csv", ["small"] * 10))
    imported = service.mapping(
        actor,
        imported["id"],
        imported["version"],
        {f"c{index}": letter(index + 1) for index in range(10)},
        {},
        key(),
    )
    row = service.staging_page(actor, imported["id"])["items"][0]
    value = "a" * CELL_CHARS
    imported = service.patch_staging(
        actor,
        imported["id"],
        imported["version"],
        [
            {
                "row_id": row["row_id"],
                "expected_version": row["revision"],
                "values": {f"c{index}": value for index in range(6)},
            }
        ],
        key(),
    )
    row = service.staging_page(actor, imported["id"])["items"][0]
    with pytest.raises(CoreError) as error:
        service.patch_staging(
            actor,
            imported["id"],
            imported["version"],
            [
                {
                    "row_id": row["row_id"],
                    "expected_version": row["revision"],
                    "values": {f"c{index}": value for index in range(6, 10)},
                }
            ],
            key(),
        )
    assert error.value.code == "ROW_LIMIT"
    current = service.staging_page(actor, imported["id"])["items"][0]
    assert current["revision"] == row["revision"]
    assert set(current["edited_values"]) == {f"c{index}" for index in range(6)}
    with runtime.reader() as connection:
        assert connection.execute(select(func.count()).select_from(s.patches)).scalar_one() == 1


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_rejected_oversize_first_source_row_is_not_partially_staged(account, kind):
    runtime, _, _ = account
    book = make_book(account, text_columns=10)
    stored, imported = parsed(
        account,
        book["id"],
        wide_source(kind, ["a" * CELL_CHARS] * 10),
        f"wide.{kind}",
        expected="FAILED",
    )
    assert imported["error_code"] == "ROW_LIMIT"
    with runtime.reader() as connection:
        assert (
            connection.execute(
                select(func.count())
                .select_from(s.stage)
                .where(s.stage.c.batch_id == imported["id"])
            ).scalar_one()
            == 0
        )
    with runtime.files.read(stored.id) as source:
        assert hashlib.sha256(source.read()).hexdigest() == stored.sha256


def test_actual_parse_insert_payloads_are_bounded_to_four_mib(account, tmp_path):
    runtime, _, _ = account
    book = make_book(account, text_columns=1)
    path = tmp_path / "large-cells.csv"
    # Distinct deterministic ASCII avoids unrealistic compression assumptions.
    generator = random.Random(42)
    cell = "".join(generator.choices(string.ascii_letters + string.digits, k=CELL_CHARS))
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["body"])
        for _ in range(500):
            writer.writerow([cell])
    payloads = []

    def inspect_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("insert into accounting_staged_rows"):
            records = context.compiled_parameters
            payloads.append((len(records), len(canonical_json(records).encode("utf-8"))))

    event.listen(runtime.database.engine, "before_cursor_execute", inspect_insert)
    try:
        _, imported = parsed(account, book["id"], path)
    finally:
        event.remove(runtime.database.engine, "before_cursor_execute", inspect_insert)
    assert imported["counts"]["source_rows"] == 500
    assert len(payloads) > 1
    assert sum(count for count, _ in payloads) == 500
    assert max(size for _, size in payloads) <= CHUNK_BYTES


def cancellable_workbook(*, row_count=10_000, shared_count=0, hidden=False):
    source = io.BytesIO(xlsx_bytes({}))
    rewritten = io.BytesIO()
    row_xml = "".join(
        f'<row r="{index + 2}" hidden="{int(hidden)}"><c r="A{index + 2}" t="inlineStr"><is><t>synthetic-{index:07d}</t></is></c></row>'
        for index in range(row_count)
    )
    with (
        zipfile.ZipFile(source) as original,
        zipfile.ZipFile(rewritten, "w", zipfile.ZIP_STORED) as output,
    ):
        for entry in original.infolist():
            content = original.read(entry)
            if entry.filename == "xl/worksheets/sheet1.xml":
                content = f'<worksheet xmlns="{MAIN}"><sheetData>{row_xml}</sheetData></worksheet>'.encode()
            output.writestr(entry.filename, content)
        if shared_count:
            strings = "".join(
                f"<si><t>synthetic-shared-{index:07d}</t></si>" for index in range(shared_count)
            )
            output.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">{strings}</sst>')
    return rewritten.getvalue()


def track_zip_reads(monkeypatch):
    original = zipfile.ZipFile.open
    reads, streams, archives = [], [], []

    def tracked(archive, name, *args, **kwargs):
        stream = original(archive, name, *args, **kwargs)
        part = name.filename if isinstance(name, zipfile.ZipInfo) else name
        state = {"part": part, "bytes": 0}
        reads.append(state)
        streams.append(stream)
        archives.append(archive)
        original_read = stream.read

        def read(*read_args, **read_kwargs):
            value = original_read(*read_args, **read_kwargs)
            state["bytes"] += len(value)
            return value

        stream.read = read
        return stream

    monkeypatch.setattr(zipfile.ZipFile, "open", tracked)
    return reads, streams, archives


@pytest.mark.parametrize("entrypoint", ["manifest", "iter_rows_upfront_scan"])
def test_cancellation_interrupts_structural_scan_before_reading_full_worksheet(
    tmp_path, monkeypatch, entrypoint
):
    path = tmp_path / "cancel-scan.xlsx"
    path.write_bytes(cancellable_workbook())
    before = hashlib.sha256(path.read_bytes()).digest()
    with zipfile.ZipFile(path) as archive:
        full_bytes = archive.getinfo("xl/worksheets/sheet1.xml").file_size
    reads, streams, archives = track_zip_reads(monkeypatch)
    interrupted = JobInterrupted()

    def cancel_during_sheet():
        if any(state["part"] == "xl/worksheets/sheet1.xml" and state["bytes"] for state in reads):
            raise interrupted

    with pytest.raises(JobInterrupted) as error:
        if entrypoint == "manifest":
            parsers.manifest(path, path.name, check_cancelled=cancel_during_sheet)
        else:
            next(parsers.iter_rows(path, path.name, {}, check_cancelled=cancel_during_sheet))
    assert error.value is interrupted
    sheet_reads = [state for state in reads if state["part"] == "xl/worksheets/sheet1.xml"]
    assert len(sheet_reads) == 1 and 0 < sheet_reads[0]["bytes"] < full_bytes
    assert all(stream.closed for stream in streams)
    assert all(archive.fp is None for archive in archives)
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_cancellation_interrupts_shared_string_spooling_and_cleans_cache(tmp_path, monkeypatch):
    path = tmp_path / "cancel-strings.xlsx"
    path.write_bytes(cancellable_workbook(row_count=1, shared_count=10_000))
    before = hashlib.sha256(path.read_bytes()).digest()
    trusted = tmp_path / "app-imports"
    trusted.mkdir()
    with zipfile.ZipFile(path) as archive:
        full_bytes = archive.getinfo("xl/sharedStrings.xml").file_size
    directories = track_temporary_directories(monkeypatch)
    reads, streams, archives = track_zip_reads(monkeypatch)
    interrupted = JobInterrupted()

    def cancel_during_strings():
        if any(state["part"] == "xl/sharedStrings.xml" and state["bytes"] for state in reads):
            raise interrupted

    with pytest.raises(JobInterrupted) as error:
        next(
            parsers.iter_rows(
                path, path.name, {}, temp_dir=trusted, check_cancelled=cancel_during_strings
            )
        )
    assert error.value is interrupted
    assert directories and all(not directory.exists() for _, directory in directories)
    assert not list(trusted.iterdir())
    assert (
        0
        < next(state["bytes"] for state in reads if state["part"] == "xl/sharedStrings.xml")
        < full_bytes
    )
    assert all(stream.closed for stream in streams)
    assert all(archive.fp is None for archive in archives)
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("skip_policy", ["before_start", "hidden"])
def test_cancellation_interrupts_xlsx_reread_while_all_rows_are_skipped(
    tmp_path, monkeypatch, skip_policy
):
    path = tmp_path / "cancel-skipped.xlsx"
    path.write_bytes(cancellable_workbook(hidden=skip_policy == "hidden"))
    before = hashlib.sha256(path.read_bytes()).digest()
    trusted = tmp_path / "app-imports"
    trusted.mkdir()
    directories = track_temporary_directories(monkeypatch)
    reads, streams, archives = track_zip_reads(monkeypatch)
    interrupted = JobInterrupted()

    def cancel_during_reread():
        worksheet = [state for state in reads if state["part"] == "xl/worksheets/sheet1.xml"]
        if len(worksheet) == 2 and worksheet[-1]["bytes"]:
            raise interrupted

    profile = {"start_row": 20_000} if skip_policy == "before_start" else {"hidden_rows": "exclude"}
    with pytest.raises(JobInterrupted) as error:
        next(
            parsers.iter_rows(
                path, path.name, profile, temp_dir=trusted, check_cancelled=cancel_during_reread
            )
        )
    assert error.value is interrupted
    worksheet = [state for state in reads if state["part"] == "xl/worksheets/sheet1.xml"]
    assert len(worksheet) == 2
    assert 0 < worksheet[1]["bytes"] < worksheet[0]["bytes"]
    assert directories and all(not directory.exists() for _, directory in directories)
    assert all(stream.closed for stream in streams)
    assert all(archive.fp is None for archive in archives)
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_cancellation_interrupts_csv_records_skipped_before_start_and_ignores_profile_callback(
    tmp_path, monkeypatch
):
    path = tmp_path / "cancel-skipped.csv"
    path.write_text("value\n" + "synthetic\n" * 10_000, encoding="utf-8")
    before = hashlib.sha256(path.read_bytes()).digest()
    original_reader = csv.reader
    consumed = 0

    def observed_reader(*args, **kwargs):
        nonlocal consumed
        for row in original_reader(*args, **kwargs):
            consumed += 1
            yield row

    monkeypatch.setattr(csv, "reader", observed_reader)
    interrupted = JobInterrupted()

    def cancel_after_records():
        if consumed:
            raise interrupted

    with pytest.raises(JobInterrupted) as error:
        next(
            parsers.iter_rows(
                path,
                path.name,
                {"start_row": 20_000, "check_cancelled": "untrusted ignored value"},
                check_cancelled=cancel_after_records,
            )
        )
    assert error.value is interrupted
    assert 0 < consumed <= 1024
    assert hashlib.sha256(path.read_bytes()).digest() == before
