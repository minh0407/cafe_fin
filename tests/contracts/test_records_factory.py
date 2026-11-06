"""Optional records providers are created only for authorized source requests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from cafe_fin.contracts.migrations.v001 import DRAFTS, VERSIONS
from cafe_fin.contracts.module import module_manifest
from cafe_fin.core.api import create_app
from cafe_fin.core.auth import AuthService, Principal
from cafe_fin.core.contracts import (
    BankAccountDTO,
    ContactDTO,
    InventorySummaryDTO,
    PartyDTO,
    ReceivableSummaryDTO,
    RepresentativeDTO,
    WeighingDTO,
    WeightLineInput,
)
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from test_api import PASSWORD, PORT, PREFIX, TOKEN, create, data, download, export, ok

PARTY_ID = "74f6918c-4c8d-4b21-8d01-e6448a80d7c8"
WEIGHING_ID = "07f0c6ae-f80a-4c84-a93c-4065795bdbe6"
OPERATOR = "factory-operator"


class ActorRecords:
    """Typed read-only source DTOs vary by principal without any records tables."""

    def __init__(self, username: str, version: int):
        self.party = PartyDTO(
            id=PARTY_ID,
            version=version,
            type="company",
            roles=("supplier",),
            name="Synthetic party for " + username,
            address="Synthetic address",
            contacts=(ContactDTO(kind="phone", value="synthetic-contact"),),
            bank_details=(BankAccountDTO(bank_name="Synthetic bank", account_number="TEST-001"),),
            representative=RepresentativeDTO(name="Synthetic representative", title="Owner"),
        )
        self.weighing = WeighingDTO(
            id=WEIGHING_ID,
            version=version,
            code="SYNTHETIC-WEIGHING",
            occurred_on=date(2026, 11, 6),
            party_id=PARTY_ID,
            lines=(
                WeightLineInput(
                    description="Goods for " + username,
                    net_kg="2.500" if username == "admin" else "1.250",
                    quantity_source="user_entered",
                    note="Synthetic source note",
                ),
            ),
        )

    def lookup_party(self, identity: str) -> PartyDTO | None:
        return self.party if identity == PARTY_ID else None

    def get_weighing(self, identity: str) -> WeighingDTO | None:
        return self.weighing if identity == WEIGHING_ID else None

    def inventory_summary(
        self, from_on: date, through_on: date, *, cutoff: datetime
    ) -> InventorySummaryDTO:
        raise AssertionError("Source selection does not query inventory")

    def receivable_summary(self, as_of: date, *, cutoff: datetime) -> ReceivableSummaryDTO:
        raise AssertionError("Source selection does not query receivables")


@contextmanager
def configured(tmp_path, *, records=None, records_factory=None):
    registry = ModuleRegistry((module_manifest(records, records_factory=records_factory),))
    runtime = Runtime(tmp_path / "Records factory root", initialize=True, modules=registry)
    app = create_app(runtime, TOKEN, port=PORT)
    with TestClient(
        app, base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False
    ) as client:
        client.headers.update({"X-App-Session": TOKEN, "Origin": "http://tauri.localhost"})
        admin = ok(
            client.post(
                "/api/v1/auth/setup",
                json={
                    "username": "admin",
                    "password": PASSWORD,
                },
            )
        )
        client.headers["Authorization"] = "Bearer " + admin["access_token"]
        operator = ok(
            client.post(
                "/api/v1/users",
                json={
                    "username": OPERATOR,
                    "password": PASSWORD,
                    "role": "operator",
                    "request_key": "factory-operator-create",
                },
            )
        )
        operator_login = ok(
            client.post(
                "/api/v1/auth/login",
                json={
                    "username": OPERATOR,
                    "password": PASSWORD,
                },
            )
        )
        yield SimpleNamespace(
            runtime=runtime,
            client=client,
            root=tmp_path,
            users={"admin": admin["user"], OPERATOR: operator},
            authorizations={
                "admin": "Bearer " + admin["access_token"],
                OPERATOR: "Bearer " + operator_login["access_token"],
            },
        )


def source(api, kind="parties", *, username="admin", authorization=None):
    identity = PARTY_ID if kind == "parties" else WEIGHING_ID
    return api.client.get(
        f"{PREFIX}/sources/{kind}/{identity}",
        headers={
            "Authorization": authorization or api.authorizations[username],
        },
    )


def test_manual_crud_preview_and_exports_never_construct_optional_factory(tmp_path):
    calls = []

    def forbidden_factory(runtime, principal):
        calls.append((runtime, principal))
        raise AssertionError("Manual operations must not initialize optional records")

    with configured(tmp_path, records_factory=forbidden_factory) as api:
        assert calls == []
        payload = data()
        ok(api.client.post(PREFIX + "/preview", json={"data": payload}))
        contract = create(api, payload)
        assert ok(api.client.get(f"{PREFIX}/{contract['id']}")) == contract
        assert ok(api.client.get(PREFIX))["total"] == 1
        assert len(ok(api.client.get(PREFIX + "/templates"))["items"]) == 2
        payload["terms"]["additional"] = "Edited without a source provider"
        edited = ok(
            api.client.patch(
                f"{PREFIX}/{contract['id']}",
                json={
                    "request_key": "manual-edit",
                    "expected_version": 1,
                    "data": payload,
                },
            )
        )
        version = export(api, edited)
        assert {state["status"] for state in version["files"].values()} == {"succeeded"}
        for format in ("docx", "pdf"):
            download(api, edited, version, format)
        deleted = ok(
            api.client.request(
                "DELETE",
                f"{PREFIX}/{contract['id']}",
                json={
                    "request_key": "manual-delete",
                    "expected_version": edited["version"],
                },
            )
        )
        ok(
            api.client.post(
                f"{PREFIX}/{contract['id']}/restore",
                json={
                    "request_key": "manual-restore",
                    "expected_version": deleted["version"],
                },
            )
        )
        assert calls == []


@pytest.mark.parametrize("failure", ["unavailable", "permission", "none"])
def test_factory_failure_affects_sources_but_manual_export_still_works(tmp_path, failure):
    calls = []
    code, status = (
        ("PERMISSION_DENIED", 403)
        if failure == "permission"
        else (
            "RECORDS_BRIDGE_UNAVAILABLE",
            503,
        )
    )

    def unavailable_factory(runtime, principal):
        calls.append((runtime, principal))
        if failure == "none":
            return None
        raise CoreError(code, "Synthetic optional records provider failure", status)

    with configured(tmp_path, records_factory=unavailable_factory) as api:
        for kind in ("parties", "weighings"):
            response = source(api, kind)
            assert response.status_code == status
            assert response.json()["error"]["code"] == code
        assert len(calls) == 2
        contract = create(api)
        ok(api.client.post(PREFIX + "/preview", json={"data": data()}))
        version = export(api, contract, formats=["docx"])
        assert version["files"]["docx"]["status"] == "succeeded"
        assert len(calls) == 2


def test_concurrent_sources_use_fresh_current_principal_and_typed_read_only_dtos(tmp_path):
    calls = []
    lock = Lock()

    def scoped_factory(runtime: Runtime, principal: Principal):
        provider = ActorRecords(principal.username, principal.version)
        with lock:
            calls.append((runtime, principal, provider))
        return provider

    with configured(tmp_path, records_factory=scoped_factory) as api:
        ready = Barrier(4)

        def read_pair(username, kind):
            ready.wait(timeout=5)
            return [source(api, kind, username=username) for _ in range(2)]

        requests = [
            (username, kind)
            for username in ("admin", OPERATOR)
            for kind in ("parties", "weighings")
        ]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(read_pair, username, kind) for username, kind in requests]
            responses = [future.result(timeout=15) for future in futures]
        for (username, kind), pair in zip(requests, responses, strict=True):
            expected = ActorRecords(username, 1)
            for response in pair:
                assert response.status_code == 200, response.text
                if kind == "parties":
                    assert PartyDTO.model_validate_json(response.text) == expected.party
                else:
                    assert WeighingDTO.model_validate_json(response.text) == expected.weighing
        assert len(calls) == len({id(provider) for _, _, provider in calls}) == 8
        for runtime, principal, provider in calls:
            assert runtime is api.runtime
            assert principal.id == api.users[principal.username]["id"]
            assert principal.role == ("admin" if principal.username == "admin" else "operator")
            assert principal.version == 1
            principal.require("records.read")
            expected = ActorRecords(principal.username, principal.version)
            assert provider.party == expected.party
            assert provider.weighing == expected.weighing
        with api.runtime.reader() as conn:
            assert not any(
                name.startswith(("records_", "accounting_"))
                for name in inspect(conn).get_table_names()
            )
            assert conn.execute(select(DRAFTS)).all() == []
            assert conn.execute(select(VERSIONS)).all() == []
            assert conn.execute(select(AUDIT).where(AUDIT.c.entity.like("contracts.%"))).all() == []
            assert (
                conn.execute(select(REQUESTS).where(REQUESTS.c.action.like("contracts.%"))).all()
                == []
            )


def test_factory_observes_new_login_role_and_version_and_never_sees_disabled_session(tmp_path):
    calls = []

    def scoped_factory(runtime, principal):
        calls.append(principal)
        return ActorRecords(principal.username, principal.version)

    with configured(tmp_path, records_factory=scoped_factory) as api:
        assert ok(source(api, username=OPERATOR))["version"] == 1
        first = calls[-1]
        old_authorization = api.authorizations[OPERATOR]
        ok(api.client.post("/api/v1/auth/logout", headers={"Authorization": old_authorization}))
        assert source(api, username=OPERATOR).status_code == 401
        assert len(calls) == 1
        login = ok(
            api.client.post(
                "/api/v1/auth/login",
                json={
                    "username": OPERATOR,
                    "password": PASSWORD,
                },
            )
        )
        api.authorizations[OPERATOR] = "Bearer " + login["access_token"]
        ok(source(api, username=OPERATOR))
        assert calls[-1] is not first
        assert calls[-1].id == first.id and calls[-1].version == first.version == 1
        updated = ok(
            api.client.patch(
                "/api/v1/users/" + first.id,
                json={
                    "request_key": "promote-factory-operator",
                    "expected_version": 1,
                    "role": "admin",
                    "active": True,
                },
            )
        )
        assert updated["version"] == 2
        assert source(api, username=OPERATOR).status_code == 401
        assert len(calls) == 2
        login = ok(
            api.client.post(
                "/api/v1/auth/login",
                json={
                    "username": OPERATOR,
                    "password": PASSWORD,
                },
            )
        )
        api.authorizations[OPERATOR] = "Bearer " + login["access_token"]
        assert ok(source(api, "weighings", username=OPERATOR))["version"] == 2
        assert calls[-1].id == first.id
        assert calls[-1].role == "admin" and calls[-1].version == 2
        ok(
            api.client.patch(
                "/api/v1/users/" + first.id,
                json={
                    "request_key": "disable-factory-operator",
                    "expected_version": 2,
                    "role": "admin",
                    "active": False,
                },
            )
        )
        assert source(api, username=OPERATOR).status_code == 401
        assert len(calls) == 3


def test_source_permission_is_checked_before_factory_and_manual_entry_remains_available(
    tmp_path, monkeypatch
):
    original_principal = AuthService._principal

    def without_records(row):
        principal = original_principal(row)
        if principal.username == OPERATOR:
            return replace(
                principal,
                permissions=tuple(
                    permission
                    for permission in principal.permissions
                    if permission != "records.read"
                ),
            )
        return principal

    monkeypatch.setattr(AuthService, "_principal", staticmethod(without_records))
    calls = []

    def forbidden_factory(runtime, principal):
        calls.append(principal)
        raise AssertionError("Source permissions must be checked before constructing records")

    with configured(tmp_path, records_factory=forbidden_factory) as api:
        for kind in ("parties", "weighings"):
            response = source(api, kind, username=OPERATOR)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"
        api.client.headers["Authorization"] = api.authorizations[OPERATOR]
        ok(api.client.post(PREFIX + "/preview", json={"data": data()}))
        contract = create(api)
        version = export(api, contract, formats=["docx"])
        assert version["files"]["docx"]["status"] == "succeeded"
        assert calls == []


@pytest.mark.parametrize("available", [False, True])
def test_legacy_static_bridge_or_no_bridge_keeps_existing_source_behavior(tmp_path, available):
    provider = ActorRecords("legacy", 7)
    with configured(tmp_path, records=provider if available else None) as api:
        for kind, expected in (("parties", provider.party), ("weighings", provider.weighing)):
            response = source(api, kind)
            if available:
                assert ok(response) == expected.model_dump(mode="json")
            else:
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "RECORDS_BRIDGE_UNAVAILABLE"
        contract = create(api)
        assert export(api, contract, formats=["docx"])["files"]["docx"]["status"] == "succeeded"


def test_static_bridge_and_factory_are_mutually_exclusive():
    provider = ActorRecords("legacy", 1)
    with pytest.raises(ValueError):
        module_manifest(provider, records_factory=lambda runtime, principal: provider)
