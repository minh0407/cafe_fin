"""In-process HTTP admission and terminal maintenance state; no filesystem authority."""

import threading
import time
from contextlib import contextmanager
from uuid import UUID

from .errors import CoreError

SAFE_PATHS = frozenset({"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/logout"})


def operation_identity(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value) != 36 or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise CoreError("INVALID_MAINTENANCE_OPERATION", "Mã bảo trì không hợp lệ.", 400) from None
    return value


def drain_timeout(value) -> float:
    if type(value) not in (int, float) or not 1 <= value <= 300:
        raise CoreError(
            "INVALID_MAINTENANCE_TIMEOUT", "Thời hạn bảo trì cần từ 1 đến 300 giây.", 400
        )
    return float(value)


class AdmissionGate:
    def __init__(self, activation_mode: str):
        if activation_mode not in ("active", "dormant"):
            raise CoreError("INVALID_ACTIVATION_MODE", "Chế độ khởi động không hợp lệ.", 400)
        self._condition = threading.Condition()
        self._state = "DORMANT" if activation_mode == "dormant" else "ACTIVE"
        self._operation_id = None
        self._requests = self._business = 0
        self._closing = False
        self._error_code = None

    def status(self) -> dict:
        with self._condition:
            return {
                "state": self._state,
                "operation_id": self._operation_id,
                "requests": self._requests,
                "business_requests": self._business,
                "error_code": self._error_code,
            }

    @contextmanager
    def admit(self, path: str):
        business = path not in SAFE_PATHS
        with self._condition:
            if self._closing or self._state == "CLOSED":
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            if business and self._state != "ACTIVE":
                raise CoreError("MAINTENANCE_REQUIRED", "Dữ liệu đang ở chế độ bảo trì.", 503)
            self._requests += 1
            self._business += business
        try:
            yield
        finally:
            with self._condition:
                self._requests -= 1
                self._business -= business
                self._condition.notify_all()

    def begin_activation(self, operation_id: str) -> bool:
        with self._condition:
            if self._closing:
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            if self._state == "ACTIVE" and self._operation_id == operation_id:
                return False
            if self._state != "DORMANT" or self._operation_id is not None:
                raise CoreError("MAINTENANCE_CONFLICT", "Trạng thái bảo trì không phù hợp.", 409)
            self._operation_id, self._state = operation_id, "ACTIVATING"
            return True

    def activated(self):
        with self._condition:
            self._state, self._error_code = "ACTIVE", None

    def hold(self, operation_id: str):
        with self._condition:
            if self._closing:
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            if self._state != "ACTIVE" and self._operation_id not in (None, operation_id):
                raise CoreError(
                    "MAINTENANCE_CONFLICT", "Mã bảo trì không khớp phiên hiện tại.", 409
                )
            self._operation_id, self._state = operation_id, "QUIESCING"

    def quiesced(self):
        with self._condition:
            self._state, self._error_code = "QUIESCED", None

    def failed(self, code: str):
        with self._condition:
            self._state, self._error_code = "FAILED_HELD", code

    def begin_close(self):
        with self._condition:
            self._closing, self._state = True, "CLOSING"

    def closed(self):
        with self._condition:
            self._closing, self._state, self._error_code = True, "CLOSED", None

    def wait_for_drain(self, deadline: float, *, include_safe: bool):
        with self._condition:
            while self._requests if include_safe else self._business:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CoreError(
                        "MAINTENANCE_DRAIN_TIMEOUT", "Yêu cầu đang chạy chưa hoàn tất.", 503
                    )
                self._condition.wait(remaining)
