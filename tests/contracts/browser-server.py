"""Isolated browser-test Runtime. Synthetic sources and failure controls are test-only."""

import json
import socket
import sys
import threading
import time
from datetime import date
from unittest.mock import patch
from uuid import NAMESPACE_DNS, uuid5

import uvicorn
from cafe_fin.contracts import service as contracts_service
from cafe_fin.contracts.module import module_manifest
from cafe_fin.core import api as core_api
from cafe_fin.core.api import require
from cafe_fin.core.contracts import PartyDTO, WeighingDTO, WeightLineInput
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from fastapi import Query, Request

PARTY_ID = "460b42cd-3b86-43b4-90f9-c811bb912ba4"
WEIGHING_ID = "7836b8e8-366a-4d09-9ffc-36b6d8356385"
TWIN_PARTY_ID = "460b42cd-3b86-43b4-90f9-c811bb912ba5"
TWIN_WEIGHING_ID = "7836b8e8-366a-4d09-9ffc-36b6d8356386"


class SyntheticSources:
    revision = 1

    def lookup_party(self, identity):
        if identity not in (PARTY_ID, TWIN_PARTY_ID):
            return None
        return PartyDTO(
            id=identity,
            version=self.revision,
            type="company",
            name=f"Đối tác nguồn & Đắk Lắk · v{self.revision}",
            address="Địa chỉ tổng hợp" if identity == PARTY_ID else "Địa chỉ bản ghi thứ hai",
        )

    def get_weighing(self, identity):
        if identity not in (WEIGHING_ID, TWIN_WEIGHING_ID):
            return None
        return WeighingDTO(
            id=identity,
            version=self.revision,
            code="CÂN ĐẮK LẮK & 01",
            occurred_on=date(2026, 11, 6),
            party_id=PARTY_ID,
            lines=(
                WeightLineInput(
                    description="Cà phê cân tổng hợp"
                    if identity == WEIGHING_ID
                    else "Cà phê cân bản ghi thứ hai",
                    net_kg="12.345",
                    quantity_source="direct",
                ),
            ),
        )


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    boot = json.loads(sys.stdin.readline())
    bridge = SyntheticSources()
    failures = {"pdf": False}
    records_mode = {"status": 200}
    renderer = contracts_service.IndependentDocumentRenderer

    class ControlledRenderer(renderer):
        def pdf(self, snapshot):
            if failures["pdf"]:
                raise CoreError(
                    "SYNTHETIC_PDF_FAILURE", "Lỗi PDF tổng hợp để kiểm tra khôi phục.", 503
                )
            return super().pdf(snapshot)

    contracts_service.IndependentDocumentRenderer = ControlledRenderer
    runtime = Runtime(
        boot["data_root"], initialize=True, modules=ModuleRegistry((module_manifest(bridge),))
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    # Test-only bootstrap allowance for this lane's dedicated dev server. Restore
    # the production allowlist immediately; actual ScopeGuard/auth/CORS remain real
    # and bind strictly to this one origin for the lifetime of this fixture app.
    test_origin = "http://127.0.0.1:1422"
    with patch.object(core_api, "ALLOWED_ORIGINS", core_api.ALLOWED_ORIGINS | {test_origin}):
        app = core_api.create_app(runtime, boot["session_token"], port=port, origin=test_origin)

    @app.post("/api/v1/harness/source-revision")
    def change_source():
        bridge.revision += 1
        return {"revision": bridge.revision}

    @app.post("/api/v1/harness/toggle-pdf-failure")
    def toggle_pdf_failure():
        failures["pdf"] = not failures["pdf"]
        return failures

    @app.post("/api/v1/harness/records-mode/{status}")
    def change_records_mode(status: int):
        records_mode["status"] = status
        return records_mode

    def record_page(kind, page, page_size, search):
        if records_mode["status"] != 200:
            raise CoreError(
                "RECORDS_UNAVAILABLE",
                "Nguồn ghi nhận tổng hợp chưa truy cập được.",
                records_mode["status"],
            )
        if kind == "parties":
            items = [
                {
                    "id": str(uuid5(NAMESPACE_DNS, f"contracts-browser-party-{index}")),
                    "code": f"DT-{index:03}",
                    "name": f"Đối tác nguồn & Đắk Lắk · v{bridge.revision}",
                }
                for index in range(50)
            ]
            items += [
                {
                    "id": identity,
                    "code": "DT-TRUNG",
                    "name": f"Đối tác nguồn & Đắk Lắk · v{bridge.revision}",
                }
                for identity in (PARTY_ID, TWIN_PARTY_ID)
            ]
        else:
            items = [
                {
                    "id": str(uuid5(NAMESPACE_DNS, f"contracts-browser-weighing-{index}")),
                    "code": f"CÂN ĐẮK LẮK & {index + 100}",
                    "occurred_on": "2026-11-06",
                    "party_id": PARTY_ID,
                    "lines": [],
                }
                for index in range(50)
            ]
            items += [
                bridge.get_weighing(identity).model_dump(mode="json")
                for identity in (WEIGHING_ID, TWIN_WEIGHING_ID)
            ]
        if search:
            items = [
                item
                for item in items
                if search.casefold() in f"{item['code']} {item.get('name', '')}".casefold()
            ]
        start = (page - 1) * page_size
        return {
            "items": items[start : start + page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
        }

    @app.get("/api/v1/records/parties")
    def parties(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=50),
        search: str = Query("", max_length=200),
    ):
        require(request, "records.read")
        return record_page("parties", page, page_size, search)

    @app.get("/api/v1/records/weighings")
    def weighings(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=50),
        search: str = Query("", max_length=200),
    ):
        require(request, "records.read")
        return record_page("weighings", page, page_size, search)

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_config=None,
            log_level="critical",
        )
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("Browser Runtime did not start")
    print(json.dumps({"api_base": f"http://127.0.0.1:{port}/api/v1"}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        runtime.close()


if __name__ == "__main__":
    main()
