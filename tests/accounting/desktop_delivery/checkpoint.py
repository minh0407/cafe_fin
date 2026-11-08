"""Test-controller checkpoint stop using existing public cooperative cancel API.

No product patch, parser barrier or frozen-code injection. A missed window stays
missed. Successful checkpoint evidence requires a partial worker durably
CANCELLED before shutdown; an already-finished parse cannot establish it.
"""

import hashlib
import json
import sqlite3
import time

from .acceptance import command, require
from .transport import AcceptanceError


def parsed_checkpoint(batch):
    job = batch["job"]
    parsed = job.get("counts", {}).get("parsed", 0)
    checkpoint = job.get("checkpoint", {}).get("parsed", 0)
    require(parsed == checkpoint, "PARSE_COUNTER_CHECKPOINT_MISMATCH")
    return parsed


def cancel_at_checkpoint(client, batch_id, rows, *, timeout=120, poll_seconds=0.01):
    """Observe a committed partial chunk before requesting a cooperative stop."""
    deadline = time.monotonic() + timeout
    events = []
    while time.monotonic() < deadline:
        batch = client.request(
            "GET", f"/accounting/import-jobs/{batch_id}", label="parse_checkpoint_status"
        )
        state, parsed = batch["job"]["state"], parsed_checkpoint(batch)
        event = {"state": state, "parsed": parsed}
        if not events or events[-1] != event:
            events.append(event)
        if state == "COMPLETED":
            return batch, {
                "status": "WINDOW_MISSED",
                "events": events,
                "cancel_requested": False,
                "poll_seconds": poll_seconds,
            }
        require(state not in {"FAILED", "CANCELLED", "RECOVERABLE"}, "PARSE_FAILED_BEFORE_PROBE")
        if state == "RUNNING" and 500 <= parsed < rows:
            observed = batch
            # No foreground writes/probes between observing progress and cancel.
            # Accept only the precise completed-race error as a missed window.
            cancelled = client.request(
                "POST",
                f"/accounting/import-jobs/{batch_id}/cancel",
                command(),
                expected=(200, 409),
                label="parse_checkpoint_cancel",
            )
            if cancelled.get("error", {}).get("code") == "JOB_ALREADY_COMPLETED":
                finished = client.request("GET", f"/accounting/import-jobs/{batch_id}")
                require(finished["job"]["state"] == "COMPLETED", "PARSE_CANCEL_RACE_UNVERIFIED")
                return finished, {
                    "status": "WINDOW_MISSED",
                    "events": events,
                    "cancel_requested": True,
                    "poll_seconds": poll_seconds,
                }
            require("error" not in cancelled, "PARSE_CANCEL_REJECTED")
            while time.monotonic() < deadline:
                stopped = client.request(
                    "GET",
                    f"/accounting/import-jobs/{batch_id}",
                    label="parse_checkpoint_stop_status",
                )
                require(
                    stopped["job"]["id"] == observed["job"]["id"], "RESTART_JOB_IDENTITY_CHANGED"
                )
                state, stopped_count = stopped["job"]["state"], parsed_checkpoint(stopped)
                if state == "CANCELLED":
                    valid = parsed <= stopped_count < rows
                    return stopped, {
                        "status": "PARTIAL_CANCELLED" if valid else "WINDOW_MISSED",
                        "events": events,
                        "cancel_requested": True,
                        "observed_before_cancel": parsed,
                        "stopped_parsed": stopped_count,
                        "poll_seconds": poll_seconds,
                    }
                require(state == "RUNNING", "PARSE_DID_NOT_CANCEL")
                time.sleep(poll_seconds)
            raise AcceptanceError("PARSE_CANCEL_TIMEOUT")
        time.sleep(poll_seconds)
    raise AcceptanceError("PARSE_CHECKPOINT_TIMEOUT")


def stage_prefix_digest(connection, batch_id, count):
    digest = hashlib.sha256()
    cursor = connection.execute(
        "SELECT row_id,source_sheet,source_row,raw_json FROM accounting_staged_rows WHERE batch_id=? ORDER BY source_row,row_id LIMIT ?",
        (batch_id, count),
    )
    seen = 0
    for row in cursor:
        digest.update(
            json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        seen += 1
    require(seen == count, "PARSE_PREFIX_COUNT_MISMATCH")
    return digest.hexdigest()


def closed_parse_reconciliation(data_root, stopped, rows):
    """Read only this run's synthetic DB after owned sidecar verified exit."""
    database = data_root / "database/cafe_fin.db"
    wal = database.with_name(database.name + "-wal")
    require(not wal.exists() or wal.stat().st_size == 0, "DATABASE_WAL_NOT_CLOSED")
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        state, counts_json, checkpoint_json = connection.execute(
            "SELECT state,counts_json,checkpoint_json FROM core_jobs WHERE id=?",
            (stopped["job"]["id"],),
        ).fetchone()
        parsed = parsed_checkpoint(stopped)
        count, distinct = connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT row_id) FROM accounting_staged_rows WHERE batch_id=?",
            (stopped["id"],),
        ).fetchone()
        receipt = connection.execute(
            "SELECT payload_hash,result_json FROM core_job_receipts WHERE job_id=? AND chunk_id=?",
            (stopped["job"]["id"], f"parse:{parsed}"),
        ).fetchone()
        require(
            state == "CANCELLED"
            and 500 <= parsed < rows
            and count == distinct == parsed
            and json.loads(counts_json)["parsed"] == parsed
            and json.loads(checkpoint_json)["parsed"] == parsed
            and receipt is not None
            and json.loads(receipt[1])["parsed"] == parsed,
            "CLOSED_PARSE_CHECKPOINT_MISMATCH",
        )
        return {
            "status": "PASS",
            "job_id": stopped["job"]["id"],
            "state": state,
            "parsed_rows": parsed,
            "staging_rows": count,
            "distinct_source_ids": distinct,
            "receipt_chunk_id": f"parse:{parsed}",
            "receipt_payload_sha256": receipt[0],
            "source_prefix_sha256": stage_prefix_digest(connection, stopped["id"], parsed),
            "scope": "read-only immutable synthetic DB after verified owned process exit",
        }


def cancelled_restart_observation(stopped, after, rows):
    require(
        stopped["id"] == after["id"] and stopped["job"]["id"] == after["job"]["id"],
        "RESTART_JOB_IDENTITY_CHANGED",
    )
    for key in ("book_id", "file_id", "file_hash"):
        require(stopped[key] == after[key], "RESTART_SOURCE_IDENTITY_CHANGED")
    parsed = parsed_checkpoint(stopped)
    valid = (
        stopped["job"]["state"] == after["job"]["state"] == "CANCELLED"
        and 500 <= parsed == parsed_checkpoint(after) < rows
    )
    return {
        "status": "DURABLE_PARTIAL_OBSERVED" if valid else "WINDOW_MISSED",
        "parsed_before_exit": parsed,
        "parsed_after_restart": parsed_checkpoint(after),
        "job_state_after_restart": after["job"]["state"],
        "same_batch_and_job": True,
        "same_source_file_and_book": True,
        "stop_method": "public_api_cooperative_cancel",
        "scope": "cooperative cancel before shutdown; not crash/power-loss recovery",
    }
