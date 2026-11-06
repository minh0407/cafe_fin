"""Sidecar IPC v1. stdin/stdout only; secrets never enter argv, URLs or logs."""

import json
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cafe_fin.core.api import ALLOWED_ORIGINS, PROTOCOL_VERSION, create_app
from cafe_fin.core.errors import CoreError
from cafe_fin.core.runtime import Runtime


class BootRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: int
    session_token: str = Field(
        min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", repr=False
    )
    data_root: str = Field(min_length=1, max_length=32767)
    initialize: bool = False
    allowed_origin: str


def main() -> int:
    runtime, listener, server, server_thread = None, None, None, None
    error = None
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        if len(sys.argv) != 1:
            raise CoreError("BOOT_ARGUMENTS_DENIED", "Khởi động backend qua ứng dụng desktop.", 503)
        line = sys.stdin.readline(65537)
        if not line.endswith("\n") or len(line) > 65536:
            raise CoreError("BOOT_PROTOCOL_INVALID", "Thiếu thông tin khởi động hợp lệ.", 503)
        boot = BootRequest.model_validate_json(line)
        if boot.protocol_version != PROTOCOL_VERSION or boot.allowed_origin not in ALLOWED_ORIGINS:
            raise CoreError("BOOT_PROTOCOL_INVALID", "Phiên bản giao thức không tương thích.", 503)
        if not Path(boot.data_root).is_absolute():
            raise CoreError(
                "BOOT_PROTOCOL_INVALID", "Thư mục dữ liệu phải là đường dẫn tuyệt đối.", 503
            )
        runtime = Runtime(boot.data_root, initialize=boot.initialize)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        app = create_app(runtime, boot.session_token, port=port, origin=boot.allowed_origin)
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_config=None,
            log_level="critical",
            server_header=False,
        )
        server = uvicorn.Server(config)
        server_failed = threading.Event()

        def serve():
            try:
                server.run(sockets=[listener])
            except BaseException:
                # Uvicorn may raise SystemExit on lifespan failure. IPC must still
                # emit a sanitized startup error instead of an optimistic ready.
                server_failed.set()

        def parent_control():
            while True:
                command = sys.stdin.readline(4097)
                if not command:
                    server.should_exit = True
                    return
                try:
                    if len(command) <= 4096 and json.loads(command) == {"command": "shutdown"}:
                        server.should_exit = True
                        return
                except (ValueError, TypeError):
                    pass

        threading.Thread(target=parent_control, name="cafe-fin-ipc", daemon=True).start()
        server_thread = threading.Thread(target=serve, name="cafe-fin-http", daemon=True)
        server_thread.start()
        startup_deadline = time.monotonic() + 15
        while not server.started and server_thread.is_alive():
            if time.monotonic() >= startup_deadline:
                server.should_exit = True
                raise CoreError(
                    "STARTUP_TIMEOUT", "Backend chưa sẵn sàng trong thời hạn khởi động.", 503
                )
            time.sleep(0.01)
        if not server.started or server_failed.is_set() or not server_thread.is_alive():
            raise CoreError("STARTUP_FAILED", "Không thể khởi động các dịch vụ dữ liệu local.", 503)
        print(
            json.dumps(
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "status": "ready",
                    "api_base": f"http://127.0.0.1:{port}/api/v1",
                }
            ),
            flush=True,
        )
        server_thread.join()
        if server_failed.is_set():
            raise CoreError("BACKEND_FAILED", "Backend local đã dừng do lỗi.", 503)
    except (ValidationError, ValueError, TypeError):
        error = CoreError("BOOT_PROTOCOL_INVALID", "Thông tin khởi động không hợp lệ.", 503)
    except CoreError as exc:
        error = exc
    except Exception:
        error = CoreError(
            "STARTUP_FAILED", "Không thể mở dữ liệu local. Kiểm tra cấu hình và thư mục.", 503
        )
    finally:
        if server_thread and server_thread.is_alive():
            server.should_exit = True
            server_thread.join(timeout=10)
        if listener:
            listener.close()
        if runtime:
            try:
                runtime.close()
            except Exception:
                error = CoreError("SHUTDOWN_FAILED", "Tác vụ chưa đóng tại ranh giới an toàn.", 503)
    if error is None:
        return 0
    print(
        json.dumps(
            {
                "protocol_version": PROTOCOL_VERSION,
                "status": "error",
                "api_base": "",
                "code": error.code,
                "message": error.message,
            },
            ensure_ascii=True,
        ),
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
