import copy
import hashlib
import io
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import exports, models
from cafe_fin.reporting.migrations import REPORTS
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.sources import BridgeSources, SourceBundle, build_snapshot
from conftest import preview_command, saved
from openpyxl import load_workbook
from pydantic import ValidationError
from pypdf import PdfReader
from sqlalchemy.exc import IntegrityError


def test_vietnam_month_boundary_exact_money_missing_mapping_and_no_cross_book_sum(env):
    row = saved(env)
    snapshot = row["snapshot"]
    assert snapshot["period"]["from"] == "2026-10-30T17:00:00+00:00"
    assert snapshot["period"]["to"] == "2026-11-01T17:00:00+00:00"
    assert snapshot["sources"]["books"][0]["metrics"][0]["amount_vnd"] == env.source.amount
    assert snapshot["sources"]["books"][1]["metrics"] == []
    assert snapshot["production"] is None and snapshot["hold"] is None
    assert "MONEY_DATA_INCOMPLETE" in snapshot["warnings"]
    assert "total_money" not in snapshot
    assert snapshot["sources"]["inventory"]["items"][0]["closing_kg"] == "9.999"


def test_preview_replay_version_reason_snapshot_immutable_and_restart(env):
    original = saved(env)
    before_calls = env.source.calls
    env.source.closing = "999.000"
    replay = env.service.preview(env.actor, preview_command())
    assert replay["id"] == original["id"]
    assert env.source.calls == before_calls
    with pytest.raises(CoreError, match="IDEMPOTENCY_CONFLICT"):
        env.service.preview(env.actor, preview_command(reason="changed payload"))
    with pytest.raises(CoreError, match="REPORT_REVISION_REASON_REQUIRED"):
        env.service.preview(env.actor, preview_command("new"))
    newer = saved(env, "new", "Bổ sung nghiệp vụ")
    assert newer["version"] == 2 and newer["sha256"] != original["sha256"]
    assert env.service.detail(original["id"])["snapshot"] == original["snapshot"]
    with pytest.raises(IntegrityError):
        env.runtime.writer.run(
            lambda conn: conn.execute(REPORTS.update().values(snapshot_json="{}"))
        )
    with pytest.raises(IntegrityError):
        env.runtime.writer.run(lambda conn: conn.execute(REPORTS.delete()))
    env.runtime.close()
    reopened = Runtime(env.root, modules=env.registry)
    try:
        service = ReportingService(reopened, source=env.source)
        assert service.detail(original["id"])["sha256"] == original["sha256"]
        assert service.detail(newer["id"])["version"] == 2
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "first,last",
    [
        ("2026-11-02", "2026-11-01"),
        ("2026-02-30", "2026-03-01"),
        ("2025-01-01", "2026-11-01"),
        ("2026-1-01", "2026-01-02"),
    ],
)
def test_invalid_periods_are_rejected(first, last):
    with pytest.raises(ValidationError):
        models.Preview(request_key="x", from_on=first, through_on=last)


def test_source_period_cutoff_book_identity_duplicates_are_checked(env):
    captured = env.source.capture

    def mismatched(first, last, book_ids, cutoff):
        value = captured(first, last, book_ids, cutoff)
        return SourceBundle(
            value.inventory.model_copy(update={"through_on": date(2026, 11, 2)}), value.books
        )

    env.source.capture = mismatched
    with pytest.raises(CoreError, match="REPORT_SOURCE_MISMATCH"):
        env.service.preview(env.actor, preview_command())

    def duplicate(first, last, book_ids, cutoff):
        value = captured(first, last, book_ids, cutoff)
        return SourceBundle(
            value.inventory.model_copy(update={"items": value.inventory.items * 2}), value.books
        )

    env.source.capture = duplicate
    with pytest.raises(CoreError, match="REPORT_SOURCE_DUPLICATE"):
        env.service.preview(env.actor, preview_command())


def test_summary_redacts_all_arbitrary_source_text_and_never_infers_invoice_cash(env):
    row = saved(env)
    text = env.service.detail(row["id"])["short_message"]
    assert env.source.malicious not in text
    for forbidden in ("CCCD", "99999", "localhost", "C:/", "invoice", "999999.99"):
        assert forbidden not in text
    assert "123456789012345678901234567890.01" not in text  # raw key income is not typed meaning
    assert "Sổ 1: chưa đủ dữ liệu" in text
    assert "Sổ 2: chưa đủ dữ liệu" in text
    assert "Tồn tổng: 9.999 kg" in text


@pytest.mark.parametrize("format", ["pdf", "xlsx", "txt"])
def test_exports_real_filestore_vietnamese_exact_deterministic_and_summary_only(env, format):
    row = saved(env)
    result = env.service.export(
        env.actor, row["id"], models.Export(request_key="export", format=format)
    )
    assert env.runtime.files.get(result["file_id"]).category == "reports"
    with env.runtime.files.read(result["file_id"]) as source:
        content = source.read()
    assert hashlib.sha256(content).hexdigest() == result["sha256"]
    assert (
        env.service.export(env.actor, row["id"], models.Export(request_key="export", format=format))
        == result
    )
    with env.runtime.render_lock:
        a, _ = exports.render(row["snapshot"], row["version"], row["sha256"], format)
        time.sleep(1.05)  # crosses document metadata second boundary
        b, _ = exports.render(row["snapshot"], row["version"], row["sha256"], format)
    assert a == b == content
    if format == "pdf":
        extracted = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
        assert "Báo cáo tổng hợp cà phê" in extracted
        assert env.source.amount not in extracted.replace("\n", "")
    elif format == "xlsx":
        workbook = load_workbook(io.BytesIO(content))
        cells = list(workbook.active)
        extracted = "\n".join(str(cell.value) for line in cells for cell in line if cell.value)
        assert env.source.amount not in extracted
        assert all(cell.data_type == "s" for line in cells for cell in line if cell.value)
    else:
        extracted = content.decode()
    assert env.source.malicious not in extracted
    assert "999999.99" not in extracted  # invoice is not cash


def test_concurrent_exports_and_paging_sorting_filtering(env):
    first = saved(env)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda n: env.service.export(
                    env.actor, first["id"], models.Export(request_key=f"export-{n}", format="pdf")
                ),
                range(4),
            )
        )
    assert len({r["id"] for r in results}) == 1
    saved(env, "revision", "Bổ sung")
    env.service.preview(env.actor, preview_command("pending", "Xem lại"))
    page = env.service.list("reports", page=1, page_size=1, state="SAVED", sort="version:desc")
    assert page["total"] == 2 and page["items"][0]["version"] == 2
    assert "snapshot" not in page["items"][0]
    assert env.service.list("reports", search="%")["total"] == 0
    with pytest.raises(CoreError, match="REPORT_FILTER_INVALID"):
        env.service.list("reports", sort="snapshot_json:asc")


def test_cutoff_only_bridge_reports_consistency_limit(env):
    class Records:
        def inventory_summary(self, first, last, *, cutoff):
            return env.source.capture(first, last, (), cutoff).inventory

    class Accounting:
        def book_summary(self, book, first, last, *, cutoff):
            return env.source.capture(first, last, (book,), cutoff).books[0]

    snapshot = build_snapshot(
        BridgeSources(Records(), Accounting()), preview_command(), datetime.now(timezone.utc)
    )
    assert "CROSS_SOURCE_SNAPSHOT_NOT_ATTESTED" in snapshot["warnings"]


def test_unconfigured_sources_fail_explicitly_but_saved_snapshots_remain_readable(env):
    row = saved(env)
    unbound = ReportingService(env.runtime)
    with pytest.raises(CoreError, match="REPORT_SOURCES_UNCONFIGURED"):
        unbound.preview(env.actor, preview_command("new"))
    assert unbound.detail(row["id"])["sha256"] == row["sha256"]


def test_summary_consumer_requires_explicit_meaning_and_preserves_exact_numbers(env):
    # Consumer compatibility fixture for coordinator's additive typed metadata.
    # This does not claim the old core DTO or real accounting provider exports it.
    row = saved(env)
    snapshot = copy.deepcopy(row["snapshot"])
    snapshot["sources"]["books"][0]["metrics"][0]["meaning"] = "cash_receipts"
    message = exports.short_message(snapshot, row["version"], row["sha256"])
    assert env.source.amount in message and "Tổng thu tiền" in message
    assert "999999.99" not in message  # invoice key still has no explicit meaning
    for format in ("pdf", "xlsx"):
        with env.runtime.render_lock:
            content, _ = exports.render(snapshot, row["version"], row["sha256"], format)
        if format == "pdf":
            text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(content)).pages).replace(
                "\n", ""
            )
        else:
            sheet = load_workbook(io.BytesIO(content)).active
            text = "".join(str(cell.value) for line in sheet for cell in line if cell.value)
        assert env.source.amount in text


def test_movement_consumer_displays_components_without_counting_them_as_extra_stock(env):
    row = saved(env)
    snapshot = copy.deepcopy(row["snapshot"])
    item = snapshot["sources"]["inventory"]["items"][0]
    movement = {
        "warehouse_id": item["warehouse_id"],
        "product_id": item["product_id"],
        "purchased_kg": "7.001",
        "sold_kg": "0.001",
        "production_input_kg": "0.001",
        "production_output_kg": "1.000",
        "transfer_in_kg": "1.000",
        "transfer_out_kg": "0.000",
        "adjustment_in_kg": "1.000",
        "adjustment_out_kg": "0.000",
    }
    snapshot["sources"]["inventory"]["movement_breakdown"] = [movement]
    snapshot["production"] = [movement]
    text = exports.short_message(snapshot, row["version"], row["sha256"])
    assert "Mua: 7.001 kg" in text and "Vào sản xuất: 0.001 kg" in text
    assert "Tồn tổng: 9.999 kg" in text and "Nhập tổng: 10.001 kg" in text
    rows = exports.summary_rows(snapshot)
    assert any(label == "Mua (kg)" and value == "7.001" for _, label, value in rows)


def test_atomic_adapter_uses_real_sqlite_read_snapshot_across_public_helpers(env):
    from cafe_fin.core.contracts import BookSummaryDTO, MappedBookMetricDTO
    from cafe_fin.reporting.sources import AtomicSources
    from sqlalchemy import Column, MetaData, String, Table, select

    table = Table("synthetic_coherent_source", MetaData(), Column("value", String))
    env.runtime.writer.run(lambda conn: table.create(conn))
    env.runtime.writer.run(lambda conn: conn.execute(table.insert().values(value="10.01")))

    def inventory(conn, first, last, *, cutoff):
        assert conn.execute(select(table.c.value)).scalar_one() == "10.01"
        # A concurrent user edit is committed between the two owner helpers.
        env.runtime.writer.run(lambda write: write.execute(table.update().values(value="20.02")))
        return env.source.capture(first, last, (), cutoff).inventory

    def book(conn, book_id, first, last, *, cutoff):
        amount = conn.execute(select(table.c.value)).scalar_one()
        return BookSummaryDTO(
            book_id=book_id,
            from_on=first,
            through_on=last,
            cutoff=cutoff,
            has_valid_money_mapping=True,
            metrics=(MappedBookMetricDTO(key="raw", amount_vnd=amount, mapping_revision=1),),
        )

    source = AtomicSources(env.runtime.reader, inventory, book)
    period = preview_command().model_copy(update={"book_ids": ["cash"]})
    snapshot = build_snapshot(source, period, datetime.now(timezone.utc))
    assert snapshot["sources"]["books"][0]["metrics"][0]["amount_vnd"] == "10.01"
    assert "CROSS_SOURCE_SNAPSHOT_NOT_ATTESTED" not in snapshot["warnings"]
    with env.runtime.reader() as conn:
        assert conn.execute(select(table.c.value)).scalar_one() == "20.02"
