import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest
from cafe_fin.core.contracts import (
    BookSummaryDTO,
    ImportCountsDTO,
    MappedBookMetricDTO,
    PartyDTO,
    WeightLineInput,
)
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.imports import (
    MIGRATIONS,
    ImportAttemptService,
    ManifestRow,
    attempts,
    claims,
    manifest_rows,
    manifests,
    receipts,
    visibility_predicate,
)
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, String, Table, Text, func, insert, select, update
from sqlalchemy.exc import IntegrityError

demo = Table(
    "example_pending_rows",
    MetaData(),
    Column("id", String, primary_key=True),
    Column("import_attempt_id", String),
    Column("payload", Text, nullable=False),
)
PINS = {
    "staging_revision": 1,
    "mapping_revision": 1,
    "decision_revision": 1,
    "validation_token": "synthetic-server-validation",
    "mapping_snapshot": {"amount": "C"},
    "duplicate_decisions": {},
    "mode": "valid_rows_only",
}


@pytest.fixture
def runtime(tmp_path):
    database = Database(tmp_path / "imports.sqlite3")
    database.migrate(MIGRATIONS)
    writer = WriteCoordinator(database)
    writer.run(lambda conn: demo.create(conn))
    yield database, writer, ImportAttemptService()
    writer.close()
    database.close()


def row(identity, value="100.01"):
    return ManifestRow(
        identity,
        {
            "source_sheet": "Sổ cà phê",
            "source_row": int(identity),
            "revision": 1,
            "raw_values": {"C": value},
            "edited_values": {},
            "typed_values": {"amount": value},
        },
    )


def prepare(writer, service, rows, *, job="job-1"):
    identity = writer.run(
        lambda conn: service.create_manifest(conn, job_id=job, pins=PINS, expected_count=len(rows))
    )
    if rows:
        writer.run(
            lambda conn: service.append_manifest_chunk(conn, identity, expected_start=0, rows=rows)
        )
    digest = writer.run(lambda conn: service.seal_manifest(conn, identity))
    attempt = writer.run(lambda conn: service.create_attempt(conn, identity, fingerprint=digest))
    return identity, attempt


def write_pending(conn, attempt_id, rows):
    conn.execute(
        insert(demo),
        [
            dict(
                id=row.target_id,
                import_attempt_id=attempt_id,
                payload=json.dumps(row.snapshot, ensure_ascii=False),
            )
            for row in rows
        ],
    )


def visible(conn):
    return list(
        conn.execute(select(demo).where(visibility_predicate(demo.c.import_attempt_id))).mappings()
    )


def test_snapshot_is_deep_persisted_and_db_immutable(runtime):
    database, writer, service = runtime
    original = row("1")
    manifest, _ = prepare(writer, service, [original])
    original.snapshot["typed_values"]["amount"] = "999.99"
    with database.read() as conn:
        snapshot = conn.execute(select(manifest_rows.c.snapshot_json)).scalar_one()
        assert json.loads(snapshot)["typed_values"]["amount"] == "100.01"
    for statement in (
        update(manifests).where(manifests.c.id == manifest).values(pins_json="{}"),
        update(manifest_rows).values(snapshot_json="{}"),
        insert(manifest_rows).values(
            manifest_id=manifest, ordinal=99, source_row_id="99", snapshot_json="{}", row_hash="bad"
        ),
    ):
        with pytest.raises(IntegrityError, match="immutable import snapshot"):
            writer.run(lambda conn: conn.execute(statement))


def test_pending_hidden_from_list_detail_count_and_update_until_atomic_publish(runtime):
    database, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1"), row("2")])
    ids = writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="chunk-1", start=0, count=1, write_pending=write_pending
        )
    )
    with database.read() as conn:
        assert visible(conn) == []
        assert (
            conn.execute(
                select(func.count())
                .select_from(demo)
                .where(visibility_predicate(demo.c.import_attempt_id))
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                select(demo).where(
                    demo.c.id == ids[0], visibility_predicate(demo.c.import_attempt_id)
                )
            ).first()
            is None
        )
        assert service.status(conn, attempt)["pending"] == 1
        assert service.status(conn, attempt)["published_rows"] == 0
    changed = writer.run(
        lambda conn: conn.execute(
            update(demo)
            .where(demo.c.id == ids[0], visibility_predicate(demo.c.import_attempt_id))
            .values(payload="{}")
        )
    ).rowcount
    assert changed == 0
    with pytest.raises(CoreError, match="IMPORT_ATTEMPT_INCOMPLETE"):
        writer.run(lambda conn: service.publish(conn, attempt))
    writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="chunk-2", start=1, count=1, write_pending=write_pending
        )
    )
    with database.read() as conn:
        assert visible(conn) == []
    result = writer.run(lambda conn: service.publish(conn, attempt))
    assert result["published_rows"] == result["staged_committed_rows"] == 2
    with database.read() as conn:
        assert len(visible(conn)) == 2
        # Predicate remains usable when callers join attempt metadata for lineage.
        assert (
            len(
                conn.execute(
                    select(demo)
                    .join(attempts, attempts.c.id == demo.c.import_attempt_id)
                    .where(visibility_predicate(demo.c.import_attempt_id))
                ).all()
            )
            == 2
        )


def test_chunk_retry_and_alternate_payload_conflict(runtime):
    database, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1"), row("2")])
    first = writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="one", start=0, count=1, write_pending=write_pending
        )
    )

    def forbidden(*_):
        raise AssertionError("retry must not execute domain writes")

    again = writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="one", start=0, count=1, write_pending=forbidden
        )
    )
    assert first == again
    with pytest.raises(CoreError, match="IMPORT_CHUNK_CONFLICT"):
        writer.run(
            lambda conn: service.commit_chunk(
                conn, attempt, chunk_id="one", start=0, count=2, write_pending=forbidden
            )
        )
    with database.read() as conn:
        assert conn.execute(select(func.count()).select_from(demo)).scalar_one() == 1
        assert conn.execute(select(func.count()).select_from(receipts)).scalar_one() == 1


def test_failed_callback_rolls_back_domain_claim_receipt_and_checkpoint(runtime):
    database, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1")])

    def fail(conn, identity, rows):
        write_pending(conn, identity, rows)
        raise RuntimeError("synthetic failure after row write")

    with pytest.raises(RuntimeError):
        writer.run(
            lambda conn: service.commit_chunk(
                conn, attempt, chunk_id="one", start=0, count=1, write_pending=fail
            )
        )
    with database.read() as conn:
        for table in (demo, claims, receipts):
            assert conn.execute(select(func.count()).select_from(table)).scalar_one() == 0
        assert service.status(conn, attempt)["checkpoint"] == 0
        assert service.status(conn, attempt)["staged_committed_rows"] == 0


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "RECOVERABLE"])
def test_interrupted_attempt_requires_explicit_resume(runtime, state):
    _, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1")])
    writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="one", start=0, count=1, write_pending=write_pending
        )
    )
    writer.run(lambda conn: service.set_interrupted(conn, attempt, state))
    with pytest.raises(CoreError, match="IMPORT_ATTEMPT_INCOMPLETE"):
        writer.run(lambda conn: service.publish(conn, attempt))
    writer.run(lambda conn: service.resume(conn, attempt))
    assert writer.run(lambda conn: service.publish(conn, attempt))["published_rows"] == 1


def test_source_identity_claim_survives_publication_but_new_job_is_independent(runtime):
    _, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1")])
    writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="one", start=0, count=1, write_pending=write_pending
        )
    )
    writer.run(lambda conn: service.publish(conn, attempt))
    _, duplicate = prepare(writer, service, [row("1", "200.00")])
    with pytest.raises(CoreError, match="IMPORT_SOURCE_ALREADY_CLAIMED"):
        writer.run(
            lambda conn: service.commit_chunk(
                conn, duplicate, chunk_id="one", start=0, count=1, write_pending=write_pending
            )
        )
    _, separate = prepare(writer, service, [row("1")], job="intentional-new-job")
    assert writer.run(
        lambda conn: service.commit_chunk(
            conn, separate, chunk_id="one", start=0, count=1, write_pending=write_pending
        )
    )


def test_competing_attempts_cannot_claim_one_source_row_twice(runtime):
    database, writer, service = runtime
    _, first = prepare(writer, service, [row("1")])
    _, second = prepare(writer, service, [row("1", "200.00")])
    barrier = Barrier(2)

    def compete(attempt):
        barrier.wait(timeout=5)
        try:
            writer.run(
                lambda conn: service.commit_chunk(
                    conn, attempt, chunk_id="race", start=0, count=1, write_pending=write_pending
                )
            )
            return "committed"
        except CoreError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (first, second)))
    assert sorted(results) == ["IMPORT_SOURCE_ALREADY_CLAIMED", "committed"]
    with database.read() as conn:
        assert conn.execute(select(func.count()).select_from(demo)).scalar_one() == 1
        assert conn.execute(select(func.count()).select_from(claims)).scalar_one() == 1


def test_real_process_exit_after_chunk_reopens_without_replaying_committed_rows(runtime):
    database, writer, service = runtime
    _, attempt = prepare(writer, service, [row("1"), row("2")])
    script = """
import os, sys, json
from sqlalchemy import text
from cafe_fin.core.db import Database, WriteCoordinator
from cafe_fin.core.imports import MIGRATIONS, ImportAttemptService
db = Database(sys.argv[1]); db.migrate(MIGRATIONS)
w = WriteCoordinator(db); service = ImportAttemptService()
def save(conn, identity, rows):
    for row in rows:
        conn.execute(text('INSERT INTO example_pending_rows VALUES (:id,:attempt,:payload)'),
                     dict(id=row.target_id, attempt=identity, payload=json.dumps(row.snapshot)))
w.run(lambda conn: service.commit_chunk(conn, sys.argv[2], chunk_id='killed-chunk', start=0,
                                       count=1, write_pending=save))
os._exit(17)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "backend"))
    result = subprocess.run(
        [sys.executable, "-c", script, str(database.path), attempt],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 17, result.stderr
    with database.read() as conn:
        assert service.status(conn, attempt)["checkpoint"] == 1
        assert visible(conn) == []
    writer.run(lambda conn: service.set_interrupted(conn, attempt, "RECOVERABLE"))
    writer.run(lambda conn: service.resume(conn, attempt))
    writer.run(
        lambda conn: service.commit_chunk(
            conn, attempt, chunk_id="second", start=1, count=1, write_pending=write_pending
        )
    )
    writer.run(lambda conn: service.publish(conn, attempt))
    with database.read() as conn:
        assert len(visible(conn)) == 2
        assert conn.execute(select(func.count()).select_from(claims)).scalar_one() == 2


def test_dto_keeps_multirole_party_nullable_weights_and_separate_pending_counts():
    party = PartyDTO(
        id="party-1",
        version=1,
        type="organization",
        roles=("customer", "supplier"),
        name="Đối tác tổng hợp",
    )
    assert party.roles == ("customer", "supplier")
    assert WeightLineInput(net_kg=None).net_kg is None
    assert WeightLineInput(net_kg="0.000").net_kg == "0.000"
    with pytest.raises(ValidationError):
        WeightLineInput(net_kg=1.5)
    counts = dict(
        source_rows=10,
        validated=10,
        valid=8,
        invalid=2,
        potential_duplicates=3,
        conflicts=1,
        excluded=1,
        staged_committed_rows=8,
        published_rows=0,
        pending=8,
    )
    assert ImportCountsDTO(**counts).pending == 8
    with pytest.raises(ValidationError):
        ImportCountsDTO(**(counts | {"pending": 0}))


def test_aggregate_dto_supports_exact_totals_beyond_int64_and_requires_mapping():
    metric = MappedBookMetricDTO(
        key="entered_receipts", amount_vnd="9223372036854775808.00", mapping_revision=1
    )
    base = dict(
        book_id="book-1",
        from_on=date(2026, 11, 1),
        through_on=date(2026, 11, 6),
        cutoff=datetime(2026, 11, 6, tzinfo=timezone.utc),
        metrics=(metric,),
    )
    assert (
        BookSummaryDTO(**base, has_valid_money_mapping=True).metrics[0].amount_vnd
        == metric.amount_vnd
    )
    with pytest.raises(ValidationError):
        BookSummaryDTO(**base, has_valid_money_mapping=False)
    with pytest.raises(ValidationError):
        MappedBookMetricDTO(key="unsupported_precision", amount_vnd="1.001", mapping_revision=1)
