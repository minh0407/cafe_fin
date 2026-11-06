"""Test-only real HTTP bootstrap with the records manifest; no root registry edits."""

import json
import socket
import sys
import threading
import time

import uvicorn
from cafe_fin.core.api import create_app
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.records.module import module_manifest


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    boot = json.loads(sys.stdin.readline())
    runtime = Runtime(boot["data_root"], initialize=True, modules=ModuleRegistry((module_manifest(),)))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    app = create_app(runtime, boot["session_token"], port=port, origin="http://tauri.localhost")
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
