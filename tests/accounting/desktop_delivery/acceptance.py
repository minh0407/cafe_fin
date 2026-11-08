"""The same bounded public-HTTP mini checks for source and packaged sidecars."""

from __future__ import annotations

import json
import secrets
import time
import urllib.parse
from pathlib import Path

from .transport import AcceptanceError, sha256


def require(condition, code):
    if not condition:
        raise AcceptanceError(code)


def command(**body):
    return body | {"request_key": secrets.token_hex(16)}


def wait_batch(client, batch_id, *, phases, timeout=120, probe=None):
    started, observations = time.perf_counter(), []
    while time.perf_counter() - started < timeout:
        batch = client.request("GET", f"/accounting/import-jobs/{batch_id}", label="batch_status")
        signature = {
            "state": batch["state"],
            "phase": batch.get("job", {}).get("phase"),
            "counts": batch["counts"],
        }
        if not observations or signature != observations[-1]["snapshot"]:
            observations.append({"seconds": time.perf_counter() - started, "snapshot": signature})
        state = batch.get("job", {}).get("state")
        if probe is not None:
            probe(batch)
        if state in {"FAILED", "RECOVERABLE", "CANCELLED"}:
            raise AcceptanceError("JOB_DID_NOT_COMPLETE")
        if state == "COMPLETED" and batch["state"] not in {
            "PARSING",
            "VALIDATING",
            "COMMITTING",
            "UPLOADED",
        }:
            phases.append({"seconds": time.perf_counter() - started, "observations": observations})
            return batch
        time.sleep(0.1)
    raise AcceptanceError("MINI_JOB_TIMEOUT")


def rows(client, book_id):
    return client.request(
        "GET", f"/accounting/books/{book_id}/rows?page_size=200", label="ledger_first_page"
    )


def reconcile(client, book_id, expected_count, expected_income):
    page = rows(client, book_id)
    require(
        page["total"] == expected_count and len(page["items"]) <= 200, "PUBLISHED_COUNT_MISMATCH"
    )
    summary = client.request(
        "GET",
        f"/accounting/books/{book_id}/summary?from_on=2026-01-01&through_on=2026-02-01",
        label="summary",
    )
    require(summary["totals"]["VND"]["income"] == expected_income, "EXACT_INCOME_MISMATCH")
    return {"published_rows": page["total"], "income_vnd": expected_income}


def validate(client, batch, phases):
    client.request(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/validate",
        command(expected_version=batch["version"]),
    )
    return wait_batch(client, batch["id"], phases=phases)


def confirm_body(batch):
    return command(
        expected_version=batch["version"],
        staging_revision=batch["revision"],
        mapping_revision=batch["mapping_revision"],
        decision_revision=batch["decision_revision"],
        validation_token=batch["validation_token"],
        mode="valid_rows_only",
    )


def mini_before_restart(client, manifest, evidence):
    source = manifest["files"]["xlsm"]
    require(manifest["rows"] == 1000, "MINI_1000_REQUIRED")
    create = command(**manifest["book"])
    original = client.request("POST", "/accounting/books", create)
    # Discard a genuine ACK then repeat the exact command, not a fabricated error.
    replay = client.request("POST", "/accounting/books", create)
    require(original["id"] == replay["id"], "BOOK_REPLAY_DUPLICATED")
    book_id = original["id"]
    uploaded = client.request("POST", "/files?category=workbooks", file=Path(source["path"]))
    require(uploaded["sha256"] == source["sha256"], "UPLOAD_HASH_MISMATCH")
    batch = client.request(
        "POST",
        "/accounting/import-jobs",
        command(book_id=book_id, file_id=uploaded["id"], profile=source["profile"]),
    )
    batch = wait_batch(client, batch["id"], phases=evidence["phases"])
    # Select the second sheet/header explicitly; never infer it from viewport.
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/mapping",
        command(
            expected_version=batch["version"], mapping=source["mapping"], profile=source["profile"]
        ),
    )
    page = client.request(
        "GET",
        f"/accounting/import-jobs/{batch['id']}/staging?page_size=200",
        label="staging_preview",
    )
    require(page["total"] == 1000 and len(page["items"]) == 200, "STAGING_PAGE_MISMATCH")
    require(
        page["items"][0]["source_sheet"] == "2" and page["items"][0]["source_row"] == 4,
        "SOURCE_COORDINATES_MISMATCH",
    )
    require(rows(client, book_id)["total"] == 0, "UNCONFIRMED_ROWS_VISIBLE")
    batch = validate(client, batch, evidence["phases"])
    for key in ("source_rows", "valid", "invalid"):
        require(batch["counts"][key] == source["expected"][key], "VALIDATION_COUNTS_MISMATCH")
    require(
        batch["counts"]["potential_duplicates"] == source["expected"]["duplicate_warning_rows"],
        "DUPLICATE_COUNT_MISMATCH",
    )
    issues = client.request(
        "GET", f"/accounting/import-jobs/{batch['id']}/issues?page_size=100", label="cell_issues"
    )
    expected = {
        (item["source_sheet"], item["source_row"], item["column_id"], item["code"])
        for item in source["expected_issues"]
    }
    actual = {
        (item["source_sheet"], item["source_row"], item["column_id"], item["code"])
        for item in issues["items"]
    }
    require(expected.issubset(actual), "CELL_ISSUES_MISMATCH")
    duplicates = client.request(
        "GET",
        f"/accounting/import-jobs/{batch['id']}/duplicates?page_size=100",
        label="duplicate_review",
    )
    require(duplicates["total"] == 20, "DUPLICATE_REVIEW_MISMATCH")
    source_size, downloaded_sha = client.content_hash(uploaded["id"])
    require(
        source_size == source["bytes"] and downloaded_sha == source["sha256"],
        "ORIGINAL_DOWNLOAD_MISMATCH",
    )
    evidence.update(
        {
            "book_id": book_id,
            "batch_id": batch["id"],
            "file_id": uploaded["id"],
            "first_validation": batch["counts"],
            "preview_rows": 200,
            "source_sha256": source["sha256"],
            "unknown_ack_model": "genuine_ACK_discarded_then_exact_HTTP_replay",
            "macro_scope": source["macro_fixture"],
            "unsupported_and_external_formulas": "rejected_with_source_coordinates",
        }
    )
    return batch


def mini_after_restart(client, manifest, batch, evidence):
    source = manifest["files"]["xlsm"]
    scenario = source["scenarios"]["skip_first_duplicate"]
    book_id = evidence["book_id"]
    batch = client.request("GET", f"/accounting/import-jobs/{batch['id']}")
    require(
        batch["counts"]["invalid"] == 17 and rows(client, book_id)["total"] == 0,
        "RESTART_STAGING_MISMATCH",
    )
    page = client.request("GET", f"/accounting/import-jobs/{batch['id']}/staging?page_size=200")
    skip = next(
        item for item in page["items"] if item["source_row"] == scenario["duplicate_source_row"]
    )
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/decisions",
        command(
            expected_version=batch["version"],
            all_pending_duplicates="keep",
            decisions=[{"row_id": skip["row_id"], "decision": "skip"}],
        ),
    )
    body = confirm_body(batch)
    client.request("POST", f"/accounting/import-jobs/{batch['id']}/confirm", body)
    client.request("POST", f"/accounting/import-jobs/{batch['id']}/confirm", body)
    batch = wait_batch(client, batch["id"], phases=evidence["phases"])
    evidence["first_publication"] = reconcile(
        client, book_id, scenario["first_published"], scenario["first_income"]
    )
    require(batch["counts"]["invalid"] == 17, "INVALID_ROWS_NOT_RETAINED")
    stage = client.request(
        "GET", f"/accounting/import-jobs/{batch['id']}/staging?page_size=200&status=invalid"
    )
    by_coordinate = {(item["source_sheet"], item["source_row"]): item for item in stage["items"]}
    patches = []
    with Path(source["repair_jsonl"]["path"]).open(encoding="utf-8") as stream:
        for line in stream:
            repair = json.loads(line)
            row = by_coordinate[repair["source_sheet"], repair["source_row"]]
            patches.append(
                {
                    "row_id": row["row_id"],
                    "expected_version": row["revision"],
                    "values": repair["values"],
                }
            )
    require(len(patches) == 17, "REPAIR_SOURCE_MISMATCH")
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch['id']}/patches",
        command(expected_version=batch["version"], patches=patches),
    )
    batch = validate(client, batch, evidence["phases"])
    require(batch["counts"]["eligible"] == 17, "SECOND_PASS_SELECTION_MISMATCH")
    body = confirm_body(batch)
    client.request("POST", f"/accounting/import-jobs/{batch['id']}/confirm", body)
    batch = wait_batch(client, batch["id"], phases=evidence["phases"])
    evidence["final_publication"] = reconcile(
        client, book_id, scenario["final_published"], scenario["final_income"]
    )
    require(batch["counts"]["excluded"] == 1, "EXCLUDED_DECISION_LOST")
    # Replaying an earlier confirmation must not add those published rows again.
    client.request("POST", f"/accounting/import-jobs/{batch['id']}/confirm", body)
    reconcile(client, book_id, scenario["final_published"], scenario["final_income"])
    exported = client.request("POST", f"/accounting/books/{book_id}/exports", command(format="csv"))
    started = time.perf_counter()
    while True:
        status = client.request(
            "GET", f"/accounting/exports/{exported['job_id']}", label="export_status"
        )
        if status["state"] == "COMPLETED":
            require(bool(status["file_id"]), "COMPLETED_EXPORT_WITHOUT_FILE")
            break
        require(
            status["state"] not in {"FAILED", "CANCELLED"} and time.perf_counter() - started < 60,
            "EXPORT_FAILED",
        )
        time.sleep(0.1)
    evidence["derived_export"] = client.csv_receipt(
        status["file_id"],
        manifest["book"]["columns"],
        scenario["final_published"],
        scenario["final_income"],
    )
    original_bytes, original_sha = client.content_hash(evidence["file_id"])
    require(
        original_bytes == source["bytes"]
        and original_sha == source["sha256"]
        and sha256(Path(source["path"])) == source["sha256"],
        "ORIGINAL_CHANGED",
    )
    evidence.update(
        {
            "restart_persistence": "PASS_AFTER_COMPLETED_VALIDATION",
            "native_gui": "NOT_RUN",
            "mid_parse_checkpoint_resume": "NOT_OBSERVED_BY_THIS_COMPLETED_PHASE_RESTART",
            "pending_visibility": "NOT_CLAIMED_FROM_A_SHORT_MINI_WINDOW",
            "copy_paste_edit": "SEPARATE_UI_SCENARIO",
            "final_counts": batch["counts"],
        }
    )
    return evidence


def bulk_begin(client, manifest):
    source = manifest["files"]["csv"]
    book = client.request("POST", "/accounting/books", command(**manifest["book"]))
    uploaded = client.request("POST", "/files?category=workbooks", file=Path(source["path"]))
    require(uploaded["sha256"] == source["sha256"], "UPLOAD_HASH_MISMATCH")
    batch = client.request(
        "POST",
        "/accounting/import-jobs",
        command(book_id=book["id"], file_id=uploaded["id"], profile=source["profile"]),
    )
    return book["id"], uploaded["id"], batch["id"]


class ForegroundProbe:
    """Public HTTP filter and versioned other-book edits alongside volume work."""

    def __init__(self, client, manifest, book_id):
        self.client, self.book_id = client, book_id
        self.last = 0
        self.samples = []
        self.published_count, self.published_income = 0, "0.00"
        self.pending_windows = []
        book = client.request(
            "POST",
            "/accounting/books",
            command(**(manifest["book"] | {"name": "Synthetic foreground probe"})),
        )
        self.row = client.request(
            "POST",
            f"/accounting/books/{book['id']}/rows",
            command(
                values={
                    "code": "probe-0001",
                    "day": "2026-01-07",
                    "amount": "100.00",
                    "quantity": "1.000",
                    "category": "Robusta",
                    "note": "synthetic probe",
                    "currency": "VND",
                    "warehouse": "LOCAL-01",
                }
            ),
        )

    def __call__(self, batch):
        if time.monotonic() - self.last < 1:
            return
        self.last = time.monotonic()
        filters = urllib.parse.quote(
            json.dumps([{"column_id": "amount", "op": "gte", "value": "0.00"}])
        )
        page = self.client.request(
            "GET",
            f"/accounting/books/{self.book_id}/rows?page_size=200&filters={filters}",
            label="foreground_whole_book_filter",
        )
        require(len(page["items"]) <= 200, "FOREGROUND_PAGE_UNBOUNDED")
        old_version = self.row["version"]
        self.row = self.client.request(
            "PATCH",
            f"/accounting/rows/{self.row['id']}",
            command(
                expected_version=old_version, values={"note": f"synthetic foreground {old_version}"}
            ),
            label="foreground_other_book_edit",
        )
        require(self.row["version"] == old_version + 1, "FOREGROUND_VERSION_MISMATCH")
        observation = {
            "phase": batch.get("job", {}).get("phase"),
            "batch_state": batch["state"],
            "published_filter_total": page["total"],
            "probe_version": self.row["version"],
        }
        self.samples.append(observation)
        if batch["counts"].get("pending", 0) > 0:
            summary = self.client.request(
                "GET",
                f"/accounting/books/{self.book_id}/summary?from_on=2026-01-01&through_on=2026-02-01",
                label="pending_visibility_summary",
            )
            after = self.client.request(
                "GET", f"/accounting/import-jobs/{batch['id']}", label="pending_visibility_recheck"
            )
            stable = after["counts"].get("pending", 0) > 0 and after["counts"].get(
                "published_rows", 0
            ) == batch["counts"].get("published_rows", 0)
            if stable:
                income = summary["totals"].get("VND", {}).get("income", "0.00")
                require(
                    page["total"] == self.published_count and income == self.published_income,
                    "PENDING_ROWS_VISIBLE",
                )
            self.pending_windows.append(
                {
                    "pending_before": batch["counts"]["pending"],
                    "pending_after": after["counts"].get("pending", 0),
                    "status": "PASS" if stable else "WINDOW_CROSSED",
                    "export_during_pending": "NOT_MEASURED",
                }
            )

    def evidence(self):
        return {
            "samples": self.samples,
            "pending_windows": self.pending_windows,
            "pending_visibility": "PASS"
            if any(item["status"] == "PASS" for item in self.pending_windows)
            else "NOT_MEASURED",
            "scope": "direct HTTP; shared host; mixed publication phases, not GUI latency",
        }


def bulk_finish(client, manifest, evidence, probe=None):
    """Future slot-gated volume path; public API only and bounded pages/patches."""
    source, phases = manifest["files"]["csv"], evidence["phases"]
    book_id, batch_id = evidence["book_id"], evidence["batch_id"]
    batch = client.request("GET", f"/accounting/import-jobs/{batch_id}")
    if batch["state"] in {"RECOVERABLE", "CANCELLED", "FAILED"}:
        client.request("POST", f"/accounting/import-jobs/{batch_id}/resume", command())
    batch = wait_batch(client, batch_id, phases=phases, timeout=86400, probe=probe)
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch_id}/mapping",
        command(
            expected_version=batch["version"], mapping=source["mapping"], profile=source["profile"]
        ),
    )
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch_id}/validate",
        command(expected_version=batch["version"]),
    )
    batch = wait_batch(client, batch_id, phases=phases, timeout=86400, probe=probe)
    for name in ("source_rows", "valid", "invalid"):
        require(batch["counts"][name] == source["expected"][name], "VOLUME_VALIDATION_MISMATCH")
    require(rows(client, book_id)["total"] == 0, "UNCONFIRMED_ROWS_VISIBLE")
    batch = client.request(
        "POST",
        f"/accounting/import-jobs/{batch_id}/decisions",
        command(expected_version=batch["version"], all_pending_duplicates="keep", decisions=[]),
    )
    first_body = confirm_body(batch)
    client.request("POST", f"/accounting/import-jobs/{batch_id}/confirm", first_body)
    client.request("POST", f"/accounting/import-jobs/{batch_id}/confirm", first_body)
    batch = wait_batch(client, batch_id, phases=phases, timeout=86400, probe=probe)
    expected = source["scenarios"]["keep_all"]
    evidence["first_publication"] = reconcile(
        client, book_id, expected["first_published"], expected["first_income"]
    )
    if probe is not None:
        probe.published_count = expected["first_published"]
        probe.published_income = expected["first_income"]
    # Invalid data is sparse by definition. Read repairs as a stream; only one
    # page of staged DTOs and one <=200-row patch request are held at a time.
    with Path(source["repair_jsonl"]["path"]).open(encoding="utf-8") as repairs:
        page_number = 1
        while True:
            page = client.request(
                "GET",
                f"/accounting/import-jobs/{batch_id}/staging?page_size=200&status=invalid&page={page_number}",
            )
            if not page["items"]:
                break
            patches = []
            for row in page["items"]:
                repair = json.loads(next(repairs))
                require(row["source_row"] == repair["source_row"], "VOLUME_REPAIR_ORDER_MISMATCH")
                patches.append(
                    {
                        "row_id": row["row_id"],
                        "expected_version": row["revision"],
                        "values": repair["values"],
                    }
                )
            batch = client.request(
                "POST",
                f"/accounting/import-jobs/{batch_id}/patches",
                command(expected_version=batch["version"], patches=patches),
            )
            page_number += 1
    client.request(
        "POST",
        f"/accounting/import-jobs/{batch_id}/validate",
        command(expected_version=batch["version"]),
    )
    batch = wait_batch(client, batch_id, phases=phases, timeout=86400, probe=probe)
    require(
        batch["counts"]["eligible"] == source["expected"]["invalid"], "VOLUME_SECOND_PASS_MISMATCH"
    )
    client.request("POST", f"/accounting/import-jobs/{batch_id}/confirm", confirm_body(batch))
    batch = wait_batch(client, batch_id, phases=phases, timeout=86400, probe=probe)
    evidence["final_publication"] = reconcile(
        client, book_id, expected["final_published"], expected["final_income"]
    )
    if probe is not None:
        probe.published_count = expected["final_published"]
        probe.published_income = expected["final_income"]
        probe.last = 0
        probe(batch)
        evidence["foreground"] = probe.evidence()
    exported = client.request("POST", f"/accounting/books/{book_id}/exports", command(format="csv"))
    deadline = time.monotonic() + 86400
    while time.monotonic() < deadline:
        status = client.request(
            "GET", f"/accounting/exports/{exported['job_id']}", label="export_status"
        )
        if status["state"] == "COMPLETED":
            require(bool(status["file_id"]), "COMPLETED_EXPORT_WITHOUT_FILE")
            evidence["derived_export"] = client.csv_receipt(
                status["file_id"],
                manifest["book"]["columns"],
                expected["final_published"],
                expected["final_income"],
            )
            break
        require(status["state"] not in {"FAILED", "CANCELLED"}, "VOLUME_EXPORT_FAILED")
        time.sleep(0.5)
    else:
        raise AcceptanceError("VOLUME_EXPORT_TIMEOUT")
    size, digest = client.content_hash(evidence["file_id"])
    require(
        size == source["bytes"]
        and digest == source["sha256"]
        and sha256(Path(source["path"])) == digest,
        "ORIGINAL_CHANGED",
    )
    evidence["final_counts"] = batch["counts"]
    return evidence
