"""Isolated browser-test Runtime. Synthetic sources and failure controls are test-only."""

import json
import socket
import sys
import threading
import time
from datetime import date

import uvicorn
from cafe_fin.contracts import service as contracts_service
from cafe_fin.contracts.module import module_manifest
from cafe_fin.core.api import create_app
from cafe_fin.core.contracts import PartyDTO, WeighingDTO, WeightLineInput
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime

PARTY_ID = "460b42cd-3b86-43b4-90f9-c811bb912ba4"
WEIGHING_ID = "7836b8e8-366a-4d09-9ffc-36b6d8356385"


class SyntheticSources:
    revision = 1

    def lookup_party(self, identity):
        if identity != PARTY_ID:
            return None
        return PartyDTO(
            id=PARTY_ID,
            version=self.revision,
            type="company",
            name=f"Đối tác nguồn phiên bản {self.revision}",
            address="Địa chỉ tổng hợp",
        )

    def get_weighing(self, identity):
        if identity != WEIGHING_ID:
            return None
        return WeighingDTO(
            id=WEIGHING_ID,
            version=self.revision,
            code="CAN-TONG-HOP",
            occurred_on=date(2026, 11, 6),
            party_id=PARTY_ID,
            lines=(
                WeightLineInput(
                    description="Cà phê cân tổng hợp", net_kg="12.345", quantity_source="direct"
                ),
            ),
        )


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    boot = json.loads(sys.stdin.readline())
    bridge = SyntheticSources()
    failures = {"pdf": False}
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
    app = create_app(runtime, boot["session_token"], port=port, origin="http://127.0.0.1:1420")

    @app.post("/api/v1/harness/source-revision")
    def change_source():
        bridge.revision += 1
        return {"revision": bridge.revision}

    @app.post("/api/v1/harness/toggle-pdf-failure")
    def toggle_pdf_failure():
        failures["pdf"] = not failures["pdf"]
        return failures

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
