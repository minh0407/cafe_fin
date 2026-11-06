"""Opt-in XLSX parser/resource benchmark. Never run concurrently with other benchmarks.

Creates synthetic data/results outside Git. This measures parser projection and
re-read/skip recovery, not application import, validation, publication or UI.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cafe_fin.accounting import parsers
from cafe_fin.accounting.exporting import write_xlsx

MAX_DATA_ROWS = 1_048_575
PAGE_ROWS = 500
PROGRESS_ROWS = 65_536
SAMPLE_SECONDS = 0.1
COLUMNS = [
    {"id": "code", "name": "Mã", "kind": "text"},
    {"id": "day", "name": "Ngày", "kind": "date"},
    {"id": "count", "name": "Số lượng", "kind": "integer", "scale": 0},
    {"id": "amount", "name": "Tiền", "kind": "money", "scale": 2},
    {"id": "quantity", "name": "Khối lượng", "kind": "decimal", "scale": 3},
    {"id": "category", "name": "Phân loại", "kind": "choice"},
    {"id": "formula_result", "name": "Giá trị công thức đã tính", "kind": "formula", "scale": 2},
    {"id": "note", "name": "Ghi chú", "kind": "text"},
]


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def record_for(index):
    cents, milli = 10_000 + index % 100_000, 1000 + index % 1000
    return {
        "code": f"{index:012d}",
        "day": (date(2026, 1, 1) + timedelta(days=index % 28)).isoformat(),
        "count": str(index),
        "amount": f"{cents // 100}.{cents % 100:02d}",
        "quantity": f"{milli // 1000}.{milli % 1000:03d}",
        "category": "Robusta" if index % 2 else "Arabica",
        "formula_result": f"{9_007_199_254_740_993 + index % 97}.{index % 100:02d}",
        "note": "=literal source text"
        if index % 113 == 0
        else f'Cà phê tổng hợp {index:07d}, "đợt"\nxuống dòng',
    }


def expected_values(record):
    # Independently specify the source projection expected from this derived file.
    # The exporter uses the 1900 system and emits exact text above 15 digits.
    serial = (date.fromisoformat(record["day"]) - date(1899, 12, 31)).days + 1
    return {
        "A": record["code"],
        "B": str(serial),
        "C": record["count"],
        "D": record["amount"],
        "E": record["quantity"],
        "F": record["category"],
        "G": record["formula_result"],
        "H": record["note"],
    }


def memory_counters():
    if os.name == "nt":

        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                    "PrivateUsage",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel, psapi = (
            ctypes.WinDLL("kernel32", use_last_error=True),
            ctypes.WinDLL("psapi", use_last_error=True),
        )
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "rss_bytes": counters.WorkingSetSize,
            "os_lifetime_peak_rss_bytes": counters.PeakWorkingSetSize,
            "private_bytes": counters.PrivateUsage,
            "source": "Windows GetProcessMemoryInfo",
        }
    if Path("/proc/self/statm").exists():
        return {
            "rss_bytes": int(Path("/proc/self/statm").read_text().split()[1])
            * os.sysconf("SC_PAGE_SIZE"),
            "source": "/proc/self/statm (non-Windows smoke only)",
        }
    return {"rss_bytes": None, "source": "unavailable"}


def hardware_inventory(root):
    result = {
        "cpu_identifier": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor(),
        "cpu_logical": os.cpu_count(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "volume": root.anchor,
        "free_disk_before_bytes": shutil.disk_usage(root.parent).free,
    }
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total_physical",
                    "available_physical",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "available_extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx(
            ctypes.byref(status)
        ):
            result["physical_ram_bytes"], result["available_ram_before_bytes"] = (
                status.total_physical,
                status.available_physical,
            )
        command = "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size | ConvertTo-Json -Compress"
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            result["disk_inventory"] = (
                json.loads(completed.stdout)
                if completed.returncode == 0 and completed.stdout.strip()
                else "UNAVAILABLE"
            )
        except (OSError, ValueError, subprocess.TimeoutExpired):
            result["disk_inventory"] = "UNAVAILABLE"
        result["disk_inventory_scope"] = (
            "Host physical-disk inventory; does not infer which device backs a virtual/mounted volume."
        )
    return result


def source_hashes(repository):
    paths = [
        Path(__file__).resolve(),
        repository / "backend/cafe_fin/accounting/parsers.py",
        repository / "backend/cafe_fin/accounting/exporting.py",
    ]
    return {path.relative_to(repository).as_posix(): digest_file(path) for path in paths}


class Measurements:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.lock, self.stop = threading.RLock(), threading.Event()
        self.phase_name = "startup"
        self.result = {
            "status": "RUNNING",
            "phases": {},
            "progress": {},
            "resource_samples": {},
            "process_id": os.getpid(),
            "process_roles": "Exporter/parser/verifier/sampler share one process; no application DB, API, worker or UI.",
        }
        self.thread = threading.Thread(
            target=self.sample_loop, name="xlsx-benchmark-resources", daemon=True
        )

    def save(self):
        with self.lock:
            encoded = json.dumps(self.result, ensure_ascii=False, indent=2, allow_nan=False)
            temporary = self.output.with_suffix(".json.part")
            temporary.write_text(encoded, encoding="utf-8")
            temporary.replace(self.output)

    def progress(self, phase, **values):
        with self.lock:
            self.result["progress"][phase] = values

    def sample(self):
        memory = memory_counters()
        sizes = {"total_file_bytes": 0, "parser_temp_bytes": 0}
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    size = path.stat().st_size
                    sizes["total_file_bytes"] += size
                    if path.is_relative_to(self.root / "parser-temp"):
                        sizes["parser_temp_bytes"] += size
            except FileNotFoundError:
                continue
        with self.lock:
            sample = self.result["resource_samples"].setdefault(self.phase_name, {"samples": 0})
            sample["samples"] += 1
            sample["memory_source"] = memory.pop("source")
            for name, value in memory.items() | sizes.items():
                if value is not None:
                    sample["peak_" + name] = max(sample.get("peak_" + name, 0), value)

    def sample_loop(self):
        last_save = 0.0
        try:
            while not self.stop.is_set():
                self.sample()
                if time.monotonic() - last_save >= 1:
                    self.save()
                    last_save = time.monotonic()
                self.stop.wait(SAMPLE_SECONDS)
        except Exception as exc:
            with self.lock:
                self.result["sampling_failure"] = type(exc).__name__

    @contextmanager
    def phase(self, name):
        self.phase_name = name
        self.sample()
        started = time.perf_counter()
        try:
            yield
        finally:
            seconds = time.perf_counter() - started
            self.sample()
            with self.lock:
                self.result["phases"][name] = {"seconds": seconds}
            self.save()


def run(args, measurements):
    fixture = args.root / "synthetic-max-worksheet.xlsx"
    checkpoint = max(0, args.rows - min(1000, args.rows))
    expected_full, expected_tail = hashlib.sha256(), hashlib.sha256()
    endpoints = {}
    max_string_chars = 0

    def rows():
        nonlocal max_string_chars
        for index in range(1, args.rows + 1):
            record = record_for(index)
            values = expected_values(record)
            encoded = canonical({"source_row": index + 1, "values": values}) + b"\n"
            expected_full.update(encoded)
            if index > checkpoint:
                expected_tail.update(encoded)
            if index in (1, args.rows):
                endpoints[str(index)] = {
                    "source_row": index + 1,
                    "projection_sha256": hashlib.sha256(encoded).hexdigest(),
                    "code": record["code"],
                    "date_serial": values["B"],
                    "high_precision_text": values["G"],
                }
            max_string_chars = max(max_string_chars, *(len(value) for value in record.values()))
            if index % PROGRESS_ROWS == 0 or index == args.rows:
                measurements.progress("generate", data_rows=index, expected_data_rows=args.rows)
            yield record

    with measurements.phase("generate_streaming_fixture_and_expected_hash"):
        count = write_xlsx(fixture, COLUMNS, rows())
        if count != args.rows:
            raise AssertionError("Generator count mismatch")
    with measurements.phase("source_sha256_before"):
        before = digest_file(fixture)
    with zipfile.ZipFile(fixture) as archive:
        inventory = archive.infolist()
        measurements.result["zip"] = {
            "entries": len(inventory),
            "unpacked_bytes": sum(entry.file_size for entry in inventory),
            "compressed_bytes": fixture.stat().st_size,
            "max_entry_expansion_ratio": max(
                entry.file_size / max(entry.compress_size, 1) for entry in inventory
            ),
            "shared_strings_present": "xl/sharedStrings.xml" in archive.namelist(),
        }
    with measurements.phase("manifest_actual_all_sheet_dimensions"):
        manifest = parsers.manifest(fixture, fixture.name)
        selected = next(sheet for sheet in manifest["sheets"] if sheet["id"] == "1")
        if (
            len(manifest["sheets"]) != 2
            or selected["max_row"] != args.rows + 1
            or selected["max_column"] != 8
        ):
            raise AssertionError("Actual worksheet bounds/notice-sheet reconciliation failed")
        if selected["stored_row_count"] != args.rows + 1 or not selected["dimensions_verified"]:
            raise AssertionError("Worksheet stored rows were not verified")
        measurements.result["manifest"] = manifest
    profile = {
        "sheet_id": "1",
        "header_row": 1,
        "start_row": 2,
        "skip_blank": True,
        "hidden_rows": "include",
        "merged_cells": "reject",
    }
    actual_full, actual_tail = hashlib.sha256(), hashlib.sha256()
    count = cells = page_rows = pages = 0
    actual_endpoints = {}
    with measurements.phase("parse_all_rows_verify_hash_and_metadata"):
        for row in parsers.iter_rows(fixture, fixture.name, profile):
            count += 1
            cells += len(row.values)
            if row.sheet_id != "1" or row.source_row != count + 1 or len(row.values) != 8:
                raise AssertionError("Source identity/cell-count mismatch")
            numeric = row.metadata.get("numeric_cells", {})
            if set(numeric) != {"B", "C", "D", "E"} or any(
                numeric[column] != row.values[column] for column in numeric
            ):
                raise AssertionError("Native numeric precision metadata mismatch")
            if row.metadata["date_cells"] != {
                "B": {"epoch": "1900", "excel_serial": row.values["B"]}
            }:
                raise AssertionError("Native Excel date metadata mismatch")
            if row.formulas or "G" in numeric:
                raise AssertionError(
                    "Derived high-precision formula result must remain inert exact text"
                )
            encoded = canonical({"source_row": row.source_row, "values": row.values}) + b"\n"
            actual_full.update(encoded)
            if count in (1, args.rows):
                actual_endpoints[str(count)] = {
                    "source_row": row.source_row,
                    "projection_sha256": hashlib.sha256(encoded).hexdigest(),
                    "code": row.values["A"],
                    "date_serial": row.values["B"],
                    "high_precision_text": row.values["G"],
                }
            page_rows += 1
            if page_rows == PAGE_ROWS:
                pages += 1
                page_rows = 0
            if count % PROGRESS_ROWS == 0 or count == args.rows:
                measurements.progress(
                    "parse", data_rows=count, cells=cells, source_row=row.source_row
                )
        if page_rows:
            pages += 1
        if (
            count != args.rows
            or cells != args.rows * 8
            or actual_full.digest() != expected_full.digest()
            or actual_endpoints != endpoints
        ):
            raise AssertionError("Full source projection count/hash/endpoint reconciliation failed")
    measurements.result["projection"] = {
        "data_rows": count,
        "data_cells": cells,
        "header_rows": 1,
        "full_projection_sha256": actual_full.hexdigest(),
        "expected_projection_sha256": expected_full.hexdigest(),
        "endpoints": actual_endpoints,
        "max_string_chars": max_string_chars,
        "page_rows": PAGE_ROWS,
        "conceptual_pages": pages,
        "final_page_rows": page_rows or min(PAGE_ROWS, args.rows),
        "paging_scope": "Bounded counters only; no application preview endpoint or UI was benchmarked.",
    }
    visited = skipped = emitted = 0
    first_tail_seconds = None
    with measurements.phase("resume_full_reread_then_skip_near_end"):
        started = time.perf_counter()
        for row in parsers.iter_rows(fixture, fixture.name, profile):
            visited += 1
            if row.source_row <= checkpoint + 1:
                skipped += 1
            else:
                if first_tail_seconds is None:
                    first_tail_seconds = time.perf_counter() - started
                emitted += 1
                actual_tail.update(
                    canonical({"source_row": row.source_row, "values": row.values}) + b"\n"
                )
            if visited % PROGRESS_ROWS == 0 or visited == args.rows:
                measurements.progress(
                    "resume", visited_rows=visited, skipped_rows=skipped, emitted_rows=emitted
                )
        if (
            visited != args.rows
            or skipped != checkpoint
            or emitted != args.rows - checkpoint
            or actual_tail.digest() != expected_tail.digest()
        ):
            raise AssertionError("Resume re-read/skip count/hash mismatch")
    measurements.result["resume"] = {
        "kind": "Parser re-read from beginning; skip stable source coordinates",
        "checkpoint_data_rows": checkpoint,
        "checkpoint_source_row": checkpoint + 1,
        "visited_rows": visited,
        "skipped_rows": skipped,
        "emitted_rows": emitted,
        "first_emitted_row_seconds": first_tail_seconds,
        "tail_sha256": actual_tail.hexdigest(),
        "expected_tail_sha256": expected_tail.hexdigest(),
        "durable_job_resume_tested": False,
        "constant_time_seek": False,
    }
    with measurements.phase("source_sha256_after"):
        after = digest_file(fixture)
        if before != after:
            raise AssertionError("Original synthetic source bytes changed")
    measurements.result["source"] = {
        "path": str(fixture),
        "sha256_before": before,
        "sha256_after": after,
        "bytes_unchanged": True,
        "bytes": fixture.stat().st_size,
    }
    measurements.result["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=MAX_DATA_ROWS)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.rows <= MAX_DATA_ROWS:
        parser.error("--rows must be between 1 and 1048575 (plus one header row)")
    if args.root is None:
        parent = Path(tempfile.mkdtemp(prefix="cafe-fin-xlsx-benchmark-"))
        args.root = parent / "synthetic-data"
    args.root = args.root.resolve()
    args.output = (args.output or args.root.with_name(args.root.name + "-result.json")).resolve()
    repository = Path(__file__).resolve().parents[2]
    if args.root.is_relative_to(repository) or args.output.is_relative_to(repository):
        parser.error("All generated fixtures/results must stay outside the repository")
    if (
        args.root.exists() and (not args.root.is_dir() or any(args.root.iterdir()))
    ) or args.output.exists():
        parser.error("Use a fresh empty root and a new output path; no existing data is deleted")
    args.root.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    (args.root / "parser-temp").mkdir()
    previous_temp = tempfile.tempdir
    tempfile.tempdir = str(args.root / "parser-temp")
    measurements = Measurements(args.root, args.output)
    measurements.result.update(
        {
            "benchmark": "xlsx-parser-max-worksheet-v1",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "requested_rows": args.rows,
            "worksheet_limit_case": args.rows == MAX_DATA_ROWS,
            "hardware": hardware_inventory(args.root),
            "runtime": {
                "python": sys.version,
                "sqlite": sqlite3.sqlite_version,
                "packages": {
                    name: importlib.metadata.version(name) for name in ("openpyxl", "defusedxml")
                },
            },
            "settings": {
                "columns": COLUMNS,
                "selected_sheet_id": "1",
                "header_rows": 1,
                "parser_columns_limit": parsers.MAX_COLUMNS,
                "sample_seconds": SAMPLE_SECONDS,
                "progress_rows": PROGRESS_ROWS,
                "simulated_page_rows": PAGE_ROWS,
                "known_invalid_rows": 0,
                "duplicate_extra_rows": 0,
                "blank_cells": 0,
                "stored_executable_formulas": 0,
            },
            "method": {
                "timing_clock": "time.perf_counter",
                "parse_timing_includes": "Selected-sheet structural prescan, value parsing, exact canonical hash, coordinate/numeric/date checks and counters",
                "generate_timing_includes": "Streaming exporter plus independent expected projection/tail hashing",
                "cache_state": "OS page cache uncontrolled; phases run sequentially in one process",
                "rss": "100 ms samples are lower bounds; Windows OS lifetime peak is cumulative, not a per-phase delta",
                "shared_strings": "NOT EXERCISED: fixture uses unique inline strings; parser creates only its empty temporary string index",
                "not_run": [
                    "Application staging/validation/dedup/publication",
                    "API/worker/UI responsiveness",
                    "Shared-string-heavy workbook",
                    "Actual process crash/restart",
                ],
                "concurrency": "Run only after CSV benchmarks finish; no other benchmark workload is launched by this script",
            },
        }
    )
    start_hashes = source_hashes(repository)
    measurements.result["code_provenance"] = {
        "source_sha256_start": start_hashes,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "worktree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=repository, text=True
            ).strip()
        ),
        "immutable_release_evidence": False,
    }
    measurements.save()
    measurements.thread.start()
    started, exit_code = time.perf_counter(), 0
    try:
        run(args, measurements)
    except Exception as exc:
        measurements.result["status"] = "FAIL"
        measurements.result["failure"] = {
            "type": type(exc).__name__,
            "code": getattr(exc, "code", "XLSX_BENCHMARK_FAILURE"),
        }
        exit_code = 1
    finally:
        measurements.stop.set()
        measurements.thread.join(timeout=5)
        measurements.result["total_seconds"] = time.perf_counter() - started
        measurements.result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        end_hashes = source_hashes(repository)
        changed = sorted(name for name in start_hashes if start_hashes[name] != end_hashes[name])
        measurements.result["code_provenance"].update(
            {"source_sha256_end": end_hashes, "files_changed_during_run": changed}
        )
        if changed or measurements.thread.is_alive() or measurements.result.get("sampling_failure"):
            measurements.result["status"] = "FAIL"
            exit_code = 1
        measurements.result["free_disk_after_bytes"] = shutil.disk_usage(args.root).free
        measurements.sample()
        measurements.save()
        tempfile.tempdir = previous_temp
    print(
        json.dumps(
            {"status": measurements.result["status"], "rows": args.rows, "output": str(args.output)}
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
