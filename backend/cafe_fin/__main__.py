"""Sidecar IPC v1; one bounded binary private pipe, with optional maintenance v1."""

import socket
import sys
import threading
import time

import uvicorn
from pydantic import ValidationError

from cafe_fin.core.api import ALLOWED_ORIGINS, PROTOCOL_VERSION, create_app
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_protocol import (
    BootRequest,
    ControlDispatcher,
    FrameWriter,
    parse_command,
    read_frame,
    safe_code,
)
from cafe_fin.core.runtime import Runtime


def main() -> int:
    runtime = listener = server = server_thread = None
    boot = None
    error = None
    output = FrameWriter(sys.stdout.buffer)
    source = sys.stdin.buffer
    control_done, close_started, closed_ack, stopping = (threading.Event() for _ in range(4))
    control_error = []
    reported = threading.Event()
    try:
        if len(sys.argv) != 1:
            raise CoreError("BOOT_ARGUMENTS_DENIED", "Khởi động backend qua desktop.", 503)
        try:
            frame = read_frame(source)
            boot = BootRequest.model_validate(frame)
        except (ValidationError, CoreError, ValueError, TypeError, UnicodeError):
            raise CoreError(
                "BOOT_PROTOCOL_INVALID", "Thông tin khởi động không hợp lệ.", 503
            ) from None
        if boot.allowed_origin not in ALLOWED_ORIGINS:
            raise CoreError("BOOT_PROTOCOL_INVALID", "Origin khởi động không hợp lệ.", 503)
        try:
            runtime = Runtime(
                boot.data_root, initialize=boot.initialize, activation_mode=boot.activation_mode
            )
        except CoreError as exc:
            if exc.code == "BACKUP_ARCHIVE_NOT_ACTIVE":
                raise CoreError(
                    "MAINTENANCE_REQUIRED", "Dữ liệu cần đối chiếu qua desktop.", 503
                ) from None
            raise
        # Runtime's phase-2 boot guard is authoritative, before any lifespan/start.
        if boot.activation_mode == "active" and runtime.maintenance.status()["state"] != "ACTIVE":
            raise CoreError("MAINTENANCE_REQUIRED", "Dữ liệu cần đối chiếu qua desktop.", 503)
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
                server_failed.set()

        def verified_close():
            nonlocal listener
            close_started.set()
            server.should_exit = True
            runtime.close()
            server_thread.join(timeout=10)
            if server_thread.is_alive() or server_failed.is_set():
                raise CoreError("SHUTDOWN_FAILED", "HTTP backend chưa đóng hoàn toàn.", 503)
            # HTTP lifespan/finally has finished. Verify idempotent final teardown
            # BEFORE ACK; there is no later potentially failing close after ACK.
            runtime.close()
            if listener is not None:
                listener.close()
                listener = None

        dispatcher = (
            ControlDispatcher(runtime, boot.generation, close=verified_close)
            if boot.maintenance_protocol == 1
            else None
        )

        def parent_control():
            try:
                while not stopping.is_set():
                    frame = read_frame(source)
                    if stopping.is_set():
                        return
                    if frame is None:
                        raise CoreError("MAINTENANCE_PIPE_EOF", "Kênh điều khiển đã đóng.", 503)
                    if frame == {"command": "shutdown"}:
                        # Existing trusted-parent app exit; no CLOSED maintenance proof.
                        server.should_exit = True
                        return
                    if dispatcher is None:
                        raise CoreError(
                            "MAINTENANCE_PROTOCOL_INVALID", "Chưa thương lượng điều khiển.", 503
                        )
                    request = parse_command(frame)
                    response = dispatcher.execute(request)
                    output.write(response)
                    if dispatcher.close_attempted:
                        if response["status"] != "ok":
                            control_error.append(response["code"])
                        else:
                            closed_ack.set()
                        reported.set()
                        server.should_exit = True
                        return
            except CoreError as exc:
                control_error.append(safe_code(exc.code))
                server.should_exit = True
            except BaseException:
                control_error.append("MAINTENANCE_COMMAND_FAILED")
                server.should_exit = True
            finally:
                control_done.set()

        server_thread = threading.Thread(target=serve, name="cafe-fin-http", daemon=True)
        server_thread.start()
        startup_deadline = time.monotonic() + 15
        while not server.started and server_thread.is_alive():
            if time.monotonic() >= startup_deadline:
                server.should_exit = True
                raise CoreError("STARTUP_TIMEOUT", "Backend chưa sẵn sàng.", 503)
            time.sleep(0.01)
        if not server.started or server_failed.is_set() or not server_thread.is_alive():
            raise CoreError("STARTUP_FAILED", "Không thể khởi động backend local.", 503)
        handshake = {
            "protocol_version": PROTOCOL_VERSION,
            "status": "ready",
            "api_base": f"http://127.0.0.1:{port}/api/v1",
        }
        if boot.maintenance_protocol == 1:
            handshake.update(
                maintenance_protocol=1,
                generation=boot.generation,
                runtime_state=runtime.maintenance.status()["state"],
            )
        output.write(handshake)
        threading.Thread(target=parent_control, name="cafe-fin-ipc", daemon=True).start()
        while server_thread.is_alive():
            server_thread.join(timeout=0.05)
            if control_done.is_set() and control_error:
                raise CoreError(control_error[0], "Điều khiển backend chưa hoàn tất.", 503)
        if close_started.is_set():
            # The HTTP thread may end before the control thread writes its final ACK.
            control_done.wait()
        if control_error:
            raise CoreError(control_error[0], "Điều khiển backend chưa hoàn tất.", 503)
        if server_failed.is_set():
            raise CoreError("BACKEND_FAILED", "Backend local đã dừng do lỗi.", 503)
    except CoreError as exc:
        error = exc
    except BaseException:
        error = CoreError("STARTUP_FAILED", "Không thể mở dữ liệu local.", 503)
    finally:
        stopping.set()
        if not closed_ack.is_set():
            if server_thread and server_thread.is_alive():
                server.should_exit = True
                server_thread.join(timeout=10)
            if listener:
                listener.close()
            if runtime:
                try:
                    runtime.close()
                except BaseException:
                    error = CoreError("SHUTDOWN_FAILED", "Backend chưa đóng an toàn.", 503)
            if server_thread and server_thread.is_alive():
                error = CoreError("SHUTDOWN_FAILED", "HTTP backend chưa dừng an toàn.", 503)
    if error is None:
        return 0
    if not reported.is_set():
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "status": "error",
            "api_base": "",
            "code": error.code,
            "message": "Không thể hoàn tất phiên backend local.",
        }
        if boot is not None and boot.maintenance_protocol == 1:
            response.update(maintenance_protocol=1, generation=boot.generation, state="FAILED_HELD")
        try:
            output.write(response)
        except (OSError, CoreError):
            pass  # Broken private pipe is never a successful close acknowledgement.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
