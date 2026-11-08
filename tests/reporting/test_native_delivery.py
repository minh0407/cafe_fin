"""Native reporting acceptance, synthetic roots only; never verify/send to Telegram.

Run unchanged against source or CAFE_FIN_REPORTING_TEST_SIDECAR. The latter is a
sidecar executable, not an installer or tray acceptance result.
"""

import hashlib
import io
import json
import os
import platform
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from cafe_fin.core.secrets import WindowsCredentialStore
from openpyxl import load_workbook
from pypdf import PdfReader

from tests.reporting.native_probe import NativeSidecar, until


def key():
    return str(uuid4())


def day():
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


def configure(child, book_ids=(), *, chat_id=""):
    config = child.call("GET", "/reporting/settings")
    return child.call(
        "PUT",
        "/reporting/settings",
        {
            "request_key": key(),
            "expected_version": config["version"],
            "enabled": True,
            "auto_generate_daily": True,
            "send_at": "00:00",
            "chat_id": chat_id,
            "daily_book_ids": list(book_ids),
            "daily_export_formats": ["pdf", "xlsx", "txt"],
        },
    )


def seed_entered_data(child, business_on):
    product = child.call(
        "POST",
        "/records/products",
        {"request_key": key(), "code": "SYN-COFFEE", "name": "Cà phê tổng hợp"},
    )
    warehouse = child.call(
        "POST",
        "/records/products/warehouses",
        {"request_key": key(), "code": "SYN-KHO", "name": "Kho tổng hợp"},
    )
    entry = child.call(
        "POST",
        "/records/entries",
        {
            "request_key": key(),
            "code": "SYN-RECEIPT",
            "occurred_on": business_on,
            "entry_type": "receipt",
            "status": "posted",
            "lines": [
                {
                    "product_id": product["id"],
                    "warehouse_id": warehouse["id"],
                    "quantity_kg": "12.345",
                    "direction": "in",
                }
            ],
        },
    )
    book = child.call(
        "POST",
        "/accounting/books",
        {
            "request_key": key(),
            "name": "Sổ thu độc lập tổng hợp",
            "columns": [
                {"id": "code", "name": "Mã", "kind": "text", "required": True},
                {"id": "day", "name": "Ngày", "kind": "date", "required": True},
                {"id": "received", "name": "Thu", "kind": "money", "required": True},
            ],
            "semantics": {
                "date_column": "day",
                "income_column": "received",
                "metric_meanings": {"income": "cash_receipts"},
            },
        },
    )
    child.call(
        "POST",
        f"/accounting/books/{book['id']}/rows",
        {"request_key": key(), "values": {"code": "0001", "day": business_on, "received": "10.01"}},
    )
    return entry, book


def assert_local_exports(child, report):
    assert report["state"] == "SAVED" and report["version"] == 1
    canonical = json.dumps(
        report["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == report["sha256"]
    assert {item["format"] for item in report["exports"]} == {"pdf", "xlsx", "txt"}
    pins = {}
    for exported in report["exports"]:
        local = exported["local_export"]
        assert local["state"] == "READY"
        assert local["relative_key"].startswith("reports/CafeFin-")
        path = (child.root / local["relative_key"]).resolve()
        assert path.is_relative_to(child.root)
        content = path.read_bytes()
        assert len(content) == local["size"] == exported["size"]
        assert hashlib.sha256(content).hexdigest() == local["sha256"] == exported["sha256"]
        downloaded = child.call(
            "GET",
            f"/reporting/reports/{report['id']}/exports/{exported['id']}/content",
            content=True,
        )
        assert downloaded == content
        if exported["format"] == "pdf":
            text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(content)).pages)
            assert "BÁO CÁO" in text.upper()  # Text/font extraction, not visual approval.
        elif exported["format"] == "xlsx":
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
            try:
                assert workbook.sheetnames
                assert not any(
                    cell.data_type == "f" for sheet in workbook for row in sheet for cell in row
                )
            finally:
                workbook.close()
        else:
            assert "BÁO CÁO" in content.decode("utf-8").upper()
        pins[exported["id"]] = (local["relative_key"], exported["sha256"], content)
    return pins


def assert_unconfigured(child):
    deliveries = child.call("GET", "/reporting/deliveries")
    assert deliveries["total"] == 1
    row = deliveries["items"][0]
    assert row["state"] == "UNCONFIGURED" and row["attempts"] == 0
    assert row["message_id"] is None and row["file_message_id"] is None
    assert child.call("GET", f"/reporting/deliveries/{row['id']}/attempts")["total"] == 0
    assert child.call("GET", "/reporting/settings")["sender_status"] == "UNCONFIGURED"
    return row


def evidence(record_property):
    binary = os.environ.get("CAFE_FIN_REPORTING_TEST_SIDECAR")
    record_property("execution_mode", "frozen" if binary else "source")
    record_property("python_controller", platform.python_version())
    record_property("windows", platform.platform())
    record_property("market_network", "disabled using production CAFE_FIN_MARKET_NETWORK=0")
    if binary:
        with Path(binary).open("rb") as stream:
            record_property("sidecar_sha256", hashlib.file_digest(stream, "sha256").hexdigest())


def record_report(record_property, report):
    record_property("report_snapshot_sha256", report["sha256"])
    for exported in report["exports"]:
        record_property(exported["format"] + "_sha256", exported["sha256"])


def test_native_real_60_second_timer_offline_exports_immutable_and_reopens(
    tmp_path, record_property
):
    evidence(record_property)
    root = tmp_path / "Dữ liệu báo cáo tổng hợp"
    business_on = day()
    with NativeSidecar(root, initialize=True) as child:
        child.login(setup=True)
        entry, book = seed_entered_data(child, business_on)
        market = child.call("GET", "/records/market/processed")
        assert market["status"] == "NETWORK_DISABLED" and market["enabled"]
        assert market["attempts"] == 0 and not market["network_available"]
        assert not market["board_id"] and market["snapshot"] is None
        configure(child, [book["id"]])
        status = child.call("GET", "/reporting/settings")["scheduler_status"]
        assert status["registered"] and status["running"] and status["runs"] == 0
        assert time.monotonic() - child.started < 45, "Setup consumed timer observation window"
        assert child.call("GET", "/reporting/reports")["total"] == 0
        # No manual tick, renderer, connection-check or page heartbeat. Only read
        # timer telemetry until the unmodified production 60-second callback ran.
        status = until(
            lambda: (
                s
                if (s := child.call("GET", "/reporting/settings")["scheduler_status"])["runs"] >= 1
                else None
            ),
            timeout=75,
        )
        elapsed = time.monotonic() - child.started
        record_property("observed_timer_seconds_from_process_start", round(elapsed, 3))
        assert elapsed >= 59 and status["runs"] == 1
        assert not status["error_code"] and status["failures"] == 0
        reports = child.call("GET", "/reporting/reports")
        assert reports["total"] == 1
        report = child.call("GET", "/reporting/reports/" + reports["items"][0]["id"])
        assert report["from_on"] == report["through_on"] == business_on == day()
        snapshot = report["snapshot"]
        assert snapshot["consistency"] == "atomic_read_snapshot"
        assert snapshot["sources"]["inventory"]["items"][0]["closing_kg"] == "12.345"
        assert snapshot["sources"]["books"][0]["metrics"][0]["amount_vnd"] == "10.01"
        pins = assert_local_exports(child, report)
        record_report(record_property, report)
        delivery = assert_unconfigured(child)
        # A real owner API edit after capture cannot rewrite the saved snapshot.
        updated = child.call(
            "PUT",
            f"/records/entries/{entry['id']}",
            {
                "request_key": key(),
                "expected_version": entry["version"],
                "code": "SYN-RECEIPT",
                "occurred_on": business_on,
                "entry_type": "receipt",
                "status": "posted",
                "lines": [{**entry["lines"][0], "quantity_kg": "13.345"}],
            },
        )
        assert updated["version"] == entry["version"] + 1
        assert updated["lines"][0]["quantity_kg"] == "13.345"
        assert child.call("GET", "/reporting/reports/" + report["id"]) == report
    assert child.process.poll() == 0
    with NativeSidecar(root) as reopened:
        reopened.login()
        assert reopened.call("GET", "/reporting/reports")["total"] == 1
        restored = reopened.call("GET", "/reporting/reports/" + report["id"])
        assert restored == report
        assert assert_local_exports(reopened, restored) == pins
        assert assert_unconfigured(reopened) == delivery


@pytest.mark.parametrize("chat_id", ["", "-1001234567890"], ids=["no-group", "group-without-token"])
def test_native_startup_catch_up_marks_past_days_without_fabricated_snapshots(
    tmp_path, record_property, chat_id
):
    evidence(record_property)
    root = tmp_path / "Dữ liệu khởi động tổng hợp"
    business_on = day()
    with NativeSidecar(root, initialize=True) as child:
        child.login(setup=True)
        configure(child, chat_id=chat_id)
        assert not child.call("GET", "/reporting/settings")["credential_configured"]
        assert child.call("GET", "/reporting/reports")["total"] == 0
        assert child.call("GET", "/reporting/settings")["scheduler_status"]["runs"] == 0
    # Synthetic offline fixture: model a cursor that was last checked two days
    # earlier. Only this test's closed reporting DB is touched; no system clock,
    # source owner tables, production data or immutable daily pins are changed.
    missing_from = (datetime.fromisoformat(business_on) - timedelta(days=2)).date().isoformat()
    with closing(sqlite3.connect(root / "database/cafe_fin.db")) as conn:
        conn.execute(
            "UPDATE reporting_daily_cursor SET next_unchecked_on=? WHERE profile_id='delivery'",
            (missing_from,),
        )
        conn.commit()
    with NativeSidecar(root) as child:
        child.login()
        assert child.call("GET", "/reporting/settings")["scheduler_status"]["runs"] == 0
        runs = child.call("GET", "/reporting/scheduler/daily-runs")
        assert runs["total"] == 3
        missed = [run for run in runs["items"] if run["state"] == "MISSED"]
        assert len(missed) == 2 and all(run["business_on"] < business_on for run in missed)
        assert all(
            run["policy"] == "MISSED_NO_SNAPSHOT"
            and run["report_id"] is None
            and run["outbox_id"] is None
            for run in missed
        )
        assert child.call("GET", "/reporting/reports")["total"] == 1
        current = next(run for run in runs["items"] if run["business_on"] == business_on)
        assert current["state"] == "COMPLETED"
        report = child.call("GET", "/reporting/reports/" + current["report_id"])
        assert report["from_on"] == report["through_on"] == business_on == day()
        assert_local_exports(child, report)
        record_report(record_property, report)
        assert_unconfigured(child)
    with NativeSidecar(root) as child:
        child.login()
        assert child.call("GET", "/reporting/scheduler/daily-runs")["total"] == 3
        assert child.call("GET", "/reporting/reports")["total"] == 1
        assert_unconfigured(child)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows Credential Manager")
def test_native_credential_manager_survives_process_backup_has_no_plaintext(
    tmp_path, record_property
):
    evidence(record_property)
    operation_id = key()
    root, backup = (
        tmp_path / "Dữ liệu credential tổng hợp",
        tmp_path / ("CafeFinBackup-" + operation_id),
    )
    store = WindowsCredentialStore()  # Independent controller inspects exact synthetic key.
    assert store.available
    credential_key = None
    token = "123456:" + "N" * 35
    children = []
    try:
        with NativeSidecar(root, initialize=True) as child:
            children.append(child)
            child.login(setup=True)
            root_id = json.loads((root / ".cafe-fin-root.json").read_text(encoding="utf-8"))[
                "root_id"
            ]
            credential_key = f"cafe_fin/reporting/{root_id}/telegram/123456"
            assert not store.has(credential_key)
            child.call("PUT", "/reporting/credentials", {"bot_token": token})
            assert store.get(credential_key) == {"bot_token": token}
            status = child.call("GET", "/reporting/settings")
            assert status["credential_store_available"] and status["credential_configured"]
            assert status["sender_status"] == "UNCONFIGURED" and status["bot_verified_at"] is None
        with NativeSidecar(root) as child:
            children.append(child)
            child.login()
            status = child.call("GET", "/reporting/settings")
            assert status["credential_configured"] and status["sender_status"] == "UNCONFIGURED"
            configure(child)
            # Token present + group absent still saves locally with zero attempts.
        with NativeSidecar(root) as child:
            children.append(child)
            child.login()
            assert_unconfigured(child)
            report_id = child.call("GET", "/reporting/reports")["items"][0]["id"]
            report = child.call("GET", "/reporting/reports/" + report_id)
            assert_local_exports(child, report)
            record_report(record_property, report)
            prepared = child.control(
                "maintenance.prepare",
                kind="backup",
                operation_id=operation_id,
                destination=str(backup.resolve()),
            )
            assert prepared["state"] == "PREPARED" and backup.is_dir()
        for directory in (root, backup):
            for path in directory.rglob("*"):
                if path.is_file():
                    assert token.encode() not in path.read_bytes(), (
                        "Synthetic secret leaked into data/backup"
                    )
        for child in children:
            assert token.encode() not in b"".join(child.frames) + child.stderr
    finally:
        if credential_key:
            store.delete(credential_key)  # No enumeration and no real credential target.
    assert not store.has(credential_key)
