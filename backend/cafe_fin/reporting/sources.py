"""Public DTO adapters only. No ORM access, inferred cash or inventory writes."""

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import Connection

from cafe_fin.core.contracts import (
    CONTRACT_VERSION,
    AccountingReadBridge,
    BookSummaryDTO,
    InventorySummaryDTO,
    RecordsReadBridge,
)
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError

from .models import DATE_RANGE_CONTRACT

NOTICE = "Chỉ tổng hợp dữ liệu đã nhập; không phải báo cáo tài chính pháp định."


@dataclass(frozen=True)
class SourceBundle:
    inventory: InventorySummaryDTO
    books: tuple[BookSummaryDTO, ...]
    # Trusted provider attests that all DTOs came from one read snapshot.
    consistency: str = "cutoff_only"


class ReportSource(Protocol):
    """first <= business_date <= last; cutoff is independent of date membership."""

    def capture(
        self, first: date, last: date, book_ids: tuple[str, ...], cutoff: datetime
    ) -> SourceBundle: ...


class InventoryConnectionReader(Protocol):
    """Connection-bound public inventory summary; last is included."""

    def __call__(
        self, conn: Connection, first: date, last: date, *, cutoff: datetime
    ) -> InventorySummaryDTO: ...


class BookConnectionReader(Protocol):
    """Connection-bound public book summary; last is included."""

    def __call__(
        self, conn: Connection, book_id: str, first: date, last: date, *, cutoff: datetime
    ) -> BookSummaryDTO: ...


class BridgeSources:
    """Convenience adapter; cutoff alone is not a cross-provider atomic snapshot."""

    def __init__(self, records: RecordsReadBridge, accounting: AccountingReadBridge):
        self.records, self.accounting = records, accounting

    def capture(self, first, last, book_ids, cutoff):
        return SourceBundle(
            self.records.inventory_summary(first, last, cutoff=cutoff),
            tuple(self.accounting.book_summary(x, first, last, cutoff=cutoff) for x in book_ids),
        )


class AtomicSources:
    """Bind owner-supplied public connection-aware helpers to one real read snapshot.

    SQLite's legacy transaction mode does not BEGIN for SELECT. An explicit
    read-only BEGIN is necessary even when SQLAlchemy shows logical autobegin.
    Consumers never access either owner's tables or private ORM here.
    """

    def __init__(
        self,
        reader: Callable[[], AbstractContextManager[Connection]],
        inventory_summary: InventoryConnectionReader,
        book_summary: BookConnectionReader,
    ):
        self.reader, self.inventory_summary, self.book_summary = (
            reader,
            inventory_summary,
            book_summary,
        )

    def capture(self, first, last, book_ids, cutoff):
        with self.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            inventory = self.inventory_summary(conn, first, last, cutoff=cutoff)
            books = tuple(
                self.book_summary(conn, book_id, first, last, cutoff=cutoff) for book_id in book_ids
            )
            return SourceBundle(inventory, books, consistency="atomic_read_snapshot")


class UnboundSources:
    def capture(self, *args):
        raise CoreError("REPORT_SOURCES_UNCONFIGURED", "Nguồn báo cáo chưa được kết nối.", 503)


def build_snapshot(source: ReportSource, period, cutoff: datetime) -> dict:
    first, last = period.business_dates()
    bundle = source.capture(first, last, tuple(period.book_ids), cutoff)
    inventory = bundle.inventory
    all_dtos = (inventory, *bundle.books)
    if (
        any(x.from_on != first or x.through_on != last or x.cutoff != cutoff for x in all_dtos)
        or sorted(x.book_id for x in bundle.books) != period.book_ids
    ):
        raise CoreError(
            "REPORT_SOURCE_MISMATCH", "Nguồn trả sai kỳ, cutoff hoặc danh sách sổ.", 409
        )
    keys = [(x.warehouse_id, x.product_id) for x in inventory.items]
    if len(keys) != len(set(keys)):
        raise CoreError("REPORT_SOURCE_DUPLICATE", "Nguồn tồn kho trả trùng nhóm hàng/kho.", 409)
    books = []
    for book in sorted(bundle.books, key=lambda x: x.book_id):
        metric_keys = [m.key for m in book.metrics]
        if len(metric_keys) != len(set(metric_keys)):
            raise CoreError("REPORT_SOURCE_DUPLICATE", "Sổ trả trùng chỉ tiêu tiền.", 409)
        books.append(book.model_dump(mode="json"))
    start, end = period.utc_bounds()
    sources = {
        "inventory": inventory.model_dump(mode="json"),
        "books": books,
    }
    inventory_data = sources["inventory"]
    breakdown = inventory_data.get("movement_breakdown")
    flags = ["HOLD_BREAKDOWN_UNAVAILABLE"]
    if breakdown is None:
        flags.append("PRODUCTION_BREAKDOWN_UNAVAILABLE")
    if any(
        metric.get("meaning") in (None, "other") for book in books for metric in book["metrics"]
    ):
        flags.append("UNINTERPRETED_MONEY_METRICS")
    for book in books:
        meanings = {metric.get("meaning") for metric in book["metrics"]}
        if book["has_valid_money_mapping"] and not {"cash_receipts", "cash_payments"}.issubset(
            meanings
        ):
            flags.append("MONEY_TOTALS_PARTIAL")
    if bundle.consistency != "atomic_read_snapshot":
        flags.append("CROSS_SOURCE_SNAPSHOT_NOT_ATTESTED")
    if not inventory.items:
        flags.append("NO_ENTERED_INVENTORY")
    if not books:
        flags.append("NO_BOOKS_SELECTED")
    if any(not b["has_valid_money_mapping"] or not b["metrics"] for b in books):
        flags.append("MONEY_DATA_INCOMPLETE")
    # Keep owner flags local; arbitrary provider strings NEVER enter outbound payloads.
    flags.extend(inventory.validation_flags)
    for book in bundle.books:
        flags.extend(book.validation_flags)
    return {
        "schema_version": 2,
        "bridge_contract_version": CONTRACT_VERSION,
        "coverage": "entered_records_only",
        "notice": NOTICE,
        "period": {
            "date_range_contract": DATE_RANGE_CONTRACT,
            "timestamp_range_contract": "half_open_utc",
            "from_on": period.from_on,
            "through_on": period.through_on,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "timezone": "Asia/Ho_Chi_Minh",
        },
        "cutoff": cutoff.isoformat(),
        "sources": sources,
        "source_sha256": hashlib.sha256(canonical_json(sources).encode()).hexdigest(),
        "consistency": bundle.consistency,
        "production": breakdown,
        "hold": None,
        # No combined money total: books can legitimately overlap and invoice != cash.
        "warnings": sorted(set(flags)),
    }
