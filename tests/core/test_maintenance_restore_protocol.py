"""Real default-registry private-wire restore and owner quarantine, without network sending."""

import hashlib
import sqlite3
from contextlib import closing
from urllib.parse import quote
from uuid import uuid4

import httpx
from cafe_fin.core.storage import DataRootService

from tests.core.test_maintenance_protocol import TOKEN, Child, login

DAY = "2026-11-06"


def key():
    return str(uuid4())


def call(client, child, token, method, path, *, expected=200, **kwargs):
    headers = {"X-App-Session": TOKEN, "Authorization": "Bearer " + token}
    headers.update(kwargs.pop("headers", {}))
    response = client.request(method, child.base + path, headers=headers, **kwargs)
    assert response.status_code == expected, (response.status_code, response.text)
    return response


def data(client, child, token, method, path, **kwargs):
    return call(client, child, token, method, path, **kwargs).json()


def files_at(root):
    with closing(
        sqlite3.connect((root / "database/cafe_fin.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        return conn.execute(
            "SELECT id,sha256,size,relative_key FROM core_files ORDER BY id"
        ).fetchall()


def guard_counts(root, operation_id):
    with closing(
        sqlite3.connect((root / "database/cafe_fin.db").as_uri() + "?mode=ro", uri=True)
    ) as conn:
        return (
            conn.execute(
                "SELECT count(*) FROM core_audit WHERE entity='reporting_activation' AND entity_id=? AND action='restore_quarantine'",
                (operation_id,),
            ).fetchone()[0],
            conn.execute(
                "SELECT count(*) FROM core_requests WHERE actor='reporting.activation' AND action='reporting.activation_guard' AND request_key=?",
                (operation_id,),
            ).fetchone()[0],
        )


def local_only_settings(client, child, token, version, book_id):
    # With no OA or group and no credentials, the production sender cannot send.
    return data(
        client,
        child,
        token,
        "PUT",
        "/reporting/settings",
        json={
            "expected_version": version,
            "request_key": key(),
            "enabled": True,
            "auto_generate_daily": True,
            "group_id": "",
            "oa_id": "",
            "send_at": "23:59",
            "daily_book_ids": [book_id],
            "daily_export_formats": ["txt"],
        },
    )


def test_actual_wire_restore_default_registry_quarantines_once_preserves_data_and_admin_review(
    tmp_path,
):
    source_root = tmp_path / "Dữ liệu nguồn thật tổng hợp"
    source = Child(source_root)
    target = restarted = None
    try:
        assert source.boot["status"] == "ready" and source.boot["runtime_state"] == "ACTIVE"
        with httpx.Client(trust_env=False, timeout=20) as client:
            token = login(client, source, setup=True)
            identity = source.control("maintenance.source_identity", token)
            with closing(
                sqlite3.connect(
                    (source_root / "database/cafe_fin.db").as_uri() + "?mode=ro", uri=True
                )
            ) as conn:
                namespaces = {
                    row[0]
                    for row in conn.execute("SELECT DISTINCT namespace FROM core_schema_migrations")
                }
            assert {"records", "contracts", "accounting", "reporting"} <= namespaces

            product = data(
                client,
                source,
                token,
                "POST",
                "/records/products",
                json={
                    "code": "WIRE-RESTORE-COFFEE",
                    "name": "Cà phê tổng hợp",
                    "request_key": key(),
                },
            )
            warehouse = data(
                client,
                source,
                token,
                "POST",
                "/records/products/warehouses",
                json={
                    "code": "WIRE-RESTORE-WAREHOUSE",
                    "name": "Kho tổng hợp",
                    "request_key": key(),
                },
            )
            entry = data(
                client,
                source,
                token,
                "POST",
                "/records/entries",
                json={
                    "code": "WIRE-RESTORE-RECEIPT",
                    "occurred_on": DAY,
                    "entry_type": "receipt",
                    "status": "posted",
                    "request_key": key(),
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
            book = data(
                client,
                source,
                token,
                "POST",
                "/accounting/books",
                json={
                    "name": "Sổ tổng hợp độc lập",
                    "request_key": key(),
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
            data(
                client,
                source,
                token,
                "POST",
                f"/accounting/books/{book['id']}/rows",
                json={
                    "values": {"code": "0001", "day": DAY, "received": "10.01"},
                    "request_key": key(),
                },
            )
            template = next(
                item
                for item in data(client, source, token, "GET", "/contracts/templates")["items"]
                if item["kind"] == "purchase"
            )
            contract = data(
                client,
                source,
                token,
                "POST",
                "/contracts",
                json={
                    "request_key": key(),
                    "data": {
                        "kind": "purchase",
                        "number": "WIRE-RESTORE-MANUAL",
                        "occurred_on": DAY,
                        "template_id": template["id"],
                        "company": {"type": "company", "name": "Công ty tổng hợp"},
                        "counterparty": {"type": "person", "name": "Đối tác tổng hợp"},
                        "lines": [
                            {
                                "description": "Cà phê cân tay",
                                "quantity_kg": "9.001",
                                "unit_price": "10.00",
                            }
                        ],
                        "tax": {"mode": "none"},
                        "payment": {"method": "cash", "recorded_paid_amount": "90.01"},
                    },
                },
            )
            original_bytes = "Mã,Ngày,Thu\n0001,2026-11-06,10.01\n".encode("utf-8-sig")
            original = data(
                client,
                source,
                token,
                "POST",
                "/files?category=workbooks",
                content=original_bytes,
                headers={
                    "Content-Type": "application/octet-stream",
                    "X-File-Name": quote("Nguồn kế toán.csv"),
                    "X-Request-Key": key(),
                },
            )
            report = data(
                client,
                source,
                token,
                "POST",
                "/reporting/reports/preview",
                json={
                    "from_on": DAY,
                    "through_on": DAY,
                    "book_ids": [book["id"]],
                    "reason": "Synthetic actual-wire restore capture",
                    "request_key": key(),
                },
            )
            report = data(
                client,
                source,
                token,
                "POST",
                f"/reporting/reports/{report['id']}/save",
                json={
                    "expected_version": report["version"],
                    "request_key": key(),
                },
            )
            exported = data(
                client,
                source,
                token,
                "POST",
                f"/reporting/reports/{report['id']}/exports",
                json={"format": "txt", "request_key": key()},
            )
            saved_report = data(client, source, token, "GET", f"/reporting/reports/{report['id']}")
            saved_entry = data(client, source, token, "GET", f"/records/entries/{entry['id']}")
            saved_rows = data(client, source, token, "GET", f"/accounting/books/{book['id']}/rows")
            saved_contract = data(client, source, token, "GET", f"/contracts/{contract['id']}")
            canonical_files = files_at(source_root)
            assert len(canonical_files) >= 2
            initial_settings = data(client, source, token, "GET", "/reporting/settings")
            local_only_settings(client, source, token, initial_settings["version"], book["id"])
            queued = data(
                client,
                source,
                token,
                "POST",
                f"/reporting/reports/{report['id']}/deliveries",
                json={"request_key": key()},
            )
            assert queued["state"] == "UNCONFIGURED" and queued["attempts"] == 0

            backup_id = key()
            backup = tmp_path / ("CafeFinBackup-" + backup_id)
            backed_up = source.control(
                "maintenance.prepare",
                token,
                operation_id=backup_id,
                kind="backup",
                destination=str(backup),
            )
            assert backed_up["status"] == "ok" and backed_up["state"] == "PREPARED"
            assert backed_up["source_fingerprint"] == identity["source_fingerprint"]
            backup_hash = hashlib.sha256((backup / "backup-manifest.json").read_bytes()).hexdigest()
            restore_id = key()
            restored_root = tmp_path / ("CafeFinData-" + restore_id)
            assert (
                source.control("maintenance.quiesce", token, operation_id=restore_id)["state"]
                == "QUIESCED"
            )
            restored = source.control(
                "maintenance.prepare",
                token,
                operation_id=restore_id,
                kind="restore",
                destination=str(restored_root),
                backup_source=str(backup),
            )
            assert restored["status"] == "ok" and restored["state"] == "PREPARED", restored
            assert restored["manifest_sha256"] == backup_hash
            assert (
                restored["source_root_id"] == restored["candidate_root_id"] == identity["root_id"]
            )
            assert restored["source_fingerprint"] != restored["candidate_fingerprint"]
            assert (
                source.control("maintenance.close", token, operation_id=restore_id)["state"]
                == "CLOSED"
            )
            assert source.process.wait(timeout=10) == 0
            assert source_root.is_dir() and files_at(source_root) == canonical_files
            assert files_at(restored_root) == canonical_files

            target = Child(restored_root, initialize=False, mode="dormant")
            assert target.boot["status"] == "ready" and target.boot["runtime_state"] == "DORMANT"
            target_token = login(client, target)
            for path in (
                "/records/entries",
                "/accounting/books",
                "/contracts",
                "/reporting/settings",
            ):
                call(client, target, target_token, "GET", path, expected=503)
            assert guard_counts(restored_root, restore_id) == (0, 0)
            denied_source_token = target.control(
                "maintenance.activate",
                token,
                operation_id=restore_id,
                origin_generation=source.generation,
            )
            assert denied_source_token["code"] == "SESSION_EXPIRED"
            activated = target.control(
                "maintenance.activate",
                target_token,
                operation_id=restore_id,
                origin_generation=source.generation,
            )
            assert activated["status"] == "ok" and activated["state"] == "ACTIVE", activated
            held_settings = data(client, target, target_token, "GET", "/reporting/settings")
            assert (
                held_settings["restore_review_required"]
                and held_settings["sender_status"] == "RESTORE_SUSPENDED"
            )
            assert not held_settings["enabled"] and not held_settings["auto_generate_daily"]
            assert held_settings["credential_configured"] is None
            assert held_settings["restore_review"]["activation_id"] == restore_id
            assert held_settings["restore_review"]["quarantined_count"] == 1
            assert guard_counts(restored_root, restore_id) == (1, 1)
            deliveries = data(client, target, target_token, "GET", "/reporting/deliveries")["items"]
            delivery = next(item for item in deliveries if item["id"] == queued["id"])
            assert (
                delivery["state"] == "UNKNOWN"
                and delivery["error_code"] == "RESTORE_REVIEW_REQUIRED"
            )
            assert delivery["attempts"] == 0
            assert (
                data(client, target, target_token, "GET", f"/records/entries/{entry['id']}")
                == saved_entry
            )
            assert (
                data(client, target, target_token, "GET", f"/accounting/books/{book['id']}/rows")
                == saved_rows
            )
            assert (
                data(client, target, target_token, "GET", f"/contracts/{contract['id']}")
                == saved_contract
            )
            assert (
                data(client, target, target_token, "GET", f"/reporting/reports/{report['id']}")
                == saved_report
            )
            for file_id, digest, size, relative_key in canonical_files:
                content = call(
                    client, target, target_token, "GET", f"/files/{file_id}/content"
                ).content
                assert len(content) == size and hashlib.sha256(content).hexdigest() == digest
                assert (
                    hashlib.sha256(
                        DataRootService(restored_root).resolve_key(relative_key).read_bytes()
                    ).hexdigest()
                    == digest
                )
            assert (
                call(
                    client, target, target_token, "GET", f"/files/{original['id']}/content"
                ).content
                == original_bytes
            )
            assert exported["file_id"] in {row[0] for row in canonical_files}

            reviewed = local_only_settings(
                client, target, target_token, held_settings["version"], book["id"]
            )
            assert reviewed["enabled"] and not reviewed["restore_review"]["required"]
            for _ in range(2):
                status = target.control(
                    "maintenance.status",
                    target_token,
                    operation_id=restore_id,
                    origin_generation=source.generation,
                )
                assert status["status"] == "ok" and status["state"] == "ACTIVE"
            assert (
                target.control(
                    "maintenance.activate",
                    target_token,
                    operation_id=restore_id,
                    origin_generation=source.generation,
                )["state"]
                == "ACTIVE"
            )
            after_status = data(client, target, target_token, "GET", "/reporting/settings")
            assert after_status["version"] == reviewed["version"]
            assert not after_status["restore_review_required"] and after_status["enabled"]
            assert guard_counts(restored_root, restore_id) == (1, 1)
            assert (
                target.control(
                    "maintenance.close",
                    target_token,
                    operation_id=restore_id,
                    origin_generation=source.generation,
                )["state"]
                == "CLOSED"
            )
            assert target.process.wait(timeout=10) == 0

            restarted = Child(restored_root, initialize=False)
            assert (
                restarted.boot["status"] == "ready" and restarted.boot["runtime_state"] == "ACTIVE"
            )
            restart_token = login(client, restarted)
            settings = data(client, restarted, restart_token, "GET", "/reporting/settings")
            assert settings["version"] == reviewed["version"] and settings["enabled"]
            assert (
                not settings["restore_review_required"]
                and settings["restore_review"] == reviewed["restore_review"]
            )
            assert (
                settings["group_id"] == settings["oa_id"] == ""
                and settings["sender_status"] == "UNCONFIGURED"
            )
            assert guard_counts(restored_root, restore_id) == (1, 1)
            assert files_at(restored_root) == canonical_files
            assert (
                hashlib.sha256((backup / "backup-manifest.json").read_bytes()).hexdigest()
                == backup_hash
            )
            assert (
                restarted.control(
                    "maintenance.close",
                    restart_token,
                    operation_id=restore_id,
                    origin_generation=source.generation,
                )["state"]
                == "CLOSED"
            )
            assert restarted.process.wait(timeout=10) == 0
    finally:
        for child in (source, target, restarted):
            if child is not None:
                child.finish()
