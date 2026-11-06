"""Inclusive business dates across both public helpers; half-open UTC instants."""

import copy
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from cafe_fin.core.contracts import (
    BookSummaryDTO,
    InventoryLineDTO,
    InventorySummaryDTO,
    MappedBookMetricDTO,
)
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.reporting import exports, models
from cafe_fin.reporting.migrations import OUTBOX, REPORTS
from cafe_fin.reporting.models import DATE_RANGE_CONTRACT
from cafe_fin.reporting.sender import dispatch_one
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.sources import AtomicSources, BridgeSources, SourceBundle, build_snapshot
from conftest import configure, saved
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, select


def calendar_source(env):
    table = Table(
        "synthetic_reporting_calendar",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("instant_utc", String),
        Column("business_on", String),
        Column("kg", String),
        Column("money", String),
    )
    env.runtime.writer.run(lambda conn: table.create(conn))
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    entries = [
        ("before", "2026-10-31T16:59:59.999999+00:00", "1.000", "10.01"),
        ("first", "2026-10-31T17:00:00+00:00", "2.000", "20.02"),
        ("last", "2026-11-01T16:59:59.999999+00:00", "3.000", "30.03"),
        ("next", "2026-11-01T17:00:00+00:00", "4.000", "40.04"),
    ]
    env.runtime.writer.run(
        lambda conn: conn.execute(
            table.insert(),
            [
                dict(
                    id=identity,
                    instant_utc=instant,
                    business_on=datetime.fromisoformat(instant).astimezone(zone).date().isoformat(),
                    kg=kg,
                    money=money,
                )
                for identity, instant, kg, money in entries
            ],
        )
    )
    calls = []

    def inventory(conn, first, last, *, cutoff):
        calls.append(("inventory", first, last))
        # Independent provider implementation: inclusive dates -> next midnight,
        # not a consumer-supplied shifted date masquerading as through_on.
        start = datetime.combine(first, time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(last + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        values = conn.execute(
            select(table.c.kg).where(
                table.c.instant_utc >= start.isoformat(), table.c.instant_utc < end.isoformat()
            )
        ).scalars()
        received = sum(exports.scaled(x, 3) for x in values)
        prior = conn.execute(
            select(table.c.kg).where(table.c.instant_utc < start.isoformat())
        ).scalars()
        opening = sum(exports.scaled(x, 3) for x in prior)
        return InventorySummaryDTO(
            from_on=first,
            through_on=last,
            cutoff=cutoff,
            items=(
                InventoryLineDTO(
                    product_id="coffee",
                    warehouse_id="demo",
                    opening_kg=exports.decimal_text(opening, 3),
                    received_kg=exports.decimal_text(received, 3),
                    issued_kg="0.000",
                    closing_kg=exports.decimal_text(opening + received, 3),
                ),
            ),
        )

    def book(conn, book_id, first, last, *, cutoff):
        calls.append(("book", first, last))
        values = conn.execute(
            select(table.c.money).where(
                table.c.business_on >= first.isoformat(), table.c.business_on <= last.isoformat()
            )
        ).scalars()
        total = sum(exports.scaled(x, 2) for x in values)
        return BookSummaryDTO(
            book_id=book_id,
            from_on=first,
            through_on=last,
            cutoff=cutoff,
            has_valid_money_mapping=True,
            metrics=(
                MappedBookMetricDTO(
                    key="cash",
                    meaning="cash_receipts",
                    mapping_revision=1,
                    amount_vnd=exports.decimal_text(total, 2),
                ),
            ),
        )

    return AtomicSources(env.runtime.reader, inventory, book), calls


@pytest.mark.parametrize(
    "first,last,kg,money,start,end",
    [
        (
            "2026-11-01",
            "2026-11-01",
            "5.000",
            "50.05",
            "2026-10-31T17:00:00+00:00",
            "2026-11-01T17:00:00+00:00",
        ),
        (
            "2026-10-31",
            "2026-11-01",
            "6.000",
            "60.06",
            "2026-10-30T17:00:00+00:00",
            "2026-11-01T17:00:00+00:00",
        ),
        (
            "2026-11-02",
            "2026-11-02",
            "4.000",
            "40.04",
            "2026-11-01T17:00:00+00:00",
            "2026-11-02T17:00:00+00:00",
        ),
    ],
)
def test_inclusive_last_day_next_day_excluded_and_exact_vietnam_utc(
    env, first, last, kg, money, start, end
):
    source, calls = calendar_source(env)
    service = ReportingService(env.runtime, source=source)
    command = models.Preview(
        request_key="calendar", from_on=first, through_on=last, book_ids=["cash"]
    )
    report = service.preview(env.actor, command)
    period, data = report["snapshot"]["period"], report["snapshot"]["sources"]
    assert period["date_range_contract"] == DATE_RANGE_CONTRACT
    assert period["timestamp_range_contract"] == "half_open_utc"
    assert period["from"] == start and period["to"] == end
    assert data["inventory"]["items"][0]["received_kg"] == kg
    opening, closing = {
        "2026-10-31": ("0.000", "6.000"),
        "2026-11-01": ("1.000", "6.000"),
        "2026-11-02": ("6.000", "10.000"),
    }[first]
    assert data["inventory"]["items"][0]["opening_kg"] == opening
    assert data["inventory"]["items"][0]["closing_kg"] == closing
    assert data["books"][0]["metrics"][0]["amount_vnd"] == money
    assert calls == [
        ("inventory", date.fromisoformat(first), date.fromisoformat(last)),
        ("book", date.fromisoformat(first), date.fromisoformat(last)),
    ]
    assert report["snapshot"]["schema_version"] == 2
    assert f"{first} đến hết {last}" in exports.period_text(report["snapshot"])


def test_period_equal_dates_valid_and_provider_cannot_echo_exclusive_end(env):
    period = models.Period(from_on="2026-11-01", through_on="2026-11-01")
    assert (period.utc_bounds()[1] - period.utc_bounds()[0]).days == 1
    with pytest.raises(ValidationError):
        models.Period(from_on="2026-11-02", through_on="2026-11-01")
    capture = env.source.capture

    def shifted(first, last, book_ids, cutoff):
        bundle = capture(first, last, book_ids, cutoff)
        book = bundle.books[0].model_copy(update={"through_on": last + timedelta(days=1)})
        return SourceBundle(bundle.inventory, (book,))

    env.source.capture = shifted
    with pytest.raises(CoreError, match="REPORT_SOURCE_MISMATCH"):
        build_snapshot(
            env.source,
            models.Period(from_on="2026-11-01", through_on="2026-11-01", book_ids=["cash"]),
            datetime.now(timezone.utc),
        )


def test_bridge_adapter_forwards_single_day_without_adding_day(env):
    calls = []

    class Records:
        def inventory_summary(self, first, last, *, cutoff):
            calls.append((first, last))
            return env.source.capture(first, last, (), cutoff).inventory

    class Accounting:
        def book_summary(self, book_id, first, last, *, cutoff):
            calls.append((first, last))
            return env.source.capture(first, last, (book_id,), cutoff).books[0]

    day = date(2026, 11, 1)
    build_snapshot(
        BridgeSources(Records(), Accounting()),
        models.Period(from_on=day.isoformat(), through_on=day.isoformat(), book_ids=["cash"]),
        datetime.now(timezone.utc),
    )
    assert calls == [(day, day), (day, day)]


def test_scheduler_uses_included_end_day_no_next_day_shift(env):
    configure(env)
    report = saved(env, first="2026-11-01", last="2026-11-01")
    assert env.service.catch_up(datetime(2026, 11, 1, 10, 59, 59, tzinfo=timezone.utc)) == 0
    assert env.service.catch_up(datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)) == 1
    assert env.service.catch_up(datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)) == 0
    assert env.service.list("deliveries")["items"][0]["report_id"] == report["id"]


def test_unmarked_legacy_snapshot_is_immutable_not_guessed_or_scheduled(env):
    configure(env)
    current = saved(env, first="2026-11-01", last="2026-11-01")
    with env.runtime.reader() as conn:
        legacy = dict(
            conn.execute(select(REPORTS).where(REPORTS.c.id == current["id"])).mappings().one()
        )
    snapshot = copy.deepcopy(current["snapshot"])
    snapshot["schema_version"] = 1
    snapshot["period"].pop("date_range_contract")
    snapshot["period"].pop("timestamp_range_contract")
    encoded = canonical_json(snapshot)
    legacy.update(
        id=str(uuid4()),
        series_key="legacy-series",
        command_key="legacy-command",
        snapshot_json=encoded,
        sha256=hashlib.sha256(encoded.encode()).hexdigest(),
    )
    env.runtime.writer.run(lambda conn: conn.execute(REPORTS.insert().values(**legacy)))
    assert "kỳ cũ chưa định danh" in env.service.detail(legacy["id"])["short_message"]
    assert "đến hết" not in exports.period_text(snapshot)
    with pytest.raises(CoreError, match="REPORT_PERIOD_CONTRACT_REQUIRED"):
        env.service.enqueue(env.actor, legacy["id"], models.Enqueue(request_key="legacy-queue"))
    assert env.service.catch_up(datetime(2026, 11, 2, 11, 0, tzinfo=timezone.utc)) == 1
    assert env.service.list("deliveries")["items"][0]["report_id"] == current["id"]
    assert env.service.detail(legacy["id"])["sha256"] == legacy["sha256"]
    assert env.service.detail(legacy["id"])["snapshot"] == snapshot


def test_legacy_outbound_payload_is_blocked_before_any_transport(env):
    configure(env)
    report = saved(env)
    row = env.service.enqueue(env.actor, report["id"], models.Enqueue(request_key="current-queue"))
    with env.runtime.reader() as conn:
        legacy = dict(conn.execute(select(OUTBOX).where(OUTBOX.c.id == row["id"])).mappings().one())
    legacy.update(
        id=str(uuid4()),
        destination="legacy-group",
        payload_json=json.dumps({"text": "Legacy text"}),
        created_at="2000-01-01T00:00:00Z",
    )
    env.runtime.writer.run(lambda conn: conn.execute(OUTBOX.insert().values(**legacy)))
    result = dispatch_one(env.service)
    assert result["id"] == legacy["id"] and result["state"] == "FAILED"
    assert result["error_code"] == "REPORT_PERIOD_CONTRACT_REQUIRED"
    assert not env.transport.texts and env.transport.refreshes == 0
