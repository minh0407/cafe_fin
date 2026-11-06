"""Display names are snapshot-scoped metadata; IDs and exact stock remain authoritative."""

import hashlib
import io
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from cafe_fin.core.contracts import InventorySummaryDTO
from cafe_fin.core.db import canonical_json
from sqlalchemy import event, insert
from test_records_read_bridge_v2 import components
from test_records_shared_snapshot import CUTOFF, DAY, prepare


def reader(api):
    from cafe_fin.records.module import RecordsReadProvider

    return RecordsReadProvider(api.runtime, api.principal)


def capture(api, *, cutoff=CUTOFF):
    return reader(api).inventory_summary(DAY, DAY, cutoff=cutoff)


def numeric(summary):
    data = summary.model_dump(mode="json")
    for row in data["items"] + (data["movement_breakdown"] or []):
        row.pop("product_name")
        row.pop("warehouse_name")
    return data


def rename(api, resource, row, name, *, active=None, note=None):
    payload = {"code": row["code"], "name": name, "active": row.get("active", True), "note": note}
    if active is not None:
        payload["active"] = active
    if resource == "products":
        payload["unit_id"] = row.get("unit_id")
    response = api.replace(resource, row, payload)
    assert response.status_code == 200, response.text
    return response.json()


def assert_names(summary, product_name, warehouse_name):
    assert len(summary.items) == len(summary.movement_breakdown) == 1
    for row in (summary.items[0], summary.movement_breakdown[0]):
        assert row.product_name == product_name
        assert row.warehouse_name == warehouse_name


def append_legacy_revision(api, row, *, invalid=None, deleted=False, replacement_name=None):
    """Append a synthetic legacy revision; only the mutable document version pointer moves."""
    from cafe_fin.records.migrations import DOCUMENTS, REVISIONS

    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    version = row["version"] + 1
    data = row | {"version": version, "updated_at": timestamp, "recorded_at": timestamp}
    if replacement_name is not None:
        data["name"] = replacement_name
    if deleted:
        data["deleted_at"] = timestamp
        data["active"] = False
    invalid_values = {"null": None, "integer": 123, "boolean": True, "array": [],
                      "object": {"not": "a name"}, "whitespace": " \t\n\u2003"}
    if invalid == "missing":
        data.pop("name")
    elif invalid in invalid_values:
        data["name"] = invalid_values[invalid]
    raw = "{ malformed legacy JSON" if invalid == "malformed_json" else canonical_json(data)

    def append(conn):
        conn.execute(insert(REVISIONS).values(document_id=row["id"], version=version,
            recorded_at=timestamp, actor=api.principal.id, action="synthetic_legacy_fixture",
            data_json=raw, occurred_on=None, status=None, commercial_scaled=None,
            deleted_at=data["deleted_at"]))
        conn.execute(DOCUMENTS.update().where(DOCUMENTS.c.id == row["id"]).values(version=version))

    api.runtime.writer.run(append)
    return data


def test_v3_unicode_literal_markup_maximum_length_and_master_only_provenance(records_api):
    api = records_api
    masters = api.masters()
    product_name = ' Cà phê Đắk Lắk <script>alert("literal")</script> & 雪 ☕ '
    warehouse_name = "Kho " + "é" * 252
    assert len(warehouse_name) == 256
    rename(api, "products", masters["product"], product_name, note="PRIVATE_PRODUCT_NOTE_DO_NOT_LABEL")
    rename(api, "products/warehouses", masters["warehouse"], warehouse_name, note="PRIVATE_WAREHOUSE_NOTE_DO_NOT_LABEL")
    party = masters["party"]
    response = api.replace("parties", party, {"code": party["code"], "name": "PRIVATE_CUSTOMER_NAME_DO_NOT_LABEL",
        "type": party["type"], "roles": party["roles"], "contacts": [],
        "bank_details": [{"bank_name": "PRIVATE_BANK", "account_number": "PRIVATE_ACCOUNT"}]})
    assert response.status_code == 200, response.text
    api.create("entries", api.entry_data(masters, "10.001") | {"note": "PRIVATE_ENTRY_NOTE_DO_NOT_LABEL"})
    summary = capture(api)
    assert_names(summary, product_name, warehouse_name)
    assert summary.items[0].closing_kg == "10.001"
    serialized = summary.model_dump_json()
    assert product_name in json.loads(serialized)["items"][0]["product_name"]
    assert all(secret not in serialized for secret in (
        "PRIVATE_PRODUCT_NOTE_DO_NOT_LABEL", "PRIVATE_WAREHOUSE_NOTE_DO_NOT_LABEL",
        "PRIVATE_CUSTOMER_NAME_DO_NOT_LABEL", "PRIVATE_BANK", "PRIVATE_ACCOUNT", "PRIVATE_ENTRY_NOTE_DO_NOT_LABEL",
    ))
    response = api.get("stock-balances", from_on=DAY.isoformat(), through_on=DAY.isoformat(), cutoff=CUTOFF.isoformat())
    assert response["items"][0]["product_name"] == product_name
    assert response["movement_breakdown"][0]["warehouse_name"] == warehouse_name


def test_v3_equal_names_do_not_merge_distinct_product_and_warehouse_ids(records_api):
    api = records_api
    product1 = api.create("products", {"code": "P1", "name": "Tên giống nhau"})
    product2 = api.create("products", {"code": "P2", "name": "Tên giống nhau"})
    warehouse1 = api.create("products/warehouses", {"code": "W1", "name": "Kho giống nhau"})
    warehouse2 = api.create("products/warehouses", {"code": "W2", "name": "Kho giống nhau"})
    lines = []
    expected = {}
    for index, (product, warehouse) in enumerate(((product1, warehouse1), (product1, warehouse2),
                                                (product2, warehouse1), (product2, warehouse2)), 1):
        quantity = f"{index}.001"
        lines.append({"product_id": product["id"], "warehouse_id": warehouse["id"],
                      "quantity_kg": quantity, "direction": "in"})
        expected[product["id"], warehouse["id"]] = quantity
    api.create("entries", {"code": "DISTINCT-SCOPES", "occurred_on": DAY.isoformat(),
        "entry_type": "receipt", "status": "posted", "lines": lines})
    summary = capture(api)
    assert {(row.product_id, row.warehouse_id): row.closing_kg for row in summary.items} == expected
    breakdown = components(summary)
    assert len(breakdown) == 4
    assert {scope: value["purchased_kg"] for scope, value in breakdown.items()} == expected
    for row in summary.items + summary.movement_breakdown:
        assert (row.product_name, row.warehouse_name) == ("Tên giống nhau", "Kho giống nhau")


def test_v3_rename_uses_same_bound_snapshot_and_cutoff_without_rewriting_saved_payloads(records_api):
    api = records_api
    masters, _, entry_payload, entry = prepare(api)
    source = reader(api)
    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = source.bind_connection(conn)
        before = bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)
        before_cutoff = datetime.now(timezone.utc)
        raw_v3 = before.model_dump_json().encode("utf-8")
        legacy_v2 = json.loads(raw_v3)
        for row in legacy_v2["items"] + legacy_v2["movement_breakdown"]:
            row.pop("product_name")
            row.pop("warehouse_name")
        raw_v2 = json.dumps(legacy_v2, ensure_ascii=False, indent=2).encode("utf-8")
        saved = []
        for version, raw in (("v3", raw_v3), ("legacy-v2", raw_v2)):
            stored = api.runtime.files.put(io.BytesIO(raw), category="reports", original_name=f"snapshot-{version}.json",
                actor=api.principal.id, request_key=api.key(), media_type="application/json",
                authorize=lambda c: api.runtime.auth.authorize(c, api.principal, "files.write"))
            assert stored.sha256 == hashlib.sha256(raw).hexdigest()
            saved.append((stored, raw))
        rename(api, "products", masters["product"], "Tên sản phẩm mới")
        rename(api, "products/warehouses", masters["warehouse"], "Tên kho mới")
        response = api.replace("entries", entry, entry_payload | {"lines": [api.line(masters, "15.003")]})
        assert response.status_code == 200, response.text
        still_old = bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)
        assert still_old == before
        fresh = source.inventory_summary(DAY, DAY, cutoff=CUTOFF)
        assert_names(fresh, "Tên sản phẩm mới", "Tên kho mới")
        assert fresh.items[0].closing_kg == fresh.movement_breakdown[0].purchased_kg == "15.003"
        historical = source.inventory_summary(DAY, DAY, cutoff=before_cutoff)
        assert historical.items == before.items
        assert historical.movement_breakdown == before.movement_breakdown
        assert not conn.closed and conn.connection.driver_connection.in_transaction
        for stored, original_bytes in saved:
            with api.runtime.files.read(stored.id) as stream:
                reread = stream.read()
            assert reread == original_bytes
            assert hashlib.sha256(reread).hexdigest() == stored.sha256
            assert api.runtime.files.get(stored.id).sha256 == stored.sha256
        parsed_legacy = InventorySummaryDTO.model_validate_json(raw_v2)
        assert parsed_legacy.items[0].product_name is None
        assert parsed_legacy.movement_breakdown[0].warehouse_name is None
        assert "product_name" not in json.loads(raw_v2)["items"][0]


def test_v3_inactive_and_legacy_deleted_masters_keep_historical_scopes_and_names(records_api):
    api = records_api
    masters, _, _, _ = prepare(api)
    before = capture(api)
    product = rename(api, "products", masters["product"], masters["product"]["name"], active=False)
    warehouse = rename(api, "products/warehouses", masters["warehouse"], masters["warehouse"]["name"], active=False)
    inactive = capture(api)
    assert numeric(inactive) == numeric(before)
    assert_names(inactive, product["name"], warehouse["name"])
    append_legacy_revision(api, product, deleted=True, replacement_name="Tên hàng nguồn cũ đã xóa")
    append_legacy_revision(api, warehouse, deleted=True, replacement_name="Tên kho nguồn cũ đã xóa")
    deleted = capture(api)
    assert numeric(deleted) == numeric(before)
    assert_names(deleted, "Tên hàng nguồn cũ đã xóa", "Tên kho nguồn cũ đã xóa")


@pytest.mark.parametrize("resource", ["products", "products/warehouses"])
@pytest.mark.parametrize("length", [257, 300])
def test_v3_source_api_accepts_long_name_but_summary_uses_none_without_numeric_change(records_api, resource, length):
    api = records_api
    masters, _, _, _ = prepare(api)
    before = capture(api)
    original = masters["product" if resource == "products" else "warehouse"]
    renamed = rename(api, resource, original, "Đ" * length)
    assert len(renamed["name"]) == length
    after = capture(api)
    assert numeric(after) == numeric(before)
    assert_names(after, None if resource == "products" else masters["product"]["name"],
                 None if resource != "products" else masters["warehouse"]["name"])


@pytest.mark.parametrize("resource", ["products", "products/warehouses"])
@pytest.mark.parametrize("invalid", ["null", "integer", "boolean", "array", "object", "missing", "whitespace", "malformed_json"])
def test_v3_legacy_invalid_label_is_unavailable_not_coerced_or_taken_from_other_fields(records_api, resource, invalid):
    api = records_api
    masters, _, _, _ = prepare(api)
    before = capture(api)
    original = masters["product" if resource == "products" else "warehouse"]
    append_legacy_revision(api, original, invalid=invalid)
    after = capture(api)
    assert numeric(after) == numeric(before)
    assert_names(after, None if resource == "products" else masters["product"]["name"],
                 None if resource != "products" else masters["warehouse"]["name"])


def test_v3_label_queries_batch_unique_ids_on_same_connection_without_joining_numeric_movements(records_api, monkeypatch):
    from cafe_fin.records.migrations import DOCUMENTS, REVISIONS

    api = records_api
    warehouses = [api.create("products/warehouses", {"code": f"BW-{n}", "name": f"Kho batch {n}"}) for n in range(2)]
    identities = [str(uuid4()) for _ in range(501)]
    timestamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    def seed_valid_masters(conn):
        documents, revisions = [], []
        for n, identity in enumerate(identities):
            code, name = f"BP-{n}", f"Sản phẩm batch {n}"
            data = {"id": identity, "version": 1, "code": code, "name": name, "active": True,
                "deleted_at": None, "unit_id": None, "note": None, "created_at": timestamp,
                "updated_at": timestamp, "recorded_at": timestamp, "created_by": api.principal.id,
                "updated_by": api.principal.id, "order_key": "synthetic-master"}
            documents.append({"id": identity, "kind": "products", "code_key": code.casefold(),
                "version": 1, "created_at": timestamp, "created_by": api.principal.id})
            revisions.append({"document_id": identity, "version": 1, "recorded_at": timestamp,
                "actor": api.principal.id, "action": "synthetic_batch_master_fixture", "data_json": canonical_json(data),
                "occurred_on": None, "status": None, "commercial_scaled": None, "deleted_at": None})
        conn.execute(insert(DOCUMENTS), documents)
        conn.execute(insert(REVISIONS), revisions)

    api.runtime.writer.run(seed_valid_masters)
    lines = [{"product_id": identity, "warehouse_id": warehouses[0 if n < 500 else 1]["id"],
              "quantity_kg": "0.001", "direction": "in"} for n, identity in enumerate(identities)]
    for repeat in range(3):
        for start in (0, 500):
            api.create("entries", {"code": f"BATCH-{repeat}-{start}", "occurred_on": DAY.isoformat(),
                "entry_type": "receipt", "status": "posted", "lines": lines[start:start + 500]})
    label_queries, movement_queries = [], []
    all_ids = set(identities) | {row["id"] for row in warehouses}

    def observe(conn, cursor, statement, parameters, context, executemany):
        if "records_summary_masters" in statement.lower():
            values = parameters.values() if isinstance(parameters, dict) else parameters
            selected_ids = {value for value in values if isinstance(value, str)} & all_ids
            label_queries.append((conn, statement, selected_ids))
        elif "records_movements" in statement.lower():
            movement_queries.append((conn, statement))

    def unexpected_reader():
        pytest.fail("bound summary opened a separate runtime.reader for labels")

    with api.runtime.reader() as conn:
        conn.exec_driver_sql("BEGIN")
        bound = reader(api).bind_connection(conn)
        monkeypatch.setattr(api.runtime, "reader", unexpected_reader)
        event.listen(api.runtime.database.engine, "before_cursor_execute", observe)
        try:
            summary = bound.inventory_summary(DAY, DAY, cutoff=CUTOFF)
        finally:
            event.remove(api.runtime.database.engine, "before_cursor_execute", observe)
        assert len(summary.items) == len(summary.movement_breakdown) == 501
        assert len(label_queries) == 2  # ceil(503 unique IDs / batch size 500), not 1503 movements.
        assert all(c is conn and "records_movements" not in sql.lower() and 0 < len(ids) <= 500
                   for c, sql, ids in label_queries)
        assert set.union(*(ids for _, _, ids in label_queries)) == all_ids
        assert sum(len(ids) for _, _, ids in label_queries) == 503
        assert len(movement_queries) == 1 and movement_queries[0][0] is conn
        assert "records_summary_masters" not in movement_queries[0][1].lower()
        by_product = {row.product_id: row for row in summary.items}
        for n, identity in enumerate(identities):
            row = by_product[identity]
            assert row.product_name == f"Sản phẩm batch {n}"
            assert row.warehouse_name == warehouses[0 if n < 500 else 1]["name"]
            assert (row.received_kg, row.issued_kg, row.closing_kg) == ("0.003", "0.000", "0.003")
        assert not conn.closed and conn.connection.driver_connection.in_transaction
