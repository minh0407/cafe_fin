"""Core import + reporting with a synthetic provider; not real accounting acceptance."""

from datetime import datetime, timezone

from cafe_fin.core.contracts import BookSummaryDTO, MappedBookMetricDTO
from cafe_fin.core.imports import ImportAttemptService, ManifestRow, visibility_predicate
from cafe_fin.reporting.exports import decimal_text, scaled
from cafe_fin.reporting.sources import BridgeSources, build_snapshot
from sqlalchemy import Column, MetaData, String, Table, select

from tests.reporting.conftest import preview_command


def test_reporting_provider_hides_pending_publishes_once_and_freezes_attempt_inputs(env):
    table = Table(
        "synthetic_reporting_source",
        MetaData(),
        Column("id", String, primary_key=True),
        Column("import_attempt_id", String),
        Column("amount", String),
    )
    env.runtime.writer.run(lambda conn: table.create(conn))
    imports = ImportAttemptService()
    pins = {
        "staging_revision": 1,
        "mapping_revision": 1,
        "decision_revision": 1,
        "validation_token": "synthetic",
        "mapping_snapshot": {"amount": "C"},
        "duplicate_decisions": {},
        "mode": "valid_rows_only",
    }

    class Records:
        def inventory_summary(self, first, last, *, cutoff):
            return env.source.capture(first, last, (), cutoff).inventory

    class Accounting:
        def book_summary(self, book_id, first, last, *, cutoff):
            with env.runtime.reader() as conn:
                values = conn.execute(
                    select(table.c.amount).where(visibility_predicate(table.c.import_attempt_id))
                ).scalars()
                total = sum(scaled(value, 2) for value in values)
            return BookSummaryDTO(
                book_id=book_id,
                from_on=first,
                through_on=last,
                cutoff=cutoff,
                has_valid_money_mapping=True,
                metrics=(
                    MappedBookMetricDTO(
                        key="cash_receipts", amount_vnd=decimal_text(total, 2), mapping_revision=1
                    ),
                ),
            )

    source = BridgeSources(Records(), Accounting())
    period = preview_command().model_copy(update={"book_ids": ["cash"]})

    def total():
        snapshot = build_snapshot(source, period, datetime.now(timezone.utc))
        return snapshot["sources"]["books"][0]["metrics"][0]["amount_vnd"]

    def prepare(source_row, amount):
        manifest = env.runtime.writer.run(
            lambda conn: imports.create_manifest(
                conn, job_id="same-job", pins=pins, expected_count=1
            )
        )
        staging = {
            "source_sheet": "Sổ tổng hợp",
            "source_row": source_row,
            "revision": 1,
            "raw_values": {"C": amount},
            "edited_values": {},
            "typed_values": {"amount": amount},
        }
        env.runtime.writer.run(
            lambda conn: imports.append_manifest_chunk(
                conn, manifest, expected_start=0, rows=[ManifestRow(str(source_row), staging)]
            )
        )
        digest = env.runtime.writer.run(lambda conn: imports.seal_manifest(conn, manifest))
        attempt = env.runtime.writer.run(
            lambda conn: imports.create_attempt(conn, manifest, fingerprint=digest)
        )
        # User edits staging/mapping after confirmation; worker must keep its frozen copy.
        staging["typed_values"]["amount"] = "999999.99"
        pins["mapping_snapshot"]["amount"] = "changed-after-confirm"
        return attempt

    def write(conn, attempt, rows):
        for row in rows:
            conn.execute(
                table.insert().values(
                    id=row.target_id,
                    import_attempt_id=attempt,
                    amount=row.snapshot["typed_values"]["amount"],
                )
            )

    first = prepare(1, "120.01")

    def chunk(attempt):
        return env.runtime.writer.run(
            lambda conn: imports.commit_chunk(
                conn, attempt, chunk_id="chunk", start=0, count=1, write_pending=write
            )
        )

    assert total() == "0.00"
    chunk(first)
    assert total() == "0.00"  # committed pending is invisible
    chunk(first)  # receipt replay, not another insert
    env.runtime.writer.run(lambda conn: imports.publish(conn, first))
    assert total() == "120.01"
    second = prepare(2, "30.02")  # formerly invalid source row fixed; do not select old row again
    chunk(second)
    assert total() == "120.01"
    env.runtime.writer.run(lambda conn: imports.publish(conn, second))
    assert total() == "150.03"
    chunk(second)
    assert total() == "150.03"
