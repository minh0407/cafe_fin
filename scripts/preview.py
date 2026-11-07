"""Docker-only, same-origin browser adapter around the unchanged desktop API.

The session capability exists only in this process and the frontend's memory.
This is a local preview, not a replacement for the Windows desktop controller.
"""

from __future__ import annotations

import secrets
import sqlite3
import uuid
from pathlib import Path

import uvicorn
from cafe_fin.core.api import create_app
from cafe_fin.core.errors import CoreError
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import MARKER
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

PORT = 1420
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
STARTUP_CODES = frozenset(
    {
        "SQLITE_UNSUPPORTED",
        "DATA_ROOT_INVALID",
        "DATA_ROOT_UNAVAILABLE",
        "DATA_ROOT_EXISTS",
        "DATA_ROOT_INCOMPLETE",
        "DATA_ROOT_VERSION",
        "DATA_ROOT_LOCKED",
        "DATABASE_MISSING",
        "PREVIEW_UI_MISSING",
        "MAINTENANCE_REQUIRED",
        "DISK_SPACE_LOW",
    }
)


def open_preview_runtime(data: Path) -> Runtime:
    """Only initialize an empty volume; never repair/replace unrecognized data."""
    # Match the production Database gate before Runtime can initialize a marker.
    # Never weaken the core check or leave a new volume partially initialized.
    if sqlite3.sqlite_version_info < (3, 51, 3) or sqlite3.sqlite_version_info == (3, 52, 0):
        raise CoreError(
            "SQLITE_UNSUPPORTED",
            "Runtime SQLite chưa có bản sửa WAL được hỗ trợ.",
            503,
            details={"sqlite_version": sqlite3.sqlite_version},
        )
    if not (data / MARKER).exists():
        if data.exists() and (not data.is_dir() or any(data.iterdir())):
            raise CoreError("DATA_ROOT_INVALID", "Volume chưa có dữ liệu Cafe Fin hợp lệ.", 409)
        return Runtime(data, initialize=True)
    return Runtime(data)


class BrowserPreview:
    def __init__(self, runtime: Runtime, frontend: Path):
        self.runtime = runtime
        self.token = secrets.token_urlsafe(32)
        self.api = create_app(runtime, self.token, port=PORT, origin=ORIGIN)
        self.index = frontend / "index.html"
        if not self.index.is_file():
            raise CoreError("PREVIEW_UI_MISSING", "Chưa build giao diện xem thử.", 503)
        self.assets = StaticFiles(directory=frontend / "assets", follow_symlink=False)

    async def __call__(self, scope, receive, send):
        # Delegate the actual API lifespan so its real workers and teardown run.
        if scope["type"] == "lifespan":
            return await self.api(scope, receive, send)
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return

        async def secured_send(message):
            if message["type"] == "http.response.start":
                # Same-origin only: this outer transport grants no CORS capability.
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if not key.lower().startswith(b"access-control-")
                    and key.lower() not in {b"cache-control", b"x-content-type-options"}
                ]
                message["headers"] = headers + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cross-origin-resource-policy", b"same-origin"),
                    (b"x-frame-options", b"DENY"),
                ]
            await send(message)

        async def reject(code, status=403):
            error = CoreError(code, "Yêu cầu xem thử local không được phép.", status)
            return await JSONResponse(error.envelope(str(uuid.uuid4())), status_code=status)(
                scope, receive, secured_send
            )

        # Duplicate security headers are ambiguous across HTTP implementations.
        headers = {}
        for key, value in scope["headers"]:
            key = key.lower()
            if key in headers and key in {
                b"host",
                b"origin",
                b"sec-fetch-site",
                b"x-preview-bootstrap",
            }:
                return await reject("PREVIEW_HEADERS_DENIED")
            headers[key] = value
        if headers.get(b"host") != HOST.encode():
            return await reject("HOST_DENIED", 400)
        if b"origin" in headers and headers[b"origin"] != ORIGIN.encode():
            return await reject("ORIGIN_DENIED")
        if scope["method"] == "OPTIONS":
            return await reject("PREFLIGHT_DENIED")

        path = scope["path"]
        if path == "/preview/bootstrap":
            if (
                scope["method"] != "POST"
                or scope.get("query_string")
                or headers.get(b"x-preview-bootstrap") != b"1"
                or headers.get(b"sec-fetch-site", b"same-origin") != b"same-origin"
            ):
                return await reject("PREVIEW_BOOTSTRAP_DENIED")
            return await JSONResponse(
                {
                    "protocol_version": 1,
                    "api_base": f"{ORIGIN}/api/v1",
                    "session_token": self.token,
                    "data_root": "/data",
                    "runtime_state": self.runtime.maintenance.status()["state"],
                }
            )(scope, receive, secured_send)
        if path.startswith("/api/v1/"):
            return await self.api(scope, receive, secured_send)
        if scope["method"] not in {"GET", "HEAD"}:
            return await reject("PREVIEW_ROUTE_NOT_FOUND", 404)
        if path == "/":
            return await FileResponse(self.index, media_type="text/html")(
                scope, receive, secured_send
            )
        if path.startswith("/assets/"):
            asset_scope = dict(scope, path=path[len("/assets") :], root_path="")
            try:
                return await self.assets(asset_scope, receive, secured_send)
            except HTTPException:
                return await reject("PREVIEW_ROUTE_NOT_FOUND", 404)
        return await reject("PREVIEW_ROUTE_NOT_FOUND", 404)


def main() -> None:
    runtime = None
    try:
        runtime = open_preview_runtime(Path("/data"))
        app = BrowserPreview(runtime, Path("/app/frontend/dist"))
        # Container networking needs 0.0.0.0; Compose publishes ONLY host loopback.
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            access_log=False,
            server_header=False,
            proxy_headers=False,
            log_level="critical",
            log_config=None,
        )
    except CoreError as error:
        code = error.code if error.code in STARTUP_CODES else "PREVIEW_STARTUP_FAILED"
        raise SystemExit(f"Cafe Fin preview could not start safely ({code}).") from None
    except BaseException:
        # Never render exception data, paths, payloads or session capabilities.
        raise SystemExit("Cafe Fin preview could not start safely.") from None
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    main()
