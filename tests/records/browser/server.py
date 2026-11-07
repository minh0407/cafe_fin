"""Test-only real HTTP bootstrap with the records manifest; no root registry edits."""

import json
import os
import secrets
import socket
import sys
import threading
import time
from contextlib import ExitStack
from datetime import date, timedelta
from unittest.mock import patch

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse
from cafe_fin.core import api as core_api
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.records.module import module_manifest


class SyntheticMarket:
    """Only enabled by the browser test process; never a product API/provider."""

    def __init__(self, mode):
        if mode not in {"fresh", "blocked", "stale"}:
            raise ValueError("Unknown synthetic market mode")
        self.mode, self.fetch_count = mode, 0
        self.lock = threading.Lock()

    def download(self):
        from cafe_fin.records import market, market_http

        with self.lock:
            self.fetch_count += 1
            mode = self.mode
        if mode == "blocked":
            return "<title>Just a moment</title><div>cf-chl-synthetic</div>"
        day = date.fromisoformat(market.today()) - timedelta(days=mode == "stale")
        dataset = {
            "@type": "Dataset",
            "@id": market_http.SOURCE_URL + "#dataset",
            "dateModified": day.isoformat() + "T08:00:00+07:00",
            "variableMeasured": [
                {"name": "Cà phê Gia Lai (đồng/kg)", "unitText": "VND", "value": "103000"}
            ],
        }
        return '<script type="application/ld+json">' + json.dumps(dataset) + "</script>"

    def install_controls(self, app, runtime, control_key):
        if not isinstance(control_key, str) or len(control_key) < 32:
            raise ValueError("Synthetic market control key required")

        @app.post("/api/v1/__records_test_market", include_in_schema=False)
        async def control(request: Request):
            from cafe_fin.records import market

            data = await request.json()
            # Core middleware additionally requires the app session and local login.
            supplied = data.get("control_key", "")
            if not isinstance(supplied, str) or not secrets.compare_digest(supplied, control_key):
                return JSONResponse({"error": "Synthetic control denied"}, status_code=403)
            with runtime.reader() as conn:
                runtime.auth.authorize(conn, request.state.principal, "records.write")
            if data.get("action") == "source":
                if data.get("mode") not in {"fresh", "blocked", "stale"}:
                    return JSONResponse({"error": "Unknown source mode"}, status_code=422)
                with self.lock:
                    self.mode = data["mode"]
                if data.get("expire_cooldown") is True:
                    # Deterministic fixture clock/cooldown control; no production hook.
                    runtime.writer.run(lambda conn: conn.execute(market.DAYS.update().where(
                        market.DAYS.c.price_date == market.today()
                    ).values(next_attempt_at=market.stamp(market.now() - timedelta(seconds=1)))))
            elif data.get("action") != "stats":
                return JSONResponse({"error": "Unknown synthetic control"}, status_code=422)
            with self.lock:
                result = {"mode": self.mode, "fetch_count": self.fetch_count}
            return result | {"periodic": runtime.periodic.status()}


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    boot = json.loads(sys.stdin.readline())
    synthetic_market = os.getenv("CAFE_FIN_RECORDS_TEST_MARKET") == "1"
    # Existing suites must never acquire WAN access from production defaults.
    os.environ["CAFE_FIN_MARKET_NETWORK"] = "1" if synthetic_market else "0"
    fixtures = ExitStack()
    source = None
    if synthetic_market:
        from cafe_fin.records import market_http

        source = SyntheticMarket(boot.get("market_mode", "fresh"))
        fixtures.enter_context(patch.object(market_http, "download_html", source.download))
    web_port = boot["web_port"]
    if type(web_port) is not int or not 1 <= web_port <= 65535:
        raise ValueError("Records test web_port must be an integer between 1 and 65535")
    origin = f"http://127.0.0.1:{web_port}"
    runtime = Runtime(boot["data_root"], initialize=True, modules=ModuleRegistry((module_manifest(),)))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    # Fixture-only bootstrap origin. Production constants/CSP are untouched;
    # restore the original allowlist immediately after constructing this app.
    production_origins = core_api.ALLOWED_ORIGINS
    with patch.object(core_api, "ALLOWED_ORIGINS", frozenset({origin})):
        app = core_api.create_app(runtime, boot["session_token"], port=port, origin=origin)
    if source:
        source.install_controls(app, runtime, boot.get("market_control_key"))
    assert core_api.ALLOWED_ORIGINS is production_origins
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, log_config=None, log_level="critical"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Records test server did not start")
            time.sleep(0.02)
        print(json.dumps({"api_base": f"http://127.0.0.1:{port}/api/v1", "session_token": boot["session_token"], "data_root": boot["data_root"], "protocol_version": 1}), flush=True)
        sys.stdin.readline()
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        runtime.close()
        listener.close()
        fixtures.close()


if __name__ == "__main__":
    main()
