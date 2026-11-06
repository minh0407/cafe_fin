"""Test-only real HTTP bootstrap with the records manifest; no root registry edits."""

import json
import socket
import sys
import threading
import time
from unittest.mock import patch

import uvicorn
from cafe_fin.core import api as core_api
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.records.module import module_manifest


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    boot = json.loads(sys.stdin.readline())
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


if __name__ == "__main__":
    main()
