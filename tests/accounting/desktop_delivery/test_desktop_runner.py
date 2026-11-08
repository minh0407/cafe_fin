"""Controller guards only: synthetic bytes are never launched as executables."""

import csv
import json
import urllib.request
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cafe_fin.accounting.parsers import iter_rows
from cafe_fin.accounting.validation import normalize_value
from cafe_fin.core.errors import CoreError

from . import runner
from .bulk_fixture import generate_bulk_csv
from .measurements import latency_summary, percentile, resource_summary
from .transport import AcceptanceError, NoRedirect, Sidecar, artifact_identity, sha256

SOURCE_SHA = "a" * 40


def _write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _candidate(tmp_path):
    executable = tmp_path / "synthetic-never-execute.exe"
    executable.write_bytes(b"SYNTHETIC NON-EXECUTABLE ARTIFACT BYTES\n")
    receipt = {
        "source_sha": SOURCE_SHA,
        "sidecar": {
            "path": str(executable),
            "sha256": sha256(executable),
            "bytes": executable.stat().st_size,
        },
    }
    return _write_json(tmp_path / "candidate.json", receipt), receipt


def _slot(tmp_path, **changes):
    now = datetime.now(timezone.utc)
    receipt = {
        "granted_at_utc": (now - timedelta(minutes=5)).isoformat(),
        "expires_at_utc": (now + timedelta(minutes=5)).isoformat(),
        "approved_source_sha": SOURCE_SHA,
        "workload_ids": ["csv-50k"],
        "evidence_modes": ["frozen-sidecar"],
        "slot_id": "synthetic-slot-no-run",
        "coordinator_decision_ref": "synthetic-test-decision",
        "declared_host_scope": "shared_unpinned",
    }
    receipt.update(changes)
    return _write_json(tmp_path / "slot.json", receipt)


def _assert_error(code, function, *args):
    with pytest.raises(AcceptanceError) as error:
        function(*args)
    assert error.value.code == code


def test_artifact_identity_verifies_declared_source_and_actual_bytes(tmp_path, monkeypatch):
    manifest, receipt = _candidate(tmp_path)

    def forbid_launch(*args, **kwargs):
        pytest.fail("artifact validation must never launch candidate bytes")

    monkeypatch.setattr("subprocess.Popen", forbid_launch)
    result = artifact_identity(manifest, SOURCE_SHA)
    assert result["source_sha"] == SOURCE_SHA
    assert result["sidecar"] == receipt["sidecar"]
    assert result["manifest_sha256"] == sha256(manifest)
    assert result["provenance"] == "coordinator_source_declaration_and_verified_file_digest"
    assert result["gui_native"] == result["clean_windows"] == "NOT_RUN"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("source_sha", "b" * 40, "ARTIFACT_SOURCE_MISMATCH"),
        ("path", "synthetic-relative.exe", "LOCAL_ABSOLUTE_ARTIFACT_REQUIRED"),
        ("sha256", "b" * 64, "ARTIFACT_HASH_MISMATCH"),
        ("sha256", "not-a-digest", "ARTIFACT_HASH_REQUIRED"),
        ("bytes", 1, "ARTIFACT_SIZE_MISMATCH"),
        ("bytes", True, "ARTIFACT_SIZE_MISMATCH"),
    ],
)
def test_artifact_identity_rejects_mismatched_or_nonlocal_claims(tmp_path, field, value, code):
    manifest, receipt = _candidate(tmp_path)
    target = receipt if field == "source_sha" else receipt["sidecar"]
    target[field] = value
    _write_json(manifest, receipt)
    _assert_error(code, artifact_identity, manifest, SOURCE_SHA)


def test_artifact_identity_detects_same_size_post_receipt_mutation(tmp_path):
    manifest, receipt = _candidate(tmp_path)
    executable = Path(receipt["sidecar"]["path"])
    original = executable.read_bytes()
    executable.write_bytes(b"X" + original[1:])
    assert executable.stat().st_size == receipt["sidecar"]["bytes"]
    _assert_error("ARTIFACT_HASH_MISMATCH", artifact_identity, manifest, SOURCE_SHA)


def test_slot_is_candidate_workload_mode_and_time_bound_and_records_digest(tmp_path):
    receipt = _slot(tmp_path)
    result = runner.verify_slot(receipt, "csv-50k", "frozen-sidecar", SOURCE_SHA)
    assert result == {
        "slot_id": "synthetic-slot-no-run",
        "receipt_sha256": sha256(receipt),
        "declared_host_scope": "shared_unpinned",
    }
    _assert_error(
        "COORDINATOR_LARGE_SLOT_REQUIRED",
        runner.verify_slot,
        None,
        "csv-50k",
        "frozen-sidecar",
        SOURCE_SHA,
    )
    for workload, mode, source in [
        ("csv-500k", "frozen-sidecar", SOURCE_SHA),
        ("csv-50k", "source", SOURCE_SHA),
        ("csv-50k", "frozen-sidecar", "b" * 40),
    ]:
        _assert_error(
            "COORDINATOR_SLOT_INVALID", runner.verify_slot, receipt, workload, mode, source
        )


@pytest.mark.parametrize("invalid", ["expired", "future", "wrong-source", "missing-decision"])
def test_bad_slot_rejected_before_any_output_or_fixture_creation(tmp_path, monkeypatch, invalid):
    manifest, _ = _candidate(tmp_path)
    now = datetime.now(timezone.utc)
    changes = {
        "expired": {"expires_at_utc": (now - timedelta(minutes=1)).isoformat()},
        "future": {"granted_at_utc": (now + timedelta(minutes=1)).isoformat()},
        "wrong-source": {"approved_source_sha": "b" * 40},
        "missing-decision": {"coordinator_decision_ref": ""},
    }[invalid]
    receipt = _slot(tmp_path, **changes)
    _run_rejected(
        tmp_path,
        monkeypatch,
        manifest,
        receipt,
        mode="frozen-sidecar",
        code="COORDINATOR_SLOT_INVALID",
    )


def _run_rejected(tmp_path, monkeypatch, manifest=None, slot=None, *, mode, code):
    output = tmp_path / "must-not-create" / "output"

    def forbid_work(*args, **kwargs):
        pytest.fail("rejected workload must not generate fixtures or launch a sidecar")

    def git_metadata(command, **kwargs):
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SOURCE_SHA
        return "" if kwargs.get("text") else b""

    monkeypatch.setattr(runner.subprocess, "check_output", git_metadata)
    monkeypatch.setattr(runner, "generate_bulk_csv", forbid_work)
    monkeypatch.setattr(runner, "generate_fixture_kit", forbid_work)
    monkeypatch.setattr(runner, "Sidecar", forbid_work)
    args = Namespace(
        mode=mode,
        workload="csv-50k",
        output_root=output,
        candidate_manifest=manifest,
        expected_source_sha=SOURCE_SHA,
        slot_receipt=slot,
    )
    _assert_error(code, runner.run, args)
    assert not output.parent.exists()


def test_large_source_rejected_before_output_or_fixture_creation(tmp_path, monkeypatch):
    _run_rejected(tmp_path, monkeypatch, mode="source", code="LARGE_PACKAGED_CANDIDATE_REQUIRED")


def test_packaged_large_missing_slot_rejected_before_output_creation(tmp_path, monkeypatch):
    manifest, _ = _candidate(tmp_path)
    _run_rejected(
        tmp_path,
        monkeypatch,
        manifest,
        mode="frozen-sidecar",
        code="COORDINATOR_LARGE_SLOT_REQUIRED",
    )


def test_bulk_mini_exact_counts_repairs_and_source_hash_are_independently_verified(tmp_path):
    manifest = generate_bulk_csv(tmp_path / "mini", 1000)
    source = manifest["files"]["csv"]
    path = Path(source["path"])
    assert path.stat().st_size == source["bytes"]
    assert sha256(path) == source["sha256"]
    with Path(source["repair_jsonl"]["path"]).open(encoding="utf-8") as stream:
        repairs = [json.loads(line) for line in stream]
    assert repairs == [{"source_sheet": "csv", "source_row": 1001, "values": {"amount": "110.00"}}]
    assert sha256(Path(source["repair_jsonl"]["path"])) == source["repair_jsonl"]["sha256"]
    repairs_by_row = {repair["source_row"]: repair["values"] for repair in repairs}
    money_column = next(
        column for column in manifest["book"]["columns"] if column["id"] == "amount"
    )
    valid = invalid = first_cents = final_cents = 0
    fingerprints = {}
    for index, row in enumerate(iter_rows(path, path.name, source["profile"]), start=1):
        assert index <= 1000
        assert row.source_row == index + 1
        if index <= 2:
            assert row.values["A"] == "000000000001"
        fingerprints.setdefault(tuple(row.values.items()), 0)
        fingerprints[tuple(row.values.items())] += 1
        try:
            _, cents = normalize_value(row.values["C"], money_column)
            assert type(cents) is int
            valid += 1
            first_cents += cents
        except CoreError as error:
            assert error.code == "INVALID_DECIMAL"
            invalid += 1
            _, cents = normalize_value(repairs_by_row[row.source_row]["amount"], money_column)
        final_cents += cents
    assert index == 1000
    assert (valid, invalid) == (999, 1)
    assert sum(count for count in fingerprints.values() if count > 1) == 2
    assert source["expected"] == {
        "source_rows": 1000,
        "valid": 999,
        "invalid": 1,
        "duplicate_warning_rows": 2,
    }
    assert (first_cents, final_cents) == (10_489_499, 10_500_499)
    scenario = source["scenarios"]["keep_all"]
    assert scenario == {
        "first_published": 999,
        "final_published": 1000,
        "first_income": "104894.99",
        "final_income": "105004.99",
    }
    assert sha256(path) == source["sha256"]
    with path.open(encoding="utf-8-sig", newline="") as stream:
        assert sum(1 for _ in csv.reader(stream)) == 1001


def test_sidecar_http_constructor_ignores_proxy_environment_and_refuses_redirects(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HTTP_PROXY", "http://synthetic.invalid:1234")
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic.invalid:1234")

    def forbid_proxy_discovery():
        pytest.fail("local acceptance transport must not inherit proxy discovery")

    monkeypatch.setattr(urllib.request, "getproxies", forbid_proxy_discovery)
    client = Sidecar(["never-launch"], tmp_path, tmp_path / "never-created")
    assert client.process is None
    assert any(isinstance(handler, NoRedirect) for handler in client.opener.handlers)
    assert (
        NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://synthetic.invalid")
        is None
    )
    assert not client.data_root.exists()


def test_latency_percentiles_empty_singleton_interpolation_and_grouping():
    assert percentile([], 0.95) is None
    assert percentile([7], 0.95) == 7
    values = [9, 1, 5]
    assert percentile(values, 0) == 1
    assert percentile(values, 1) == 9
    assert percentile(values, 0.5) == 5
    assert percentile(values, 0.95) == pytest.approx(8.6)
    assert values == [9, 1, 5]
    assert latency_summary([]) == {}
    summary = latency_summary(
        [
            {"label": "page", "seconds": 1},
            {"label": "page", "seconds": 3},
            {"label": "export", "seconds": 9},
        ]
    )
    assert summary["page"] == {"count": 2, "p50_seconds": 2, "p95_seconds": 2.9, "max_seconds": 3}
    assert summary["export"]["count"] == 1


def _checkpoint(parsed, state, *, batch_id="synthetic-batch", job_id="synthetic-job"):
    return {"id": batch_id, "job": {"id": job_id, "state": state, "counts": {"parsed": parsed}}}


@pytest.mark.parametrize(
    ("parsed_after", "state_after", "expected"),
    [
        (1000, "COMPLETED", "WINDOW_MISSED"),
        (600, "COMPLETED", "WINDOW_MISSED"),
        (600, "RECOVERABLE", "DURABLE_PARTIAL_OBSERVED"),
        (750, "RECOVERABLE", "DURABLE_PARTIAL_OBSERVED"),
        (0, "RECOVERABLE", "WINDOW_MISSED"),
        (500, "RECOVERABLE", "WINDOW_MISSED"),
    ],
)
def test_checkpoint_reports_only_durable_partial_after_restart(parsed_after, state_after, expected):
    observation = runner.checkpoint_observation(
        _checkpoint(600, "RUNNING"), _checkpoint(parsed_after, state_after), 1000
    )
    assert observation["status"] == expected
    assert observation["parsed_before_exit"] == 600
    assert observation["parsed_after_restart"] == parsed_after
    assert observation["job_state_after_restart"] == state_after
    assert observation["same_batch_and_job"] is True
    assert observation["scope"] == "owned graceful stop; not crash/power-loss evidence"


@pytest.mark.parametrize("change", [{"job_id": "different-job"}, {"batch_id": "different-batch"}])
def test_checkpoint_rejects_changed_job_or_batch_identity(change):
    _assert_error(
        "RESTART_JOB_IDENTITY_CHANGED",
        runner.checkpoint_observation,
        _checkpoint(600, "RUNNING"),
        _checkpoint(600, "RECOVERABLE", **change),
        1000,
    )


def _process(pid, created, rss, private, os_peak, cpu):
    return {
        "pid": pid,
        "creation_filetime_100ns": created,
        "executable": "synthetic.exe",
        "image_path": "synthetic-never-launch.exe",
        "rss_bytes": rss,
        "private_bytes": private,
        "os_peak_rss_bytes": os_peak,
        "cpu_seconds_since_process_start": cpu,
    }


def test_resource_summary_separates_pid_reuse_and_preserves_process_peaks_and_cpu_deltas():
    samples = [
        {
            "disk": {"database_bytes": 100, "wal_bytes": 80},
            "processes": [
                _process(41, 1000, 300, 200, 350, 10),
                _process(42, 2000, 700, 600, 800, None),
            ],
        },
        {
            "disk": {"database_bytes": 120, "wal_bytes": 20},
            "processes": [
                _process(41, 1000, 400, 180, 500, 13),
                _process(42, 2000, 650, 620, 810, None),
            ],
        },
        {
            "disk": {"database_bytes": 110, "wal_bytes": 0},
            "processes": [
                _process(41, 3000, 50, 40, 60, 1),
            ],
        },
        {
            "disk": {"database_bytes": 110, "wal_bytes": 0},
            "processes": [
                _process(41, 3000, 45, 42, 65, 2),
            ],
        },
    ]
    summary = resource_summary(samples)
    assert set(summary) == {"processes", "disk_sampled_peaks"}
    assert summary["disk_sampled_peaks"] == {"database_bytes": 120, "wal_bytes": 80}
    processes = {(p["pid"], p["creation_filetime_100ns"]): p for p in summary["processes"]}
    assert set(processes) == {(41, 1000), (42, 2000), (41, 3000)}
    original, reused, unknown = processes[41, 1000], processes[41, 3000], processes[42, 2000]
    assert (
        original["rss_peak_sampled_bytes"],
        original["private_peak_sampled_bytes"],
        original["os_peak_rss_bytes"],
    ) == (400, 200, 500)
    assert (
        original["cpu_first_seconds"],
        original["cpu_last_seconds"],
        original["cpu_observed_delta_seconds"],
    ) == (10, 13, 3)
    assert (
        reused["rss_peak_sampled_bytes"],
        reused["private_peak_sampled_bytes"],
        reused["os_peak_rss_bytes"],
        reused["cpu_observed_delta_seconds"],
    ) == (50, 42, 65, 1)
    assert unknown["cpu_observed_delta_seconds"] is None
    assert (unknown["rss_peak_sampled_bytes"], unknown["private_peak_sampled_bytes"]) == (700, 620)
    # No aggregate RSS/role total is reported as unique memory; each PID identity stays separate.
    assert all("rss_sum_bytes" not in item for item in summary["processes"])


def test_resource_summary_empty_input_has_no_invented_process_or_resource_usage():
    assert resource_summary([]) == {"processes": [], "disk_sampled_peaks": {}}
