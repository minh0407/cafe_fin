"""Developer acceptance controller, not a dependency required by Cafe Fin users.

Source mini: python -m tests.accounting.desktop_delivery.runner --mode source
  --output-root <fresh-external-path>
Packaged: --mode frozen-sidecar --candidate-manifest <05-receipt.json>
  --expected-source-sha <coordinator-SHA>. Large runs also require --slot-receipt.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .acceptance import (
    ForegroundProbe,
    bulk_begin,
    bulk_finish,
    mini_after_restart,
    mini_before_restart,
    require,
)
from .bulk_fixture import generate_bulk_csv
from .checkpoint import (
    cancel_at_checkpoint,
    cancelled_restart_observation,
    closed_parse_reconciliation,
    stage_prefix_digest,
)
from .fixtures import generate_fixture_kit
from .measurements import Sampler, latency_summary, windows_process_tree
from .transport import AcceptanceError, Sidecar, artifact_identity, outside_repo, sha256

BASELINE = "eab8c96b851f039de515083189f4301cc09437c0"
WORKLOADS = {
    "desktop-mini-xlsm-1000": 1000,
    "csv-mini-1000": 1000,
    "csv-checkpoint-5000": 5000,
    "csv-50k": 50000,
    "csv-500k": 500000,
    "csv-1m": 1000000,
}


def verify_slot(path, workload, mode, source_sha):
    if path is None:
        raise AcceptanceError("COORDINATOR_LARGE_SLOT_REQUIRED")
    try:
        if path.stat().st_size > 65536:
            raise ValueError()
        receipt = json.loads(path.read_text(encoding="utf-8"))
        start = datetime.fromisoformat(receipt["granted_at_utc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(receipt["expires_at_utc"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        valid = (
            start.tzinfo is not None
            and end.tzinfo is not None
            and start <= now <= end
            and receipt["approved_source_sha"] == source_sha
            and isinstance(receipt["workload_ids"], list)
            and isinstance(receipt["evidence_modes"], list)
            and workload in receipt["workload_ids"]
            and mode in receipt["evidence_modes"]
            and isinstance(receipt["slot_id"], str)
            and 0 < len(receipt["slot_id"]) <= 128
            and isinstance(receipt["coordinator_decision_ref"], str)
            and 0 < len(receipt["coordinator_decision_ref"]) <= 512
        )
        if not valid:
            raise ValueError()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise AcceptanceError("COORDINATOR_SLOT_INVALID") from exc
    return {
        "slot_id": receipt["slot_id"],
        "receipt_sha256": sha256(path),
        "declared_host_scope": receipt.get("declared_host_scope", "shared_unpinned"),
    }


def closed_db_reconciliation(data_root, evidence):
    database = data_root / "database/cafe_fin.db"
    wal = database.with_name(database.name + "-wal")
    require(not wal.exists() or wal.stat().st_size == 0, "DATABASE_WAL_NOT_CLOSED")
    with sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        count, distinct = connection.execute(
            "SELECT COUNT(*),COUNT(DISTINCT target_id) FROM core_import_claims WHERE job_id=?",
            (evidence["batch_id"],),
        ).fetchone()
        published = connection.execute(
            "SELECT COUNT(*) FROM accounting_entries e LEFT JOIN core_import_attempts a ON a.id=e.import_attempt_id WHERE e.book_id=? AND (e.import_attempt_id IS NULL OR a.state='PUBLISHED')",
            (evidence["book_id"],),
        ).fetchone()[0]
        attempts = connection.execute(
            "SELECT COUNT(*) FROM core_import_attempts WHERE job_id=? AND state='PUBLISHED'",
            (evidence["batch_id"],),
        ).fetchone()[0]
        expected = evidence["final_publication"]["published_rows"]
        require(
            count == distinct == published == expected and attempts == 2, "CLOSED_LINEAGE_MISMATCH"
        )
        checkpoint = evidence.get("parse_checkpoint_closed")
        parse_result = {}
        if checkpoint is not None:
            total, distinct_source = connection.execute(
                "SELECT COUNT(*),COUNT(DISTINCT row_id) FROM accounting_staged_rows WHERE batch_id=?",
                (evidence["batch_id"],),
            ).fetchone()
            require(total == distinct_source == evidence["rows"], "RESUMED_STAGING_COUNT_MISMATCH")
            require(
                stage_prefix_digest(connection, evidence["batch_id"], checkpoint["parsed_rows"])
                == checkpoint["source_prefix_sha256"],
                "RESUMED_SOURCE_PREFIX_CHANGED",
            )
            receipt = connection.execute(
                "SELECT payload_hash FROM core_job_receipts WHERE job_id=? AND chunk_id=?",
                (checkpoint["job_id"], checkpoint["receipt_chunk_id"]),
            ).fetchone()
            require(
                receipt is not None and receipt[0] == checkpoint["receipt_payload_sha256"],
                "RESUMED_PARSE_RECEIPT_CHANGED",
            )
            parse_result = {
                "resumed_staging_rows": total,
                "resumed_distinct_source_ids": distinct_source,
                "retained_checkpoint_prefix": "PASS",
                "retained_parse_receipt": "PASS",
            }
        return {
            "published_rows": published,
            "lineage_rows": count,
            "distinct_targets": distinct,
            "published_attempts": attempts,
            "scope": "read-only immutable synthetic DB after verified process exit",
            **parse_result,
        }


def checkpoint_observation(before, after, rows):
    """A pre-exit partial counter alone cannot establish durable resume."""
    before_job, after_job = before["job"], after["job"]
    require(
        before["id"] == after["id"] and before_job["id"] == after_job["id"],
        "RESTART_JOB_IDENTITY_CHANGED",
    )
    parsed_before = before_job.get("counts", {}).get("parsed", 0)
    parsed_after = after_job.get("counts", {}).get("parsed", 0)
    observed = 500 <= parsed_before <= parsed_after < rows and after_job["state"] == "RECOVERABLE"
    return {
        "status": "DURABLE_PARTIAL_OBSERVED" if observed else "WINDOW_MISSED",
        "parsed_before_exit": parsed_before,
        "parsed_after_restart": parsed_after,
        "job_state_after_restart": after_job["state"],
        "same_batch_and_job": True,
        "scope": "owned graceful stop; not crash/power-loss evidence",
    }


def run(args):
    repository = Path(__file__).resolve().parents[3]
    output = outside_repo(args.output_root, repository)
    require(not output.exists(), "FRESH_OUTPUT_ROOT_REQUIRED")
    rows = WORKLOADS[args.workload]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    if args.mode == "frozen-sidecar":
        require(os.name == "nt", "WINDOWS_PACKAGED_ARTIFACT_REQUIRED")
        require(
            args.candidate_manifest is not None and args.expected_source_sha is not None,
            "PACKAGED_IDENTITY_REQUIRED",
        )
        identity = artifact_identity(args.candidate_manifest.resolve(), args.expected_source_sha)
        executable_command = [identity["sidecar"]["path"]]
    else:
        identity = {
            "source_sha": source_sha,
            "evidence_mode": "source",
            "planning_baseline": BASELINE,
            "gui_native": "NOT_RUN",
            "frozen_sidecar": "NOT_RUN",
            "clean_windows": "NOT_RUN",
        }
        executable_command = [sys.executable, "-m", "cafe_fin"]
        require(
            not subprocess.check_output(
                ["git", "status", "--porcelain", "--", "backend", "frontend/src", "desktop"],
                cwd=repository,
            ),
            "SOURCE_PRODUCT_TREE_DIRTY",
        )
    slot = None
    if rows >= 50000:
        # A prepared workload is not authorization. No fixture or data root is
        # created until the coordinator's exact-candidate slot receipt validates.
        require(args.mode == "frozen-sidecar", "LARGE_PACKAGED_CANDIDATE_REQUIRED")
        slot = verify_slot(args.slot_receipt, args.workload, args.mode, identity["source_sha"])
    elif args.slot_receipt is not None:
        slot = verify_slot(args.slot_receipt, args.workload, args.mode, identity["source_sha"])
    output.mkdir(parents=True)
    result = {
        "schema": "accounting-desktop-acceptance-v1",
        "status": "RUNNING",
        "workload": args.workload,
        "rows": rows,
        "evidence_mode": args.mode,
        "identity": identity,
        "slot": slot,
        "harness_git_sha": source_sha,
        "harness_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=repository)
        ),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "phases": [],
        "gui_native": "NOT_RUN",
        "clean_windows": "NOT_RUN",
        "network_scope": "controller HTTP loopback only; proxies/redirects disabled; market test network gate0; reporting fresh UNCONFIGURED; backend OS network NOT_MEASURED",
        "resource_runs": [],
        "stage_timings": [],
        "workload_manifest": {
            "path": str(repository / "tests/accounting/desktop_delivery/workloads.json"),
            "sha256": sha256(repository / "tests/accounting/desktop_delivery/workloads.json"),
        },
        "harness_files": {
            str(path.relative_to(repository)): sha256(path)
            for path in sorted(Path(__file__).parent.glob("*.py"))
        },
        "host_interference": "shared developer host; other-chat load/cache/affinity NOT_CONTROLLED",
        "controller_runtime": {
            "python": sys.version,
            "executable": sys.executable,
            "sqlite": sqlite3.sqlite_version,
        },
    }
    data_root = output / "data"
    data_root.parent.joinpath("synthetic-controller.json").write_text(
        json.dumps({"synthetic_only": True, "workload": args.workload}), encoding="utf-8"
    )
    started, client, sampler = time.perf_counter(), None, None
    password, username = secrets.token_urlsafe(32), "accounting-desktop-synthetic"
    all_latencies = []

    def new_client(initialize):
        nonlocal sampler
        current = Sidecar(executable_command, repository, data_root)
        try:
            current.start(initialize=initialize, source=args.mode == "source")
            if args.mode == "frozen-sidecar":
                images = windows_process_tree(current.process.pid)
                root_image = next(
                    (
                        item.get("image_path")
                        for item in images
                        if item["pid"] == current.process.pid
                    ),
                    None,
                )
                require(
                    root_image is not None
                    and Path(root_image).resolve() == Path(identity["sidecar"]["path"]).resolve(),
                    "PACKAGED_PROCESS_IMAGE_MISMATCH",
                )
                require(
                    not any(
                        item["executable"].lower() in {"python.exe", "pythonw.exe"}
                        for item in images
                    ),
                    "PACKAGED_PYTHON_FALLBACK_DENIED",
                )
                result.setdefault("launch_images", []).append(images)
            sampler = Sampler(current.process.pid, data_root)
            sampler.thread.start()
            auth = current.request(
                "POST",
                "/auth/setup" if initialize else "/auth/login",
                {"username": username, "password": password},
            )
            current.access_token = auth["access_token"]
        except Exception:
            if current.process is not None:
                close_client(current)
            raise
        return current

    def close_client(current):
        nonlocal sampler
        try:
            current.close()
        finally:
            all_latencies.extend(current.latencies)
            if sampler is not None:
                result["resource_runs"].append(sampler.finish())
                sampler = None

    try:
        generation_started = time.perf_counter()
        if args.workload == "desktop-mini-xlsm-1000":
            manifest = generate_fixture_kit(output / "fixtures", 1000)
        else:
            manifest = generate_bulk_csv(output / "fixtures", rows)
            path = output / "fixtures/manifest.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest["manifest_artifact"] = {"path": str(path), "sha256": sha256(path)}
        result["fixture_manifest"] = manifest["manifest_artifact"]
        result["stage_timings"].append(
            {"stage": "fixture_generation", "seconds": time.perf_counter() - generation_started}
        )
        client = new_client(True)
        sampler.stage = "mini_before_restart" if rows == 1000 else "parse"
        if args.workload == "desktop-mini-xlsm-1000":
            phase_started = time.perf_counter()
            batch = mini_before_restart(client, manifest, result)
            result["stage_timings"].append(
                {"stage": "parse_mapping_validate", "seconds": time.perf_counter() - phase_started}
            )
            close_client(client)
            client = new_client(False)
            sampler.stage = "mini_partial_repair_export"
            phase_started = time.perf_counter()
            mini_after_restart(client, manifest, batch, result)
            result["stage_timings"].append(
                {"stage": "partial_repair_export", "seconds": time.perf_counter() - phase_started}
            )
        else:
            book_id, file_id, batch_id = bulk_begin(client, manifest)
            result.update(book_id=book_id, file_id=file_id, batch_id=batch_id)
            before_restart, stop = cancel_at_checkpoint(
                client, batch_id, rows, timeout=86400 if rows >= 50000 else 120
            )
            result["parse_stop"] = stop
            result["restart_process"] = {"old_pid": client.process.pid}
            close_client(client)
            if stop["status"] == "PARTIAL_CANCELLED":
                result["parse_checkpoint_closed"] = closed_parse_reconciliation(
                    data_root, before_restart, rows
                )
            result["restart_process"]["old_exit_code"] = client.process.returncode
            client = new_client(False)
            result["restart_process"]["new_pid"] = client.process.pid
            after_restart = client.request("GET", f"/accounting/import-jobs/{batch_id}")
            checkpoint = cancelled_restart_observation(before_restart, after_restart, rows)
            result["mid_parse_checkpoint_resume"] = checkpoint
            probe = ForegroundProbe(client, manifest, book_id)
            sampler.stage = "volume_validate_confirm_repair_export"
            bulk_finish(client, manifest, result, probe=probe)
            checkpoint["resume_completed_same_batch"] = (
                result["final_publication"]["published_rows"] == rows
            )
        close_client(client)
        result["closed_reconciliation"] = closed_db_reconciliation(data_root, result)
        if args.mode == "frozen-sidecar":
            require(
                sha256(Path(identity["sidecar"]["path"])) == identity["sidecar"]["sha256"],
                "ARTIFACT_CHANGED_DURING_RUN",
            )
            require(
                sha256(args.candidate_manifest.resolve()) == identity["manifest_sha256"],
                "ARTIFACT_MANIFEST_CHANGED_DURING_RUN",
            )
            require(
                not any(
                    process["executable"].lower() in {"python.exe", "pythonw.exe"}
                    for resource in result["resource_runs"]
                    for sample in resource["samples"]
                    for process in sample["processes"]
                ),
                "PACKAGED_PYTHON_FALLBACK_DENIED",
            )
        result["status"] = "PASS"
        if (
            args.workload != "desktop-mini-xlsm-1000"
            and result["mid_parse_checkpoint_resume"]["status"] == "WINDOW_MISSED"
        ):
            result.update(
                status="BLOCKED", code="CHECKPOINT_WINDOW_MISSED", functional_acceptance="PASS"
            )
    except AcceptanceError as exc:
        result.update(
            status="BLOCKED" if "OS_LAUNCH_BLOCKED" in exc.code else "FAIL", code=exc.code
        )
    except KeyboardInterrupt:
        result.update(status="INTERRUPTED", code="CONTROLLER_INTERRUPTED")
    except Exception:
        result.update(status="FAIL", code="ACCEPTANCE_UNEXPECTED_FAILURE")
    finally:
        if client is not None and not client.closed:
            try:
                close_client(client)
            except AcceptanceError:
                result.update(status="FAIL", code="SIDECAR_SHUTDOWN_FAILED")
        if sampler is not None:
            result["resource_runs"].append(sampler.finish())
        result["total_seconds"] = time.perf_counter() - started
        result["http_latency"] = latency_summary(all_latencies)
        result["closed"] = client is not None and client.closed
        result["gui_native"] = "NOT_RUN"
        result["ended_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "code": result.get("code"),
                "result": str(output / "result.json"),
                "evidence_mode": args.mode,
            }
        )
    )
    return 0 if result["status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("source", "frozen-sidecar"), required=True)
    parser.add_argument("--workload", choices=tuple(WORKLOADS), default="desktop-mini-xlsm-1000")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--slot-receipt", type=Path)
    args = parser.parse_args()
    try:
        return run(args)
    except AcceptanceError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code}))
        return 2
    except (OSError, ValueError):
        print(json.dumps({"status": "BLOCKED", "code": "CONTROLLER_PREPARATION_FAILED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
