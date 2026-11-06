"""Authenticated loopback API. No absolute filesystem-path parameters are public."""

import hashlib
import io
import json
import re
import secrets
import sqlite3
import uuid
from contextlib import ExitStack, asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from .auth import Principal
from .db import REQUESTS
from .errors import CoreError
from .http_types import (
    AuthDTO,
    DataRootDTO,
    DocumentExportsDTO,
    ErrorEnvelopeDTO,
    GridPageDTO,
    HealthDTO,
    JobDTO,
    JobSubmittedDTO,
    LogoutDTO,
    UserDetailDTO,
    UserDTO,
)
from .renderers import DocumentRenderer, DocumentSnapshot, synthetic_snapshot
from .runtime import Runtime

PROTOCOL_VERSION = 1
ALLOWED_ORIGINS = frozenset(
    {"http://tauri.localhost", "https://tauri.localhost", "http://127.0.0.1:1420"}
)
MAX_BODY = 2 * 1024 * 1024


class VerifiedFileResponse(StreamingResponse):
    """Close even if the client disconnects before iteration/response-start succeeds."""

    def __init__(self, content, *, resources: ExitStack, **kwargs):
        super().__init__(content, **kwargs)
        self.resources = resources

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.resources.close()


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Login(Payload):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=128, repr=False)


class CreateUser(Login):
    role: str
    request_key: str = Field(min_length=1, max_length=128)


class UpdateUser(Payload):
    role: str
    active: bool
    expected_version: int = Field(ge=1)
    request_key: str = Field(min_length=1, max_length=128)


class Command(Payload):
    request_key: str = Field(min_length=1, max_length=128)


class SubmitJob(Command):
    kind: str
    payload: dict = Field(default_factory=dict)


class ScopeGuard:
    def __init__(self, app, *, runtime: Runtime, session_token: str, port: int, origin: str):
        self.app, self.runtime, self.token, self.port, self.origin = (
            app,
            runtime,
            session_token,
            port,
            origin,
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {
            key.decode("latin1").lower(): value.decode("latin1") for key, value in scope["headers"]
        }
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        request_origin = headers.get("origin")

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ]
                if request_origin == self.origin:
                    extra += [
                        (b"access-control-allow-origin", self.origin.encode()),
                        (b"access-control-expose-headers", b"X-Request-ID,X-Content-SHA256"),
                        (b"vary", b"Origin"),
                    ]
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        async def reject(error):
            await JSONResponse(error.envelope(request_id), status_code=error.status)(
                scope, receive, wrapped_send
            )

        if headers.get("host") != f"127.0.0.1:{self.port}":
            return await reject(CoreError("HOST_DENIED", "Host không được phép.", 400))
        if request_origin is not None and request_origin != self.origin:
            return await reject(CoreError("ORIGIN_DENIED", "Origin không được phép.", 403))
        if scope["method"] == "OPTIONS":
            allowed_headers = {"content-type", "authorization", "x-app-session"}
            wanted = {
                item.strip().lower()
                for item in headers.get("access-control-request-headers", "").split(",")
                if item.strip()
            }
            if request_origin != self.origin or not wanted.issubset(allowed_headers):
                return await reject(
                    CoreError("PREFLIGHT_DENIED", "Yêu cầu origin không hợp lệ.", 403)
                )
            response = JSONResponse(
                {},
                headers={
                    "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,PUT",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-App-Session",
                },
            )
            return await response(scope, receive, wrapped_send)
        supplied = headers.get("x-app-session", "")
        if not secrets.compare_digest(supplied.encode(), self.token.encode()):
            return await reject(
                CoreError("APP_SESSION_REQUIRED", "Phiên ứng dụng không hợp lệ.", 401)
            )
        public = {"/api/v1/health", "/api/v1/auth/setup", "/api/v1/auth/login"}
        if scope["path"] not in public:
            bearer = headers.get("authorization", "")
            try:
                principal = self.runtime.auth.authenticate(
                    bearer[7:] if bearer.startswith("Bearer ") else None
                )
                scope["state"]["principal"] = principal
            except CoreError as exc:
                return await reject(exc)
        # Buffer only a bounded HTTP command body before any domain handler may mutate.
        body = bytearray()
        if scope["method"] in {"POST", "PATCH", "PUT", "DELETE"}:
            try:
                if int(headers.get("content-length", "0")) > MAX_BODY:
                    return await reject(CoreError("PAYLOAD_TOO_LARGE", "Yêu cầu quá lớn.", 413))
            except ValueError:
                return await reject(
                    CoreError("INVALID_LENGTH", "Độ dài yêu cầu không hợp lệ.", 400)
                )
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_BODY:
                    return await reject(CoreError("PAYLOAD_TOO_LARGE", "Yêu cầu quá lớn.", 413))
                if not message.get("more_body", False):
                    break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered and scope["method"] in {"POST", "PATCH", "PUT", "DELETE"}:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, wrapped_send)


def require(request: Request, permission: str) -> Principal:
    principal = request.state.principal
    principal.require(permission)
    return principal


def create_app(
    runtime: Runtime, session_token: str, *, port: int, origin: str = "http://tauri.localhost"
) -> FastAPI:
    if origin not in ALLOWED_ORIGINS or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", session_token):
        raise CoreError("BOOT_PROTOCOL_INVALID", "Cấu hình phiên khởi động không hợp lệ.", 503)

    @asynccontextmanager
    async def lifespan(app):
        runtime.start()
        try:
            yield
        finally:
            runtime.close()

    app = FastAPI(
        title="Cafe Fin local API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        responses={
            code: {"model": ErrorEnvelopeDTO}
            for code in (400, 401, 403, 404, 409, 413, 422, 429, 500, 503)
        },
    )
    app.state.runtime = runtime
    app.add_middleware(
        ScopeGuard, runtime=runtime, session_token=session_token, port=port, origin=origin
    )

    @app.exception_handler(CoreError)
    async def core_error(request, exc):
        return JSONResponse(exc.envelope(request.state.request_id), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "code": "INVALID_FIELD",
                "message": "Giá trị không hợp lệ.",
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            CoreError(
                "VALIDATION_ERROR", "Kiểm tra lại các trường nhập.", 422, field_errors=fields
            ).envelope(request.state.request_id),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        code, status, message = "INTERNAL_ERROR", 500, "Không thể hoàn tất thao tác. Hãy thử lại."
        if isinstance(exc, IntegrityError):
            code, status, message = "DATA_CONFLICT", 409, "Dữ liệu xung đột với bản ghi hiện có."
        elif isinstance(exc, (OperationalError, sqlite3.Error, OSError)):
            code, status, message = "STORAGE_UNAVAILABLE", 503, "Không truy cập được dữ liệu local."
        runtime.logger.warning("%s request_id=%s", code, request.state.request_id)
        return JSONResponse(
            CoreError(code, message, status).envelope(request.state.request_id), status_code=status
        )

    @app.get("/api/v1/health", response_model=HealthDTO)
    def health():
        if runtime.runner.error_code or (runtime._started and not runtime.runner.thread.is_alive()):
            raise CoreError(
                "JOB_RUNNER_UNAVAILABLE", "Bộ xử lý tác vụ local đang cần phục hồi.", 503
            )
        with runtime.database.read() as conn:
            conn.exec_driver_sql("SELECT 1").scalar_one()
        return {
            "status": "ok",
            "protocol_version": PROTOCOL_VERSION,
            "setup_required": runtime.auth.setup_required(),
        }

    @app.post("/api/v1/auth/setup", response_model=AuthDTO)
    def setup(payload: Login):
        return runtime.auth.setup(payload.username, payload.password)

    @app.post("/api/v1/auth/login", response_model=AuthDTO)
    def login(payload: Login):
        return runtime.auth.login(payload.username, payload.password)

    @app.post("/api/v1/auth/logout", response_model=LogoutDTO)
    def logout(request: Request):
        runtime.auth.logout(request.headers["authorization"][7:])
        return {"logged_out": True}

    @app.get("/api/v1/auth/me", response_model=UserDTO)
    def me(request: Request):
        return request.state.principal.public()

    @app.post("/api/v1/users", response_model=UserDetailDTO)
    def create_user(request: Request, payload: CreateUser):
        return runtime.auth.create_user(require(request, "core.manage"), **payload.model_dump())

    @app.patch("/api/v1/users/{user_id}", response_model=UserDetailDTO)
    def update_user(user_id: str, request: Request, payload: UpdateUser):
        return runtime.auth.update_user(
            require(request, "core.manage"), user_id, **payload.model_dump()
        )

    @app.get("/api/v1/settings/data-root", response_model=DataRootDTO)
    def data_root(request: Request):
        require(request, "core.manage")
        marker = json.loads(
            runtime.root.resolve_key(".cafe-fin-root.json").read_text(encoding="utf-8")
        )
        return {"root_id": marker["root_id"], "format": 1, "available": True}

    @app.get("/api/v1/jobs/{job_id}", response_model=JobDTO)
    def job_status(job_id: str, request: Request):
        actor = require(request, "jobs.read")
        result = runtime.jobs.status(job_id)
        if result["kind"] != "foundation.sample":
            actor.require(f"{result['kind'].split('.', 1)[0]}.read")
        return result

    def require_core_demo_job(kind: str):
        # Module commands own validation, confirmation snapshots and permission scope.
        # Exposing arbitrary registered payloads here would bypass those contracts.
        if kind != "foundation.sample":
            if kind not in runtime.jobs.handlers:
                raise CoreError("UNKNOWN_JOB", "Tác vụ chưa được đăng ký.")
            raise CoreError(
                "MODULE_JOB_ENDPOINT_REQUIRED",
                "Thực hiện tác vụ từ màn hình module đã tạo tác vụ.",
                403,
            )

    @app.post("/api/v1/jobs", response_model=JobSubmittedDTO)
    def submit_job(request: Request, payload: SubmitJob):
        actor = require(request, "jobs.write")
        require_core_demo_job(payload.kind)
        return runtime.jobs.submit(
            actor.id,
            payload.kind,
            payload.payload,
            payload.request_key,
            authorize=lambda conn: runtime.auth.authorize(conn, actor, "jobs.write"),
        )

    @app.post("/api/v1/jobs/{job_id}/cancel", response_model=JobDTO)
    def cancel_job(job_id: str, request: Request):
        actor = require(request, "jobs.write")
        require_core_demo_job(runtime.jobs.status(job_id)["kind"])
        return runtime.jobs.cancel(
            job_id, authorize=lambda conn: runtime.auth.authorize(conn, actor, "jobs.write")
        )

    @app.post("/api/v1/jobs/{job_id}/resume", response_model=JobDTO)
    def resume_job(job_id: str, request: Request):
        actor = require(request, "jobs.write")
        require_core_demo_job(runtime.jobs.status(job_id)["kind"])
        return runtime.jobs.resume(
            job_id, authorize=lambda conn: runtime.auth.authorize(conn, actor, "jobs.write")
        )

    @app.get("/api/v1/spikes/grid", response_model=GridPageDTO)
    def grid(
        request: Request, page: int = Query(1, ge=1), page_size: int = Query(500, ge=1, le=500)
    ):
        actor = require(request, "spikes.use")
        return runtime.workbook_spike.page(
            actor=actor.id,
            page=page,
            page_size=page_size,
            authorize=lambda conn: runtime.auth.authorize(conn, actor, "spikes.use"),
        )

    @app.post("/api/v1/spikes/documents", response_model=DocumentExportsDTO)
    def documents(request: Request, payload: Command):
        actor = require(request, "spikes.use")
        # Rendering stays outside writer. Serialize sample export requests and consult the
        # durable receipt first, because ZIP/PDF timestamps may differ on a fresh render.
        with runtime.render_lock:
            with runtime.database.read() as conn:
                prior = conn.execute(
                    select(REQUESTS.c.result_json).where(
                        REQUESTS.c.actor == actor.id,
                        REQUESTS.c.action == "spikes.documents",
                        REQUESTS.c.request_key == payload.request_key,
                    )
                ).scalar_one_or_none()
            if prior is not None:
                return runtime.writer.execute(
                    actor.id,
                    "spikes.documents",
                    payload.request_key,
                    {},
                    lambda conn: json.loads(prior),
                    authorize=lambda conn: runtime.auth.authorize(conn, actor, "spikes.use"),
                )
            # Persist the immutable render input before either format can commit.
            prepared = runtime.writer.execute(
                actor.id,
                "spikes.documents.prepare",
                payload.request_key,
                {},
                lambda conn: {
                    "snapshot_json": synthetic_snapshot().canonical_bytes().decode("utf-8")
                },
                authorize=lambda conn: runtime.auth.authorize(conn, actor, "spikes.use"),
            )
            raw = json.loads(prepared["snapshot_json"])
            snapshot = DocumentSnapshot(
                title=raw["title"],
                subtitle=raw["subtitle"],
                fields=tuple(tuple(pair) for pair in raw["fields"]),
                paragraphs=tuple(raw["paragraphs"]),
                column_headers=tuple(raw["column_headers"]),
                rows=tuple(tuple(row) for row in raw["rows"]),
            )
            result = render_documents(actor, payload.request_key, snapshot)
            if result["errors"]:
                # Successful formats already have durable individual receipts. A retry
                # recovers those and retries only failures, preserving the first snapshot.
                return result
            return runtime.writer.execute(
                actor.id,
                "spikes.documents",
                payload.request_key,
                {},
                lambda conn: result,
                authorize=lambda conn: runtime.auth.authorize(conn, actor, "spikes.use"),
            )

    def render_documents(actor: Principal, request_key: str, snapshot: DocumentSnapshot):
        outputs, errors = [], []
        for format in ("docx", "pdf"):
            try:
                format_key = hashlib.sha256(f"{request_key}:{format}".encode()).hexdigest()
                with runtime.database.read() as conn:
                    receipt = conn.execute(
                        select(REQUESTS.c.result_json).where(
                            REQUESTS.c.actor == actor.id,
                            REQUESTS.c.action == "files.put",
                            REQUESTS.c.request_key == format_key,
                        )
                    ).scalar_one_or_none()
                if receipt is not None:
                    record = json.loads(receipt)
                    stored = runtime.files.get(record["id"])
                    if (
                        stored.sha256 != record["sha256"]
                        or stored.original_name != f"foundation-sample.{format}"
                    ):
                        raise CoreError(
                            "EXPORT_RECEIPT_CONFLICT", "Output không khớp lượt xuất đã lưu.", 409
                        )
                    with runtime.files.read(stored.id):
                        pass
                else:
                    output = getattr(DocumentRenderer(), format)(snapshot)
                    stored = runtime.files.put(
                        io.BytesIO(output.content),
                        category="documents",
                        original_name=f"foundation-sample.{format}",
                        media_type={
                            "pdf": "application/pdf",
                            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        }[format],
                        actor=actor.id,
                        request_key=format_key,
                        authorize=lambda conn: runtime.auth.authorize(conn, actor, "spikes.use"),
                    )
                outputs.append(
                    {
                        "format": format,
                        "file_id": stored.id,
                        "sha256": stored.sha256,
                        "size": stored.size,
                    }
                )
            except CoreError as exc:
                errors.append({"format": format, "code": exc.code, "message": exc.message})
            except Exception:
                errors.append(
                    {
                        "format": format,
                        "code": "RENDER_FAILED",
                        "message": "Không xuất được định dạng này.",
                    }
                )
        return {"snapshot_sha256": snapshot.sha256, "documents": outputs, "errors": errors}

    @app.get(
        "/api/v1/files/{file_id}/content",
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
                }
            }
        },
    )
    def file_content(file_id: str, request: Request):
        require(request, "files.read")
        stored = runtime.files.get(file_id)
        resources = ExitStack()
        try:
            # Opening and hash verification must finish before HTTP response-start.
            source = resources.enter_context(runtime.files.read(file_id))
        except BaseException:
            resources.close()
            raise

        def stream():
            try:
                while chunk := source.read(64 * 1024):
                    yield chunk
            finally:
                resources.close()

        return VerifiedFileResponse(
            stream(),
            resources=resources,
            media_type=stored.media_type,
            headers={"Content-Disposition": "attachment", "X-Content-SHA256": stored.sha256},
        )

    def module_guard(module_id: str):
        def permission(request: Request):
            suffix = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
            require(request, f"{module_id}.{suffix}")

        return permission

    for module in runtime.modules.ordered():
        if module.router:
            app.include_router(
                module.router,
                prefix=f"/api/v1{module.api_prefix}",
                dependencies=[Depends(module_guard(module.id))],
            )
    original_openapi = app.openapi

    def authenticated_schema():
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {}).update(
            {
                "AppSession": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-App-Session",
                    "description": "Opaque sidecar session, exchanged only by native IPC.",
                },
                "LocalUser": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "opaque",
                    "description": "Memory-only local login token; no OAuth.",
                },
            }
        )
        public = {"/api/v1/health", "/api/v1/auth/setup", "/api/v1/auth/login"}
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method.lower() in {"get", "post", "patch", "put", "delete", "head", "options"}:
                    operation["security"] = (
                        [{"AppSession": []}]
                        if path in public
                        else [{"AppSession": [], "LocalUser": []}]
                    )
        return schema

    app.openapi = authenticated_schema
    return app
