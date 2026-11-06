"""Historical provenance, stable chronology and permission revalidation at integration boundaries."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pytest
from cafe_fin.core.auth import USERS
from cafe_fin.core.errors import CoreError
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from tests.records.test_records_api import balances, error, snapshot


@pytest.mark.parametrize("table_name", ["REVISIONS", "MOVEMENTS", "REFERENCES", "LINES"])
@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_history_ledger_and_references_reject_sql_tampering(records_api, table_name, operation):
    from cafe_fin.records import migrations

    api = records_api
    masters = api.masters()
    api.create("entries", api.entry_data(masters, "10.001"))
    table = getattr(migrations, table_name)
    with api.runtime.reader() as conn:
        assert conn.exec_driver_sql("PRAGMA recursive_triggers").scalar_one() == 1
        row = dict(conn.execute(select(table)).mappings().first())
    before = snapshot(api)

    def tamper(conn):
        if operation == "update":
            # Even an otherwise harmless rewrite is forbidden for immutable provenance.
            column = next(iter(table.c)).name
            conn.execute(table.update().values({column: row[column]}))
        elif operation == "delete":
            conn.execute(table.delete())
        else:
            conn.execute(insert(table).prefix_with("OR REPLACE").values(**row))

    with pytest.raises(IntegrityError, match="records history is immutable"):
        api.runtime.writer.run(tamper)
    assert snapshot(api) == before


def test_referenced_masters_cannot_be_deleted_but_deactivation_preserves_saved_reads(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters = api.masters()
    entry_payload = api.entry_data(masters, "10.001")
    entry = api.create("entries", entry_payload)
    resources = {
        "parties": (masters["party"], {
            "code": "DT-01", "name": "Đối tác ngừng", "type": "organization",
            "roles": ["customer", "supplier"], "contacts": [],
        }),
        "products": (masters["product"], {
            "code": "CP-01", "name": "Cà phê ngừng", "unit_id": masters["unit"]["id"],
        }),
        "products/units": (masters["unit"], {"code": "KG", "name": "Kg ngừng"}),
        "products/warehouses": (masters["warehouse"], {"code": "KHO-01", "name": "Kho ngừng"}),
    }
    for resource, (row, payload) in resources.items():
        before = snapshot(api)
        error(api.command(resource, row, "delete"), "RECORD_REFERENCED")
        assert snapshot(api) == before
        response = api.replace(resource, row, payload | {"active": False})
        assert response.status_code == 200, response.text
        assert response.json()["active"] is False
        assert api.get(resource + "/" + row["id"])["id"] == row["id"]
    provider = RecordsReadProvider(api.runtime, api.principal)
    assert provider.lookup_party(masters["party"]["id"]).name == "Đối tác ngừng"
    response = api.replace("entries", entry, entry_payload | {"note": "Giữ tham chiếu lịch sử"})
    assert response.status_code == 200, response.text
    assert list(balances(api).values()) == ["10.001"]
    before = snapshot(api)
    error(api.request("POST", "entries", data=entry_payload | {
        "request_key": api.key(), "code": "PN-NEW-INACTIVE",
    }), "REFERENCE_INACTIVE")
    assert snapshot(api) == before


def test_same_day_order_is_stable_after_edit_and_retry(records_api):
    api = records_api
    masters = api.masters()
    receipt_payload = api.entry_data(masters, "10.000", day="2026-11-01")
    receipt = api.create("entries", receipt_payload)
    issue = api.create("entries", api.entry_data(
        masters, "8.000", code="PX-SAME-DAY", day="2026-11-01", kind="issue",
    ))
    updated_data = receipt_payload | {"lines": [api.line(masters, "9.000")], "note": "Sửa sau xuất"}
    response = api.replace("entries", receipt, updated_data, key="same-day-edit-once")
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["order_key"] == receipt["order_key"]
    assert updated["order_key"] < issue["order_key"]
    before = snapshot(api)
    assert api.replace("entries", receipt, updated_data, key="same-day-edit-once").json() == updated
    assert snapshot(api) == before
    assert list(balances(api).values()) == ["1.000"]
    movements = api.get("stock-movements")["items"]
    assert [row["entry_id"] for row in movements] == [receipt["id"], issue["id"]]
    assert movements[0]["order_key"].startswith(receipt["order_key"])


def test_same_day_later_receipt_cannot_repair_an_earlier_negative_prefix(records_api):
    api = records_api
    masters = api.masters()
    receipt = api.create("entries", api.entry_data(masters, "10.000"))
    issue = api.create("entries", api.entry_data(
        masters, "8.000", code="PX-EARLY", day="2026-11-02", kind="issue",
    ))
    api.create("entries", api.entry_data(masters, "10.000", code="PN-SAME-DAY-LATE", day="2026-11-02"))
    before = snapshot(api)
    detail = error(api.command("entries", receipt, "cancel"), "STOCK_NEGATIVE")["details"]
    assert detail["related_entry_id"] == issue["id"]
    assert snapshot(api) == before


@pytest.mark.parametrize("replay", [False, True])
def test_revoked_principal_cannot_write_or_replay_after_waiting_in_writer_queue(records_api, monkeypatch, replay):
    from cafe_fin.records.service import RecordsService

    api = records_api
    masters = api.masters()
    account = api.runtime.auth.create_user(
        api.principal, username="queued-operator", password="synthetic-queue-password",
        role="operator", request_key="queued-operator-account",
    )
    session = api.runtime.auth.login("queued-operator", "synthetic-queue-password")
    captured = api.runtime.auth.authenticate(session["access_token"])
    service = RecordsService(api.runtime)
    data = api.entry_data(masters, "1.001")
    key = "revoked-write-key"
    if replay:
        service.save("entries", data, actor=captured, request_key=key)
    before = snapshot(api)
    transaction_entered, release_revoke, queued = (threading.Event() for _ in range(3))

    def revoke_inside_transaction(conn):
        # Trusted synthetic fixture models a prior administrator write transaction.
        conn.execute(USERS.update().where(USERS.c.id == account["id"]).values(active=False, version=2))
        transaction_entered.set()
        assert release_revoke.wait(10)

    original_submit = api.runtime.writer._executor.submit

    def track_submit(fn, *args, **kwargs):
        future = original_submit(fn, *args, **kwargs)
        queued.set()
        return future

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            revocation = executor.submit(api.runtime.writer.run, revoke_inside_transaction)
            assert transaction_entered.wait(5)
            monkeypatch.setattr(api.runtime.writer._executor, "submit", track_submit)
            attempted = executor.submit(service.save, "entries", data, actor=captured, request_key=key)
            try:
                assert queued.wait(5), "records command was not enqueued behind revocation"
                assert not attempted.done()
            finally:
                release_revoke.set()
            revocation.result(timeout=10)
            with pytest.raises(CoreError, match="SESSION_EXPIRED"):
                attempted.result(timeout=10)
        assert snapshot(api) == before
    finally:
        release_revoke.set()


def test_all_read_provider_methods_revalidate_captured_principal(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters = api.masters()
    weighing = api.create("weighings", {
        "code": "CAN-REVOKED", "occurred_on": "2026-11-01",
        "lines": [{"quantity_source": "direct_net", "net_kg": "1.001"}],
    })
    api.create("entries", api.entry_data(masters, "1.001"))
    account = api.runtime.auth.create_user(
        api.principal, username="read-operator", password="synthetic-read-password",
        role="operator", request_key="read-operator-account",
    )
    session = api.runtime.auth.login("read-operator", "synthetic-read-password")
    actor = api.runtime.auth.authenticate(session["access_token"])
    provider = RecordsReadProvider(api.runtime, actor)
    assert provider.lookup_party(masters["party"]["id"]) is not None
    api.runtime.auth.update_user(
        api.principal, account["id"], role="operator", active=False,
        expected_version=account["version"], request_key="revoke-reader",
    )
    before = snapshot(api)
    cutoff = datetime.now(timezone.utc)
    for call in (
        lambda: provider.lookup_party(masters["party"]["id"]),
        lambda: provider.get_weighing(weighing["id"]),
        lambda: provider.inventory_summary(date(2026, 11, 1), date(2026, 11, 1), cutoff=cutoff),
        lambda: provider.receivable_summary(date(2026, 11, 1), cutoff=cutoff),
    ):
        with pytest.raises(CoreError, match="SESSION_EXPIRED"):
            call()
    assert snapshot(api) == before


def test_cutoff_reconstructs_before_delete_during_delete_and_after_restore(records_api):
    from cafe_fin.records.module import RecordsReadProvider

    api = records_api
    masters = api.masters()
    receipt = api.create("entries", api.entry_data(masters, "10.001") | {"commercial_amount_vnd": "50.01"})
    before_delete = datetime.now(timezone.utc)
    response = api.command("entries", receipt, "delete")
    assert response.status_code == 200, response.text
    while_deleted = datetime.now(timezone.utc)
    response = api.command("entries", response.json(), "restore")
    assert response.status_code == 200, response.text
    after_restore = datetime.now(timezone.utc)
    provider = RecordsReadProvider(api.runtime, api.principal)
    before = snapshot(api)
    for cutoff, expected_stock, expected_money in (
        (before_delete, ["10.001"], ["50.01"]),
        (while_deleted, [], []),
        (after_restore, ["10.001"], ["50.01"]),
    ):
        inventory = provider.inventory_summary(date(2026, 11, 1), date(2026, 11, 1), cutoff=cutoff)
        receivables = provider.receivable_summary(date(2026, 11, 1), cutoff=cutoff)
        assert [row.closing_kg for row in inventory.items] == expected_stock
        assert [row.amount_vnd for row in receivables.items] == expected_money
    assert snapshot(api) == before


def test_reordering_saved_lines_keeps_inactive_product_references(records_api):
    api = records_api
    masters = api.masters()
    other = api.create("products", {"code": "CP-02", "name": "Cà phê thứ hai"})
    original_lines = [api.line(masters, "10.001"), api.line(masters, "20.002", product=other)]
    payload = api.entry_data(masters, "10.001") | {"lines": original_lines}
    entry = api.create("entries", payload)
    for row in (masters["product"], other):
        response = api.replace("products", row, {
            "code": row["code"], "name": row["name"], "unit_id": row.get("unit_id"), "active": False,
        })
        assert response.status_code == 200, response.text
    response = api.replace("entries", entry, payload | {
        "lines": list(reversed(original_lines)), "note": "Đổi thứ tự, giữ sản phẩm đã ghi",
    })
    assert response.status_code == 200, response.text
    assert response.json()["lines"][0]["product_id"] == other["id"]
    result = balances(api)
    assert result[(masters["product"]["id"], masters["warehouse"]["id"])] == "10.001"
    assert result[(other["id"], masters["warehouse"]["id"])] == "20.002"
