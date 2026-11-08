"""Controller guards with scripted replies/tiny SQLite, never runtime resume proof."""

import hashlib
import json
import sqlite3
from collections import deque
from copy import deepcopy

import pytest

from . import checkpoint
from .transport import AcceptanceError, sha256

BATCH_ID = "synthetic-batch"
JOB_ID = "synthetic-job"
ENDPOINT = f"/accounting/import-jobs/{BATCH_ID}"


def _batch(parsed=500, state="RUNNING", **changes):
    batch = {
        "id": BATCH_ID,
        "book_id": "synthetic-book",
        "file_id": "synthetic-file",
        "file_hash": "a" * 64,
        "job": {
            "id": JOB_ID,
            "state": state,
            "counts": {"parsed": parsed},
            "checkpoint": {"parsed": parsed},
        },
    }
    batch.update(changes)
    return batch


class ScriptedClient:
    """Any extra foreground call or reordered cancellation fails immediately."""

    def __init__(self, script):
        self.script = deque(script)
        self.calls = []

    def request(self, method, endpoint, *args, **kwargs):
        assert self.script, "unexpected foreground request"
        expected_method, expected_endpoint, response = self.script.popleft()
        assert (method, endpoint) == (expected_method, expected_endpoint)
        self.calls.append((method, endpoint))
        if method == "POST":
            assert endpoint == ENDPOINT + "/cancel"
            assert kwargs["expected"] == (200, 409)
            assert len(args) == 1 and isinstance(args[0]["request_key"], str)
        return deepcopy(response)


def _error(code, function, *args, **kwargs):
    with pytest.raises(AcceptanceError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_partial_progress_immediately_cancels_then_waits_for_durable_cancelled():
    client = ScriptedClient(
        [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {}),
            ("GET", ENDPOINT, _batch(500, "RUNNING")),
            ("GET", ENDPOINT, _batch(600, "CANCELLED")),
        ]
    )
    stopped, result = checkpoint.cancel_at_checkpoint(client, BATCH_ID, 1000, poll_seconds=0)
    assert not client.script
    assert client.calls[:2] == [("GET", ENDPOINT), ("POST", ENDPOINT + "/cancel")]
    assert stopped["job"]["state"] == "CANCELLED"
    assert result["status"] == "PARTIAL_CANCELLED"
    assert result["observed_before_cancel"] == 500
    assert result["stopped_parsed"] == 600
    assert result["cancel_requested"] is True


def test_completed_parse_is_missed_without_cancel_request():
    client = ScriptedClient([("GET", ENDPOINT, _batch(1000, "COMPLETED"))])
    _, result = checkpoint.cancel_at_checkpoint(client, BATCH_ID, 1000, poll_seconds=0)
    assert result["status"] == "WINDOW_MISSED"
    assert result["cancel_requested"] is False
    assert client.calls == [("GET", ENDPOINT)]


def test_cancel_stopped_after_all_rows_is_missed_even_when_state_is_cancelled():
    client = ScriptedClient(
        [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {}),
            ("GET", ENDPOINT, _batch(1000, "CANCELLED")),
        ]
    )
    _, result = checkpoint.cancel_at_checkpoint(client, BATCH_ID, 1000, poll_seconds=0)
    assert result["status"] == "WINDOW_MISSED"
    assert result["cancel_requested"] is True


def test_only_precise_verified_already_completed_race_is_accepted():
    client = ScriptedClient(
        [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {"error": {"code": "JOB_ALREADY_COMPLETED"}}),
            ("GET", ENDPOINT, _batch(1000, "COMPLETED")),
        ]
    )
    _, result = checkpoint.cancel_at_checkpoint(client, BATCH_ID, 1000, poll_seconds=0)
    assert result["status"] == "WINDOW_MISSED"
    assert result["cancel_requested"] is True
    wrong_error = ScriptedClient(
        [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {"error": {"code": "VERSION_CONFLICT"}}),
        ]
    )
    _error(
        "PARSE_CANCEL_REJECTED",
        checkpoint.cancel_at_checkpoint,
        wrong_error,
        BATCH_ID,
        1000,
        poll_seconds=0,
    )
    unverified = ScriptedClient(
        [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {"error": {"code": "JOB_ALREADY_COMPLETED"}}),
            ("GET", ENDPOINT, _batch()),
        ]
    )
    _error(
        "PARSE_CANCEL_RACE_UNVERIFIED",
        checkpoint.cancel_at_checkpoint,
        unverified,
        BATCH_ID,
        1000,
        poll_seconds=0,
    )


@pytest.mark.parametrize("when", ["before-cancel", "after-cancel"])
def test_counter_checkpoint_mismatch_rejects_before_claiming_progress(when):
    inconsistent = _batch()
    inconsistent["job"]["checkpoint"]["parsed"] = 0
    script = (
        [("GET", ENDPOINT, inconsistent)]
        if when == "before-cancel"
        else [
            ("GET", ENDPOINT, _batch()),
            ("POST", ENDPOINT + "/cancel", {}),
            ("GET", ENDPOINT, inconsistent),
        ]
    )
    client = ScriptedClient(script)
    _error(
        "PARSE_COUNTER_CHECKPOINT_MISMATCH",
        checkpoint.cancel_at_checkpoint,
        client,
        BATCH_ID,
        1000,
        poll_seconds=0,
    )
    if when == "before-cancel":
        assert client.calls == [("GET", ENDPOINT)]


def test_cancelled_restart_requires_same_partial_count_and_cancelled_state():
    stopped = _batch(500, "CANCELLED")
    observed = checkpoint.cancelled_restart_observation(stopped, deepcopy(stopped), 1000)
    assert observed["status"] == "DURABLE_PARTIAL_OBSERVED"
    assert observed["same_batch_and_job"] and observed["same_source_file_and_book"]
    assert observed["parsed_before_exit"] == observed["parsed_after_restart"] == 500
    assert observed["stop_method"] == "public_api_cooperative_cancel"
    assert "not crash/power-loss" in observed["scope"]
    for after in [
        _batch(0, "CANCELLED"),
        _batch(600, "CANCELLED"),
        _batch(500, "COMPLETED"),
        _batch(1000, "COMPLETED"),
    ]:
        result = checkpoint.cancelled_restart_observation(stopped, after, 1000)
        assert result["status"] == "WINDOW_MISSED"


@pytest.mark.parametrize("field", ["id", "job.id", "book_id", "file_id", "file_hash"])
def test_cancelled_restart_rejects_changed_source_and_job_identities(field):
    stopped = _batch(500, "CANCELLED")
    after = deepcopy(stopped)
    if field == "job.id":
        after["job"]["id"] = "changed"
    else:
        after[field] = "changed"
    code = (
        "RESTART_JOB_IDENTITY_CHANGED"
        if field in {"id", "job.id"}
        else "RESTART_SOURCE_IDENTITY_CHANGED"
    )
    _error(code, checkpoint.cancelled_restart_observation, stopped, after, 1000)


def _stage_row(index):
    return (
        f"csv:{index + 1}",
        "csv",
        index + 1,
        json.dumps({"A": f"{index:012d}", "B": "Cà phê tổng hợp"}, ensure_ascii=False),
    )


def _database(tmp_path):
    data_root = tmp_path / "synthetic-app"
    folder = data_root / "database"
    folder.mkdir(parents=True)
    path = folder / "cafe_fin.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE core_jobs(id TEXT,state TEXT,counts_json TEXT,checkpoint_json TEXT);
            CREATE TABLE accounting_staged_rows(batch_id TEXT,row_id TEXT,source_sheet TEXT,source_row INTEGER,raw_json TEXT);
            CREATE TABLE core_job_receipts(job_id TEXT,chunk_id TEXT,payload_hash TEXT,result_json TEXT);
        """)
        conn.execute(
            "INSERT INTO core_jobs VALUES(?,?,?,?)",
            (JOB_ID, "CANCELLED", '{"parsed":500}', '{"parsed":500}'),
        )
        conn.executemany(
            "INSERT INTO accounting_staged_rows VALUES(?,?,?,?,?)",
            ((BATCH_ID, *_stage_row(index)) for index in range(500, 0, -1)),
        )
        conn.execute(
            "INSERT INTO core_job_receipts VALUES(?,?,?,?)",
            (JOB_ID, "parse:500", "b" * 64, '{"parsed":500}'),
        )
    return data_root, path


def _prefix_hash():
    digest = hashlib.sha256()
    for index in range(1, 501):
        digest.update(
            json.dumps(list(_stage_row(index)), ensure_ascii=False, separators=(",", ":")).encode()
            + b"\n"
        )
    return digest.hexdigest()


def test_closed_reconciliation_reads_existing_db_readonly_and_retains_source_prefix(
    tmp_path, monkeypatch
):
    data_root, path = _database(tmp_path)
    original_hash = sha256(path)
    connect = sqlite3.connect
    calls = []

    def observed_connect(database, **kwargs):
        calls.append((database, kwargs))
        assert str(database).endswith("?mode=ro&immutable=1")
        assert kwargs == {"uri": True}
        return connect(database, **kwargs)

    monkeypatch.setattr(checkpoint.sqlite3, "connect", observed_connect)
    result = checkpoint.closed_parse_reconciliation(data_root, _batch(500, "CANCELLED"), 1000)
    assert len(calls) == 1
    assert result["status"] == "PASS"
    assert result["parsed_rows"] == result["staging_rows"] == result["distinct_source_ids"] == 500
    assert result["receipt_chunk_id"] == "parse:500"
    assert result["receipt_payload_sha256"] == "b" * 64
    assert result["source_prefix_sha256"] == _prefix_hash()
    assert sha256(path) == original_hash


@pytest.mark.parametrize(
    "corruption",
    [
        "state",
        "counts",
        "checkpoint",
        "missing-stage",
        "duplicate-row-id",
        "missing-receipt",
        "receipt-count",
    ],
)
def test_closed_reconciliation_rejects_receipt_or_staging_mismatch(tmp_path, corruption):
    data_root, path = _database(tmp_path)
    mutations = {
        "state": "UPDATE core_jobs SET state='COMPLETED'",
        "counts": "UPDATE core_jobs SET counts_json='{\"parsed\":0}'",
        "checkpoint": "UPDATE core_jobs SET checkpoint_json='{\"parsed\":0}'",
        "missing-stage": "DELETE FROM accounting_staged_rows WHERE source_row=2",
        "duplicate-row-id": "UPDATE accounting_staged_rows SET row_id='csv:2' WHERE source_row=3",
        "missing-receipt": "DELETE FROM core_job_receipts",
        "receipt-count": "UPDATE core_job_receipts SET result_json='{\"parsed\":0}'",
    }
    with sqlite3.connect(path) as conn:
        conn.execute(mutations[corruption])
    _error(
        "CLOSED_PARSE_CHECKPOINT_MISMATCH",
        checkpoint.closed_parse_reconciliation,
        data_root,
        _batch(500, "CANCELLED"),
        1000,
    )


def test_prefix_digest_stays_stable_on_append_and_detects_original_prefix_change(tmp_path):
    _, path = _database(tmp_path)
    with sqlite3.connect(path) as conn:
        assert checkpoint.stage_prefix_digest(conn, BATCH_ID, 500) == _prefix_hash()
        conn.execute(
            "INSERT INTO accounting_staged_rows VALUES(?,?,?,?,?)", (BATCH_ID, *_stage_row(501))
        )
        assert checkpoint.stage_prefix_digest(conn, BATCH_ID, 500) == _prefix_hash()
        conn.execute("UPDATE accounting_staged_rows SET raw_json='{}' WHERE source_row=2")
        assert checkpoint.stage_prefix_digest(conn, BATCH_ID, 500) != _prefix_hash()
        _error("PARSE_PREFIX_COUNT_MISMATCH", checkpoint.stage_prefix_digest, conn, BATCH_ID, 502)


def test_nonempty_wal_rejects_closed_reconciliation(tmp_path):
    data_root, path = _database(tmp_path)
    path.with_name(path.name + "-wal").write_bytes(b"synthetic-open-wal-marker")
    _error(
        "DATABASE_WAL_NOT_CLOSED",
        checkpoint.closed_parse_reconciliation,
        data_root,
        _batch(500, "CANCELLED"),
        1000,
    )
