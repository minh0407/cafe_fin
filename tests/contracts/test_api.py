"""Contract HTTP integration proofs using only synthetic records and isolated roots."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.contracts.migrations.v001 import DRAFTS, LINES, OUTPUTS
from cafe_fin.contracts.module import module_manifest
from cafe_fin.contracts.schemas import TEMPLATE_IDS
from cafe_fin.core.api import create_app
from cafe_fin.core.contracts import (
    InventorySummaryDTO,
    PartyDTO,
    ReceivableSummaryDTO,
    WeighingDTO,
    WeightLineInput,
)
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.renderers import DocumentRenderer
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import FILES
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import inspect, select

TOKEN = "synthetic-contract-session-0123456789abcdef"
PORT = 48932
PREFIX = "/api/v1/contracts"
PASSWORD = "synthetic-password"


def data(kind="purchase"):
    return {
        "kind": kind,
        "number": f"THU-{kind}-01",
        "occurred_on": "2026-11-06",
        "place": "Địa điểm tổng hợp",
        "template_id": TEMPLATE_IDS[kind],
        "company": {"type": "company", "name": "Công ty thử", "roles": ["buyer"]},
        "counterparty": {"type": "person", "name": "Đối tác thử"},
        "lines": [
            {
                "description": "Cà phê tổng hợp",
                "quantity_kg": "12.345",
                "unit_price": "45678.90",
                "net_kg": "12.345",
            }
        ],
        "tax": {"mode": "none"},
        "terms": {
            "delivery": "Giao tại kho thử",
            "quality": "Chất lượng do hai bên ghi",
            "additional": "Điều khoản riêng\nDòng tiếp theo",
        },
        "payment": {
            "method": "mixed",
            "description": "Trả hai đợt tổng hợp",
            "deposit_amount": "100.00",
            "recorded_paid_amount": "50.00",
            "schedule": [{"due_on": "2026-12-01", "amount": "200.00"}],
        },
    }


@pytest.mark.parametrize("kind", ["purchase", "sale"])
@pytest.mark.parametrize("revised_template", [False, True])
def test_preview_export_and_returned_snapshot_share_canonical_hash(api, kind, revised_template):
    payload = data(kind)
    if revised_template:
        template = next(
            row for row in ok(api.client.get(PREFIX + "/templates"))["items"] if row["kind"] == kind
        )
        ok(
            api.client.patch(
                PREFIX + "/templates/" + template["id"],
                json={
                    "request_key": "hash-template",
                    "expected_version": template["version"],
                    "title": template["title"],
                    "body": template["body"] + "\nNội dung mẫu sửa thử.",
                },
            )
        )
    preview = ok(api.client.post(PREFIX + "/preview", json={"data": payload}))
    saved = ok(api.client.post(PREFIX, json={"request_key": "hash-save", "data": payload}))
    version = export(api, saved)
    canonical = json.dumps(
        version["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    assert hashlib.sha256(canonical.encode()).hexdigest() == version["snapshot_sha256"]
    assert preview["snapshot_sha256"] == version["snapshot_sha256"]
    assert preview["document"] == version["snapshot"]["document"]


@contextmanager
def running(root, *, initialize=True, bridge=None):
    runtime = Runtime(
        root, initialize=initialize, modules=ModuleRegistry((module_manifest(bridge),))
    )
    app = create_app(runtime, TOKEN, port=PORT)
    with TestClient(
        app, base_url=f"http://127.0.0.1:{PORT}", raise_server_exceptions=False
    ) as client:
        client.headers.update({"X-App-Session": TOKEN, "Origin": "http://tauri.localhost"})
        endpoint = "setup" if initialize else "login"
        auth = client.post(
            f"/api/v1/auth/{endpoint}", json={"username": "admin", "password": PASSWORD}
        )
        assert auth.status_code == 200, auth.text
        client.headers["Authorization"] = "Bearer " + auth.json()["access_token"]
        yield SimpleNamespace(runtime=runtime, client=client, root=root)


@pytest.fixture
def api(tmp_path):
    with running(tmp_path / "Dữ liệu hợp đồng") as value:
        yield value


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def create(api, payload=None, key="create"):
    return ok(api.client.post(PREFIX, json={"request_key": key, "data": payload or data()}))


def export(api, contract, *, key="export", formats=None):
    return ok(
        api.client.post(
            f"{PREFIX}/{contract['id']}/exports",
            json={
                "request_key": key,
                "expected_version": contract["version"],
                "formats": formats or ["docx", "pdf"],
            },
        )
    )


def download(api, contract, version, format):
    response = api.client.get(f"{PREFIX}/{contract['id']}/versions/{version['id']}/files/{format}")
    assert response.status_code == 200, response.text
    state = version["files"][format]
    assert hashlib.sha256(response.content).hexdigest() == state["sha256"]
    assert response.headers["x-content-sha256"] == state["sha256"]
    assert len(response.content) == state["size"]
    return response.content


@pytest.mark.parametrize("kind", ["purchase", "sale"])
def test_manual_export_without_records_and_replay_exact_snapshot_and_files(api, kind):
    contract = create(api, data(kind))
    assert contract["version"] == 1
    version = export(api, contract)
    assert version["sequence"] == version["contract_version"] == 1
    assert {x["status"] for x in version["files"].values()} == {"succeeded"}
    contents = {f: download(api, contract, version, f) for f in ("docx", "pdf")}
    word = "\n".join(p.text for p in Document(io.BytesIO(contents["docx"])).paragraphs)
    pdf = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(contents["pdf"])).pages)
    for text in (word, pdf):
        for expected in (
            "Cà phê tổng hợp",
            "Điều khoản riêng",
            "Giao tại kho thử",
            "Trả hai đợt tổng hợp",
            "2026-12-01",
        ):
            assert expected in text
        assert "{{" not in text
    assert export(api, contract) == version
    assert {f: download(api, contract, version, f) for f in contents} == contents
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions"))["total"] == 1
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/attachments"))["total"] == 0
    unavailable = api.client.get(f"{PREFIX}/sources/parties/{uuid4()}")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "RECORDS_BRIDGE_UNAVAILABLE"
    with api.runtime.reader() as conn:
        tables = inspect(conn).get_table_names()
        assert not any(t.startswith(("records_", "accounting_")) for t in tables)
        assert len(conn.execute(select(FILES)).all()) == 2
        draft_row = conn.execute(select(DRAFTS)).mappings().one()
        line_row = conn.execute(select(LINES)).mappings().one()
        assert draft_row["quantity_milli"] == line_row["quantity_milli"] == 12345
        assert line_row["unit_price_cents"] == 4567890
        assert draft_row["subtotal_cents"] == line_row["amount_cents"] == 56390602
        assert draft_row["total_cents"] == 56390602
        assert line_row["net_milli"] == 12345
        assert line_row["gross_milli"] is line_row["tare_milli"] is None


def test_commands_replay_conflicts_stale_version_and_history(api):
    original = data()
    contract = create(api, original)
    assert create(api, original) == contract
    changed = copy.deepcopy(original)
    changed["number"] = "THU-edited"
    conflict = api.client.post(PREFIX, json={"request_key": "create", "data": changed})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    edited = ok(
        api.client.patch(
            f"{PREFIX}/{contract['id']}",
            json={"request_key": "edit", "expected_version": 1, "data": changed},
        )
    )
    assert edited["version"] == 2
    for path, payload in (
        (
            f"{PREFIX}/{contract['id']}",
            {"request_key": "stale-edit", "expected_version": 1, "data": original},
        ),
        (
            f"{PREFIX}/{contract['id']}/exports",
            {"request_key": "stale-export", "expected_version": 1, "formats": ["docx"]},
        ),
    ):
        response = (api.client.patch if path.endswith(contract["id"]) else api.client.post)(
            path, json=payload
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "VERSION_CONFLICT"
    version = export(api, edited, formats=["docx"])
    changed_export = api.client.post(
        f"{PREFIX}/{contract['id']}/exports",
        json={"request_key": "export", "expected_version": 2, "formats": ["pdf"]},
    )
    assert changed_export.status_code == 409
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions"))["items"] == [version]
    history = ok(api.client.get(f"{PREFIX}/{contract['id']}/history"))
    assert history["total"] == 2
    assert {row["action"] for row in history["items"]} == {"create", "update"}


def test_concurrent_same_key_export_produces_one_version_and_one_file(api):
    contract = create(api)
    ready = threading.Barrier(2)

    def concurrent_export():
        ready.wait(timeout=5)
        return export(api, contract, key="concurrent", formats=["docx"])

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(concurrent_export)
        second = executor.submit(concurrent_export)
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert results[0] == results[1]
    assert results[0]["files"]["docx"]["status"] == "succeeded"
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions"))["total"] == 1
    with api.runtime.reader() as conn:
        assert len(conn.execute(select(FILES)).all()) == 1
        assert len(conn.execute(select(OUTPUTS)).all()) == 1


@pytest.mark.parametrize("recovery", ["same_key", "add_formats"])
def test_pdf_failure_preserves_docx_and_recovery_uses_same_version(api, monkeypatch, recovery):
    contract = create(api)
    original_pdf = DocumentRenderer.pdf

    def broken_pdf(self, snapshot):
        raise CoreError("PDF_TEST_UNAVAILABLE", "Synthetic local PDF failure", 503)

    monkeypatch.setattr(DocumentRenderer, "pdf", broken_pdf)
    partial = export(api, contract)
    assert partial["files"]["docx"]["status"] == "succeeded"
    assert partial["files"]["pdf"]["status"] == "failed"
    assert partial["files"]["pdf"]["error_code"] == "PDF_TEST_UNAVAILABLE"
    word = download(api, contract, partial, "docx")
    blocked = api.client.get(f"{PREFIX}/{contract['id']}/versions/{partial['id']}/files/pdf")
    assert blocked.status_code == 409
    monkeypatch.setattr(DocumentRenderer, "pdf", original_pdf)
    if recovery == "same_key":
        recovered = export(api, contract)
    else:
        recovered = ok(
            api.client.post(
                f"{PREFIX}/{contract['id']}/versions/{partial['id']}/files",
                json={"request_key": "add-pdf", "formats": ["pdf"]},
            )
        )
    assert recovered["id"] == partial["id"]
    assert recovered["snapshot"] == partial["snapshot"]
    assert recovered["files"]["docx"] == partial["files"]["docx"]
    assert recovered["files"]["pdf"]["status"] == "succeeded"
    assert download(api, contract, recovered, "docx") == word
    download(api, contract, recovered, "pdf")
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions"))["total"] == 1


def test_pdf_native_initialization_failure_does_not_block_docx(api, monkeypatch):
    contract = create(api)

    def missing_font(self):
        raise CoreError("RENDER_FONT_MISSING", "Synthetic missing local PDF font", 503)

    monkeypatch.setattr(DocumentRenderer, "__init__", missing_font)
    partial = export(api, contract)
    assert partial["files"]["docx"]["status"] == "succeeded"
    assert partial["files"]["pdf"]["status"] == "failed"
    assert partial["files"]["pdf"]["error_code"] == "RENDER_FONT_MISSING"
    download(api, contract, partial, "docx")


class SyntheticRecords:
    """Public DTO bridge only; mutable source replacement simulates another module."""

    def __init__(self):
        self.party = PartyDTO(id=str(uuid4()), version=1, type="person", name="Nguồn thử")
        self.weight = WeighingDTO(
            id=str(uuid4()),
            version=1,
            code="CAN-THU",
            occurred_on=date(2026, 11, 5),
            party_id=self.party.id,
            lines=(WeightLineInput(description="Cà phê nguồn", net_kg="10.000"),),
        )

    def lookup_party(self, identity: str) -> PartyDTO | None:
        return self.party if identity == self.party.id else None

    def get_weighing(self, identity: str) -> WeighingDTO | None:
        return self.weight if identity == self.weight.id else None

    def inventory_summary(
        self, from_on: date, through_on: date, *, cutoff: datetime
    ) -> InventorySummaryDTO:
        raise AssertionError("contracts must not query stock")

    def receivable_summary(self, as_of: date, *, cutoff: datetime) -> ReceivableSummaryDTO:
        raise AssertionError("contracts must not query receivables")


def test_bridge_copy_is_read_only_snapshot_survives_all_changes_and_soft_delete(tmp_path):
    bridge = SyntheticRecords()
    with running(tmp_path / "source-copy", bridge=bridge) as api:
        party = ok(api.client.get(f"{PREFIX}/sources/parties/{bridge.party.id}"))
        weight = ok(api.client.get(f"{PREFIX}/sources/weighings/{bridge.weight.id}"))
        payload = data()
        payload["counterparty"] = {k: v for k, v in party.items() if k not in ("id", "version")}
        payload["counterparty"]["name"] = "Bản chụp chỉnh riêng"
        payload["lines"][0].update(
            quantity_kg="9.000",
            source_snapshot=weight["lines"][0],
            source={
                "id": weight["id"],
                "version": weight["version"],
                "line_index": 0,
                "code": weight["code"],
                "occurred_on": weight["occurred_on"],
            },
        )
        payload["source_refs"] = [
            {"type": "party", "id": party["id"], "version": 1},
            {"type": "weighing", "id": weight["id"], "version": 1},
        ]
        source_before = (bridge.party.model_dump(), bridge.weight.model_dump())
        contract = create(api, payload)
        version = export(api, contract)
        old_bytes = {f: download(api, contract, version, f) for f in ("docx", "pdf")}
        assert (bridge.party.model_dump(), bridge.weight.model_dump()) == source_before
        bridge.party = bridge.party.model_copy(update={"version": 2, "name": "Nguồn đã đổi"})
        bridge.weight = bridge.weight.model_copy(
            update={"version": 2, "lines": (WeightLineInput(net_kg="99.000"),)}
        )
        payload["terms"]["additional"] = "Điều khoản bản mới"
        updated = ok(
            api.client.patch(
                f"{PREFIX}/{contract['id']}",
                json={"request_key": "edit-draft", "expected_version": 1, "data": payload},
            )
        )
        template = ok(api.client.get(f"{PREFIX}/templates"))["items"][0]
        changed_template = ok(
            api.client.patch(
                f"{PREFIX}/templates/{template['id']}",
                json={
                    "request_key": "template",
                    "expected_version": 1,
                    "title": template["title"],
                    "body": template["body"] + "\n\nMẫu mới",
                },
            )
        )
        assert changed_template["version"] == 2
        deleted = ok(
            api.client.request(
                "DELETE",
                f"{PREFIX}/{contract['id']}",
                json={"request_key": "delete", "expected_version": updated["version"]},
            )
        )
        assert deleted["deleted_at"]
        assert ok(api.client.get(PREFIX))["total"] == 0
        assert ok(api.client.get(PREFIX + "?include_deleted=true"))["total"] == 1
        assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions/{version['id']}")) == version
        assert {f: download(api, contract, version, f) for f in old_bytes} == old_bytes
        # An exact replay remains a lookup of the old snapshot even after deletion.
        assert export(api, contract) == version
        restored = ok(
            api.client.post(
                f"{PREFIX}/{contract['id']}/restore",
                json={"request_key": "restore", "expected_version": deleted["version"]},
            )
        )
        assert restored["deleted_at"] is None


def test_optional_attachment_signed_status_is_user_metadata_only(api):
    contract = create(api)
    version = export(api, contract, formats=["docx"])
    upload = ok(
        api.client.post(
            "/api/v1/files?category=documents",
            content=b"%PDF-1.7\nsynthetic",
            headers={
                "X-File-Name": "synthetic-signed.pdf",
                "X-Request-Key": "upload",
                "Content-Type": "application/pdf",
            },
        )
    )
    attachment_payload = {
        "request_key": "attach",
        "file_id": upload["id"],
        "version_id": version["id"],
        "note": "Người dùng ghi nhận bản ký",
        "status": "user_recorded_signed",
    }
    attachment = ok(
        api.client.post(f"{PREFIX}/{contract['id']}/attachments", json=attachment_payload)
    )
    assert attachment["signature_verification"] == "not_performed"
    assert attachment["status"] == "user_recorded_signed"
    assert attachment["sha256"] == upload["sha256"]
    assert (
        ok(api.client.post(f"{PREFIX}/{contract['id']}/attachments", json=attachment_payload))
        == attachment
    )
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/attachments"))["items"] == [attachment]
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}")) == contract
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions/{version['id']}")) == version


def test_operator_can_export_but_cannot_administer_templates(api):
    ok(
        api.client.post(
            "/api/v1/users",
            json={
                "username": "operator",
                "password": PASSWORD,
                "role": "operator",
                "request_key": "operator-create",
            },
        )
    )
    token = ok(
        api.client.post("/api/v1/auth/login", json={"username": "operator", "password": PASSWORD})
    )["access_token"]
    api.client.headers["Authorization"] = "Bearer " + token
    contract = create(api)
    export(api, contract, formats=["docx"])
    template = ok(api.client.get(f"{PREFIX}/templates"))["items"][0]
    forbidden = api.client.patch(
        f"{PREFIX}/templates/{template['id']}",
        json={
            "request_key": "forbidden-template",
            "expected_version": 1,
            "title": template["title"],
            "body": template["body"],
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "PERMISSION_DENIED"
    assert ok(api.client.get(f"{PREFIX}/templates"))["items"][0] == template


@pytest.mark.parametrize(
    "field,value",
    [
        ("occurred_on", "2026-02-30"),
        ("number", " "),
        ("number", "bad\u0000text"),
        ("kind", "approval"),
        ("template_id", TEMPLATE_IDS["sale"]),
        ("lines", []),
        ("unknown", "forbidden"),
    ],
)
def test_malformed_contract_boundary_has_no_writes(api, field, value):
    payload = data()
    payload[field] = value
    response = api.client.post(PREFIX, json={"request_key": "invalid", "data": payload})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert ok(api.client.get(PREFIX))["total"] == 0


@pytest.mark.parametrize(
    "quantity,price",
    [
        (1.25, "1"),
        ("1.0001", "1"),
        ("-1", "1"),
        ("0", "1"),
        ("1", "1.001"),
        ("1", "NaN"),
        ("9223372036854775.808", "1"),
    ],
)
def test_decimal_boundary_rejects_float_precision_negative_nonfinite_and_overflow(
    api, quantity, price
):
    payload = data()
    payload["lines"][0].update(quantity_kg=quantity, unit_price=price)
    assert (
        api.client.post(PREFIX, json={"request_key": "bad-number", "data": payload}).status_code
        == 422
    )
    assert ok(api.client.get(PREFIX))["total"] == 0


def test_paging_search_and_bad_command_boundary(api):
    payload = data()
    payload["number"] = "literal_%"
    create(api, payload)
    create(api, data("sale"), key="sale")
    assert ok(api.client.get(PREFIX, params={"search": "_%"}))["total"] == 1
    result = ok(api.client.get(PREFIX, params={"kind": "sale", "page_size": 1}))
    assert result["total"] == 1 and result["items"][0]["kind"] == "sale"
    for query in ("page=0", "page_size=501", "sort=arbitrary", "kind=other"):
        assert api.client.get(PREFIX + "?" + query).status_code == 422
    assert api.client.get(PREFIX + "/not-a-uuid").status_code == 422
    assert (
        api.client.post(PREFIX, json={"request_key": "contains space", "data": data()}).status_code
        == 422
    )


def test_unsafe_markup_remains_literal_in_preview_and_export(api):
    literal = '<script>alert("synthetic")</script><img src="https://invalid.example/remote">'
    payload = data()
    payload["terms"]["additional"] = literal
    preview = ok(api.client.post(PREFIX + "/preview", json={"data": payload}))
    assert literal in "\n".join(preview["document"]["paragraphs"])
    contract = create(api, payload)
    version = export(api, contract)
    word = Document(io.BytesIO(download(api, contract, version, "docx")))
    assert literal in "\n".join(p.text for p in word.paragraphs)
    pdf = PdfReader(io.BytesIO(download(api, contract, version, "pdf")))
    assert literal in "\n".join(p.extract_text() for p in pdf.pages)


@pytest.mark.parametrize(
    "damage,code", [("missing", "FILE_MISSING"), ("modified", "FILE_HASH_MISMATCH")]
)
def test_download_verifies_bytes_before_success_headers(api, damage, code):
    contract = create(api)
    version = export(api, contract, formats=["docx"])
    stored = api.runtime.files.get(version["files"]["docx"]["file_id"])
    path = api.runtime.root.resolve_key(stored.relative_key)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupt synthetic bytes")
    response = api.client.get(f"{PREFIX}/{contract['id']}/versions/{version['id']}/files/docx")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert "content-disposition" not in response.headers
    assert "x-content-sha256" not in response.headers


@pytest.mark.parametrize(
    "damage,code", [("missing", "FILE_MISSING"), ("modified", "FILE_HASH_MISMATCH")]
)
@pytest.mark.parametrize("recovery", ["same_key", "add_formats"])
def test_export_retry_never_regenerates_damaged_history_and_exact_restore_recovers(
    api, monkeypatch, damage, code, recovery
):
    contract = create(api)
    version = export(api, contract, formats=["docx"])
    original = download(api, contract, version, "docx")
    saved_state = version["files"]["docx"]
    stored = api.runtime.files.get(saved_state["file_id"])
    path = api.runtime.root.resolve_key(stored.relative_key)
    if damage == "missing":
        path.unlink()
    else:
        corrupted = bytes([original[0] ^ 1]) + original[1:]
        path.write_bytes(corrupted)

    def forbidden_regeneration(*args, **kwargs):
        raise AssertionError("Historical bytes must be restored, never regenerated or re-stored")

    monkeypatch.setattr(DocumentRenderer, "docx", forbidden_regeneration)
    monkeypatch.setattr(api.runtime.files, "put", forbidden_regeneration)
    failed = export(api, contract, formats=["docx"])
    state = failed["files"]["docx"]
    assert state["status"] == "failed"
    assert state["error_code"] == code
    assert {k: v for k, v in failed.items() if k != "files"} == {
        k: v for k, v in version.items() if k != "files"
    }
    for field in ("file_id", "sha256", "size"):
        assert state[field] == saved_state[field]
    if damage == "missing":
        assert not path.exists()
    else:
        assert path.read_bytes() == corrupted

    path.write_bytes(original)
    if recovery == "same_key":
        recovered = export(api, contract, formats=["docx"])
    else:
        recovered = ok(
            api.client.post(
                f"{PREFIX}/{contract['id']}/versions/{version['id']}/files",
                json={"request_key": "restored-file", "formats": ["docx"]},
            )
        )
    restored_state = recovered["files"]["docx"]
    assert restored_state["status"] == "succeeded"
    assert restored_state["error_code"] is restored_state["error_message"] is None
    for field in ("file_id", "sha256", "size"):
        assert restored_state[field] == saved_state[field]
    assert {k: v for k, v in recovered.items() if k != "files"} == {
        k: v for k, v in version.items() if k != "files"
    }
    assert download(api, contract, recovered, "docx") == original
    assert ok(api.client.get(f"{PREFIX}/{contract['id']}/versions"))["total"] == 1
    with api.runtime.reader() as conn:
        assert len(conn.execute(select(FILES)).all()) == 1
        assert len(conn.execute(select(OUTPUTS)).all()) == 1
        assert conn.execute(select(OUTPUTS.c.rendered_bytes)).scalar_one() is None


@pytest.mark.parametrize("failure", ["file_store", "finalization"])
def test_file_or_db_failure_recovers_exact_staged_bytes_after_runtime_restart(
    tmp_path, monkeypatch, failure
):
    root = tmp_path / failure
    with running(root) as api:
        contract = create(api)
        original_put = api.runtime.files.put
        original_run = api.runtime.writer.run
        stored_files = []
        failed = False

        def intercepted_run(effect, *args, **kwargs):
            nonlocal failed
            if failure == "finalization" and stored_files and not failed:
                failed = True
                raise OSError("Synthetic database failure after FileStore.put")
            return original_run(effect, *args, **kwargs)

        def intercepted_put(*args, **kwargs):
            if failure == "file_store":
                raise OSError("Synthetic storage unavailable")
            result = original_put(*args, **kwargs)
            stored_files.append(result)
            return result

        monkeypatch.setattr(api.runtime.writer, "run", intercepted_run)
        monkeypatch.setattr(api.runtime.files, "put", intercepted_put)
        partial = export(api, contract, formats=["docx"])
        assert partial["files"]["docx"]["status"] == "failed"
        with api.runtime.reader() as conn:
            staged = conn.execute(
                select(OUTPUTS.c.rendered_bytes).where(OUTPUTS.c.version_id == partial["id"])
            ).scalar_one()
        assert staged and staged.startswith(b"PK")
        if failure == "finalization":
            assert len(stored_files) == 1
            with api.runtime.files.read(stored_files[0].id) as source:
                assert source.read() == staged
    with running(root, initialize=False) as restarted:

        def forbidden_render(*args, **kwargs):
            raise AssertionError("Recovery must use durable exact bytes, never rerender")

        monkeypatch.setattr(DocumentRenderer, "docx", forbidden_render)
        recovered = export(restarted, contract, formats=["docx"])
        assert recovered["id"] == partial["id"]
        assert recovered["snapshot"] == partial["snapshot"]
        assert recovered["files"]["docx"]["status"] == "succeeded"
        assert download(restarted, contract, recovered, "docx") == staged
        if stored_files:
            assert recovered["files"]["docx"]["file_id"] == stored_files[0].id
        with restarted.runtime.reader() as conn:
            assert len(conn.execute(select(FILES)).all()) == 1
            assert conn.execute(select(OUTPUTS.c.rendered_bytes)).scalar_one() is None
        assert ok(restarted.client.get(f"{PREFIX}/{contract['id']}/versions"))["total"] == 1
