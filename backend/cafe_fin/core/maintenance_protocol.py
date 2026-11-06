"""Bounded private-pipe transport. This module grants no filesystem authority."""

import json
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, BinaryIO, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import CoreError
from .maintenance import operation_identity

MAX_FRAME_BYTES = 262144
MAX_RESPONSE_BYTES = 16384
REPLAY_WINDOW_SIZE = 4096
STATES = frozenset(
    {
        "ACTIVE",
        "QUIESCING",
        "QUIESCED",
        "PREPARING",
        "PREPARED",
        "CLOSING",
        "CLOSED",
        "DORMANT",
        "ACTIVATING",
        "FAILED_HELD",
        "REPLAY_REQUIRED",
    }
)
ERROR_CODES = frozenset(
    "LOGIN_REQUIRED SESSION_EXPIRED PERMISSION_DENIED WRITER_BUSY RUNTIME_CLOSED "
    "MAINTENANCE_REQUIRED MAINTENANCE_CONFLICT MAINTENANCE_DRAIN_TIMEOUT "
    "MAINTENANCE_ACTIVATION_FAILED MAINTENANCE_FAILED MAINTENANCE_CLOSE_FAILED "
    "PERIODIC_SHUTDOWN_TIMEOUT JOB_SHUTDOWN_TIMEOUT MAINTENANCE_OPERATION_NOT_FOUND "
    "MAINTENANCE_SOURCE_CONFLICT MAINTENANCE_LOCATION_INVALID MAINTENANCE_SOURCE_INVALID "
    "MAINTENANCE_ARTIFACT_CONFLICT MAINTENANCE_REPLAY_REQUIRED MAINTENANCE_DESTINATION_EXISTS "
    "MAINTENANCE_GENERATION_CONFLICT MAINTENANCE_REQUEST_REPLAY MAINTENANCE_REQUEST_LIMIT "
    "MAINTENANCE_PROTOCOL_INVALID MAINTENANCE_COMMAND_FAILED MAINTENANCE_RESPONSE_INVALID "
    "MAINTENANCE_PIPE_EOF MAINTENANCE_PIPE_WRITE_FAILED ACTIVATION_BINDING_INVALID "
    "ACTIVATION_REPLAY_REQUIRED RESTORE_GUARD_UNAVAILABLE IDEMPOTENCY_CONFLICT "
    "DATA_ROOT_UNAVAILABLE DATA_ROOT_LOCKED DATA_ROOT_REMOTE FILE_KEY_INVALID "
    "BACKUP_LOCATION_INVALID BACKUP_INVALID BACKUP_EXISTS RESTORE_LOCATION_INVALID "
    "RESTORE_EXISTS DISK_FULL STORAGE_IO SHUTDOWN_FAILED".split()
)


def safe_code(value):
    return (
        value if isinstance(value, str) and value in ERROR_CODES else "MAINTENANCE_COMMAND_FAILED"
    )


def native_path(value: str) -> str:
    if (
        not value
        or len(value) > 32767
        or "\x00" in value
        or len(value.encode("utf-8")) > 98304
        or not Path(value).is_absolute()
    ):
        raise ValueError("Invalid native path")
    return value


class BootRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocol_version: Literal[1]
    session_token: str = Field(
        min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", repr=False
    )
    data_root: str = Field(repr=False)
    initialize: bool = False
    allowed_origin: str
    maintenance_protocol: Literal[1] | None = None
    generation: str | None = None
    activation_mode: Literal["active", "dormant"] = "active"

    _path = field_validator("data_root")(native_path)

    @field_validator("protocol_version", "maintenance_protocol", mode="before")
    @classmethod
    def exact_version(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("Invalid protocol")
        return value

    @model_validator(mode="after")
    def negotiated(self):
        if self.maintenance_protocol is None:
            if self.generation is not None or self.activation_mode != "active":
                raise ValueError("Capability required")
        else:
            operation_identity(self.generation)
        return self


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    maintenance_protocol: Literal[1]
    request_id: str
    generation: str
    access_token: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("maintenance_protocol", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int:
            raise ValueError("Invalid protocol")
        return value

    @field_validator("request_id", "generation")
    @classmethod
    def identity(cls, value):
        return operation_identity(value)


class OperationControl(Control):
    operation_id: str
    origin_generation: str
    _identity = field_validator("operation_id", "origin_generation")(operation_identity)


class Quiesce(OperationControl):
    command: Literal["maintenance.quiesce"]


class Prepare(OperationControl):
    command: Literal["maintenance.prepare"]
    kind: Literal["backup", "move", "restore"]
    destination: str = Field(repr=False)
    backup_source: str | None = Field(default=None, repr=False)
    _destination = field_validator("destination")(native_path)

    @field_validator("backup_source")
    @classmethod
    def source(cls, value):
        return native_path(value) if value is not None else None

    @model_validator(mode="after")
    def restore_only(self):
        if (self.kind == "restore") != (self.backup_source is not None):
            raise ValueError("Restore source required only for restore")
        if self.kind != "restore" and "backup_source" in self.model_fields_set:
            raise ValueError("Unexpected source")
        return self


class Status(OperationControl):
    command: Literal["maintenance.status"]


class Activate(OperationControl):
    command: Literal["maintenance.activate"]


class Close(OperationControl):
    command: Literal["maintenance.close"]


class OpenReports(Control):
    command: Literal["reports.authorize_open"]


class SourceIdentity(Control):
    command: Literal["maintenance.source_identity"]


COMMAND = TypeAdapter(
    Annotated[
        Quiesce | Prepare | Status | Activate | Close | OpenReports | SourceIdentity,
        Field(discriminator="command"),
    ]
)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _invalid_constant(_):
    raise ValueError("Invalid constant")


def read_frame(source: BinaryIO):
    """The same binary reader owns boot and every later frame; never text-read ahead."""
    raw = source.readline(MAX_FRAME_BYTES + 1)
    if not raw:
        return None
    if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
        raise CoreError("MAINTENANCE_PROTOCOL_INVALID", "Khung điều khiển không hợp lệ.", 503)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_invalid_constant
        )
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise CoreError(
            "MAINTENANCE_PROTOCOL_INVALID", "Khung điều khiển không hợp lệ.", 503
        ) from None


class FrameWriter:
    def __init__(self, target: BinaryIO):
        self.target, self._lock = target, threading.Lock()

    def write(self, value):
        try:
            raw = (
                json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n"
            ).encode("utf-8")
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise CoreError(
                "MAINTENANCE_RESPONSE_INVALID", "Không tạo được phản hồi điều khiển.", 503
            ) from None
        with self._lock:
            self.target.write(raw)
            self.target.flush()


class ControlDispatcher:
    def __init__(self, runtime, generation: str, *, operations=None, close: Callable):
        from .maintenance_operations import MaintenanceOperations

        self.runtime, self.generation = runtime, operation_identity(generation)
        self.operations = (
            operations
            if operations is not None
            else MaintenanceOperations(runtime, generation=generation)
        )
        self.close = close
        self.close_attempted = False
        self._seen = OrderedDict()
        self._lock = threading.Lock()

    def _runtime_state(self):
        state = self.runtime.maintenance.status()["state"]
        return state if state in STATES else "FAILED_HELD"

    def response(self, request, *, result=None, code=None):
        runtime_state = self._runtime_state()
        response = {
            "maintenance_protocol": 1,
            "request_id": request.request_id,
            "generation": self.generation,
            "status": "error" if code else "ok",
            "state": runtime_state,
            "runtime_state": runtime_state,
        }
        if isinstance(request, OperationControl):
            response["operation_id"] = request.operation_id
        if code:
            response["code"] = safe_code(code)
            if result and result.get("state") in STATES:
                response["state"] = result["state"]
            if response["state"] == "CLOSED":
                response["state"] = "FAILED_HELD"
            return response
        result = result or {}
        state = result.get("state", runtime_state)
        if state not in STATES:
            raise CoreError(
                "MAINTENANCE_RESPONSE_INVALID", "Trạng thái điều khiển không hợp lệ.", 503
            )
        response["state"] = state
        for key in ("root_id", "source_root_id", "candidate_root_id"):
            if key in result:
                response[key] = operation_identity(result[key])
        for key in ("manifest_sha256", "source_fingerprint", "candidate_fingerprint"):
            if key in result:
                if not isinstance(result[key], str) or not re.fullmatch(
                    r"[a-f0-9]{64}", result[key]
                ):
                    raise CoreError(
                        "MAINTENANCE_RESPONSE_INVALID", "Tham chiếu điều khiển không hợp lệ.", 503
                    )
                response[key] = result[key]
        if "kind" in result:
            if result["kind"] not in ("backup", "move", "restore"):
                raise CoreError(
                    "MAINTENANCE_RESPONSE_INVALID", "Loại điều khiển không hợp lệ.", 503
                )
            response["kind"] = result["kind"]
        if "allowed" in result:
            if type(result["allowed"]) is not bool:
                raise CoreError(
                    "MAINTENANCE_RESPONSE_INVALID", "Quyền điều khiển không hợp lệ.", 503
                )
            response["allowed"] = result["allowed"]
        return response

    def execute(self, request):
        with self._lock:
            self.close_attempted = False
            try:
                if request.generation != self.generation:
                    raise CoreError(
                        "MAINTENANCE_GENERATION_CONFLICT", "Phiên backend đã thay đổi.", 409
                    )
                if request.request_id in self._seen:
                    raise CoreError("MAINTENANCE_REQUEST_REPLAY", "Mã yêu cầu đã được dùng.", 409)
                self._seen[request.request_id] = None
                if len(self._seen) > REPLAY_WINDOW_SIZE:
                    self._seen.popitem(last=False)
                if isinstance(request, OpenReports):
                    result = self.operations.authorize_open_reports(request.access_token)
                elif isinstance(request, SourceIdentity):
                    result = self.operations.authorize_source_identity(request.access_token)
                elif isinstance(request, Quiesce):
                    result = self.runtime.quiesce(
                        request.operation_id, access_token=request.access_token
                    )
                elif isinstance(request, Prepare):
                    result = self.operations.prepare(
                        request.operation_id,
                        request.kind,
                        access_token=request.access_token,
                        origin_generation=request.origin_generation,
                        destination=request.destination,
                        backup_source=request.backup_source,
                    )
                else:
                    args = dict(
                        access_token=request.access_token,
                        origin_generation=request.origin_generation,
                    )
                    if isinstance(request, Close):
                        self.operations.authorize_close(request.operation_id, **args)
                        self.close_attempted = True
                        self.close()
                        if self._runtime_state() != "CLOSED":
                            raise CoreError("SHUTDOWN_FAILED", "Backend chưa đóng hoàn toàn.", 503)
                        result = {"state": "CLOSED"}
                    else:
                        method = (
                            self.operations.status
                            if isinstance(request, Status)
                            else self.operations.activate
                        )
                        result = method(request.operation_id, **args)
                if result.get("code"):
                    return self.response(request, result=result, code=result["code"])
                return self.response(request, result=result)
            except CoreError as error:
                return self.response(request, code=error.code)
            except BaseException:
                return self.response(request, code="MAINTENANCE_COMMAND_FAILED")


def parse_command(value):
    try:
        return COMMAND.validate_python(value)
    except (ValidationError, CoreError, ValueError, TypeError):
        raise CoreError(
            "MAINTENANCE_PROTOCOL_INVALID", "Lệnh điều khiển không hợp lệ.", 503
        ) from None
