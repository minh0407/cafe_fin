"""Records tests use isolated, new, file-backed SQLite databases and real HTTP handlers."""

from itertools import count

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient


class RecordsAPI:
    def __init__(self, runtime, client, headers, principal):
        self.runtime, self.client = runtime, client
        self.headers, self.principal = headers, principal
        self.keys = count(1)

    def key(self):
        return f"records-test-{next(self.keys)}"

    def request(self, method, path, *, data=None, params=None):
        return self.client.request(
            method, "/api/v1/records/" + path, headers=self.headers, json=data, params=params
        )

    def create(self, resource, data, *, key=None):
        response = self.request("POST", resource, data=data | {"request_key": key or self.key()})
        assert response.status_code in (200, 201), response.text
        return response.json()

    def get(self, path, **params):
        response = self.request("GET", path, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def replace(self, resource, row, data, *, key=None):
        return self.request(
            "PUT", f"{resource}/{row['id']}",
            data=data | {"request_key": key or self.key(), "expected_version": row["version"]},
        )

    def command(self, resource, row, command, *, key=None):
        path = f"{resource}/{row['id']}"
        method = "DELETE" if command == "delete" else "POST"
        if command != "delete":
            path += "/" + command
        return self.request(
            method, path,
            data={"request_key": key or self.key(), "expected_version": row["version"]},
        )

    def stock(self, from_on="2026-01-01", through_on="2026-12-31"):
        return self.get("stock-balances", from_on=from_on, through_on=through_on)

    def masters(self):
        unit = self.create("products/units", {"code": "KG", "name": "Kilôgam"})
        warehouse = self.create("products/warehouses", {"code": "KHO-01", "name": "Kho mới"})
        product = self.create("products", {"code": "CP-01", "name": "Cà phê nhân", "unit_id": unit["id"]})
        party = self.create("parties", {
            "code": "DT-01", "name": "Đối tác tổng hợp", "type": "organization",
            "roles": ["customer", "supplier"], "contacts": [],
        })
        return {"unit": unit, "warehouse": warehouse, "product": product, "party": party}

    def line(self, masters, quantity, direction="in", *, product=None, warehouse=None):
        return {
            "product_id": (product or masters["product"])["id"],
            "warehouse_id": (warehouse or masters["warehouse"])["id"],
            "quantity_kg": quantity, "direction": direction,
        }

    def entry_data(self, masters, quantity, *, code="PN-01", day="2026-11-01", kind="receipt"):
        return {
            "code": code, "occurred_on": day, "entry_type": kind, "status": "posted",
            "party_id": masters["party"]["id"],
            "lines": [self.line(masters, quantity, "out" if kind == "issue" else "in")],
        }


@pytest.fixture
def records_api(tmp_path):
    # Import inside the fixture makes collection possible while the lane is being built.
    from cafe_fin.records.module import module_manifest

    runtime = Runtime(
        tmp_path / "Records dữ liệu mới", initialize=True,
        modules=ModuleRegistry((module_manifest(),)),
    )
    session = runtime.auth.setup("records-admin", "records-synthetic-password")
    principal = runtime.auth.authenticate(session["access_token"])
    token, port = "records-synthetic-app-session-0123456789abcdef", 49153
    headers = {"X-App-Session": token, "Authorization": "Bearer " + session["access_token"]}
    app = create_app(runtime, token, port=port)
    try:
        with TestClient(app, base_url=f"http://127.0.0.1:{port}") as client:
            yield RecordsAPI(runtime, client, headers, principal)
    finally:
        runtime.close()
