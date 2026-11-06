"""Physical candidate identity and receipt-guarded activation, without native policy."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func, select

from .audit import AuditService
from .db import REQUESTS
from .errors import CoreError
from .maintenance import operation_identity
from .storage import MARKER, DataRootService, sha256_file

ACTIVATION_MARKER = ".cafe-fin-activation.json"
OPERATION_MARKER = ".cafe-fin-operation.json"
RECEIPT_ACTOR = "core.maintenance"
INTENT = "maintenance.intent"
PREPARED = "maintenance.prepared"
ACTIVATION_INTENT = "maintenance.activation_intent"
ACTIVATION_COMPLETED = "maintenance.activation_completed"


def canonical_location(path: Path | str) -> Path:
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            raise ValueError()
        return DataRootService(candidate).preflight_location()
    except (OSError, TypeError, ValueError):
        raise CoreError(
            "MAINTENANCE_PATH_INVALID", "Cần vị trí local do desktop chọn.", 409
        ) from None


def location_fingerprint(path: Path | str) -> str:
    spelling = os.path.normcase(str(canonical_location(path)))
    return hashlib.sha256(spelling.encode("utf-8")).hexdigest()


def read_control_json(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            data = stream.read(16385)
        if len(data) > 16384:
            raise ValueError()
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise CoreError(
            "MAINTENANCE_METADATA_INVALID", "Thông tin bảo trì không hợp lệ.", 409
        ) from None


def root_identity(root: DataRootService) -> str:
    value = read_control_json(root.resolve_key(MARKER))
    if value.get("format") != 1:
        raise CoreError("MAINTENANCE_METADATA_INVALID", "Dấu dữ liệu không hợp lệ.", 409)
    return operation_identity(value.get("root_id"))


def receipt(conn, action: str, operation_id: str):
    raw = conn.execute(
        select(REQUESTS.c.result_json).where(
            REQUESTS.c.actor == RECEIPT_ACTOR,
            REQUESTS.c.action == action,
            REQUESTS.c.request_key == operation_id,
        )
    ).scalar_one_or_none()
    return None if raw is None else json.loads(raw)


def authorize_current(runtime, access_token, permission="core.manage"):
    actor = runtime.auth.authenticate(access_token)

    def fence(conn):
        current = runtime.auth.authenticate(access_token)
        if current.id != actor.id:
            raise CoreError("SESSION_EXPIRED", "Phiên đăng nhập không còn hiệu lực.", 401)
        runtime.auth.authorize(conn, actor, permission)

    runtime.writer.run(fence)
    return actor


def write_receipt(runtime, actor, access_token, action, operation_id, payload, result):
    def authorize(conn):
        runtime.auth.authenticate(access_token)
        runtime.auth.authorize(conn, actor, "core.manage")

    def operation(conn):
        AuditService.record(
            conn,
            actor=actor.id,
            entity="core_maintenance",
            entity_id=operation_id,
            action=action,
            after=result,
        )
        return result

    return runtime.writer.execute(
        RECEIPT_ACTOR,
        action,
        operation_id,
        payload,
        operation,
        authorize=authorize,
    )


@dataclass(frozen=True)
class ActivationContext:
    activation_id: str
    kind: str
    origin_generation: str
    source_root_id: str
    candidate_root_id: str
    source_fingerprint: str
    candidate_fingerprint: str
    manifest_sha256: str

    @property
    def operation_id(self) -> str:
        return self.activation_id

    def marker(self) -> dict:
        return {"format": 1, **asdict(self)}


def activation_context(root: DataRootService) -> ActivationContext | None:
    path = root.resolve_key(ACTIVATION_MARKER)
    if not path.exists():
        return None
    value = read_control_json(path)
    try:
        if value.pop("format") != 1:
            raise ValueError()
        context = ActivationContext(**value)
        for name in ("activation_id", "origin_generation", "source_root_id", "candidate_root_id"):
            operation_identity(getattr(context, name))
        for name in ("source_fingerprint", "candidate_fingerprint", "manifest_sha256"):
            digest = getattr(context, name)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise ValueError()
        if context.kind not in ("move", "restore"):
            raise ValueError()
        if context.candidate_fingerprint != location_fingerprint(root.path):
            raise ValueError()
        if context.candidate_root_id != root_identity(root):
            raise ValueError()
        if sha256_file(root.resolve_key("backup-manifest.json")) != context.manifest_sha256:
            raise ValueError()
        provenance = read_control_json(root.resolve_key(OPERATION_MARKER))
        expected_binding = {
            "kind": context.kind,
            "origin_generation": context.origin_generation,
            "source_root_id": context.source_root_id,
            "source_fingerprint": context.source_fingerprint,
            "candidate_fingerprint": context.candidate_fingerprint,
            "backup_manifest_sha256": context.manifest_sha256
            if context.kind == "restore"
            else None,
        }
        if (
            provenance.get("format") != 1
            or provenance.get("operation_id") != context.activation_id
            or provenance.get("binding") != expected_binding
        ):
            raise ValueError()
        return context
    except (OSError, ValueError, TypeError, KeyError):
        raise CoreError(
            "ACTIVATION_BINDING_INVALID", "Candidate không khớp lần bảo trì.", 409
        ) from None


def boot_preflight(root: DataRootService):
    context = activation_context(root)
    if root.resolve_key("backup-manifest.json").exists() and context is None:
        raise CoreError(
            "BACKUP_ARCHIVE_NOT_ACTIVE", "Bản sao lưu phải được khôi phục qua desktop.", 409
        )
    return context


def guarded_boot_mode(root, database, requested_mode, context):
    fingerprint = location_fingerprint(root.path)
    with database.read() as conn:
        if context is not None:
            complete = receipt(conn, ACTIVATION_COMPLETED, context.activation_id)
            if complete is None:
                return "dormant"
            expected = {
                "activation_id": context.activation_id,
                "candidate_fingerprint": fingerprint,
                "context": context.marker(),
            }
            if complete != expected:
                raise CoreError(
                    "ACTIVATION_BINDING_INVALID", "Biên nhận candidate không khớp.", 409
                )
        relocations = conn.execute(
            select(REQUESTS.c.request_key).where(
                REQUESTS.c.actor == RECEIPT_ACTOR,
                REQUESTS.c.action == INTENT,
                func.json_extract(REQUESTS.c.result_json, "$.intent.kind").in_(("move", "restore")),
                func.json_extract(REQUESTS.c.result_json, "$.intent.source_fingerprint")
                == fingerprint,
            )
        ).first()
        if relocations is not None:
            return "dormant"
        pending = conn.execute(
            select(REQUESTS.c.request_key).where(
                REQUESTS.c.actor == RECEIPT_ACTOR,
                REQUESTS.c.action == ACTIVATION_INTENT,
                func.json_extract(REQUESTS.c.result_json, "$.candidate_fingerprint") == fingerprint,
            )
        ).scalars()
        for operation_id in pending:
            if receipt(conn, ACTIVATION_COMPLETED, operation_id) is None:
                return "dormant"
    return requested_mode


def begin_activation(runtime, actor, access_token, operation_id):
    context = activation_context(runtime.root)
    fingerprint = location_fingerprint(runtime.root.path)
    payload = {
        "activation_id": operation_id,
        "candidate_fingerprint": fingerprint,
        "context": context.marker() if context else None,
    }
    with runtime.reader() as conn:
        if context is not None and context.activation_id != operation_id:
            raise CoreError("ACTIVATION_BINDING_INVALID", "Mã kích hoạt không khớp candidate.", 409)
        complete = receipt(conn, ACTIVATION_COMPLETED, operation_id)
        intent = receipt(conn, ACTIVATION_INTENT, operation_id)
        source_pending = conn.execute(
            select(REQUESTS.c.request_key).where(
                REQUESTS.c.actor == RECEIPT_ACTOR,
                REQUESTS.c.action == INTENT,
                func.json_extract(REQUESTS.c.result_json, "$.intent.kind").in_(("move", "restore")),
                func.json_extract(REQUESTS.c.result_json, "$.intent.source_fingerprint")
                == fingerprint,
            )
        ).first()
    if source_pending:
        raise CoreError(
            "MAINTENANCE_REPLAY_REQUIRED", "Nguồn cũ đang chờ đối chiếu chuyển dữ liệu.", 409
        )
    if complete is not None:
        if complete != payload:
            raise CoreError("ACTIVATION_BINDING_INVALID", "Biên nhận kích hoạt không khớp.", 409)
        return context, payload, False
    if intent is not None:
        raise CoreError(
            "ACTIVATION_REPLAY_REQUIRED", "Lần kích hoạt trước cần được đối chiếu.", 409
        )
    if context is not None:
        from .backup import BackupService

        BackupService.verify(runtime.root.path)
        if context.kind == "restore":
            require_restore_guard(runtime)
    write_receipt(runtime, actor, access_token, ACTIVATION_INTENT, operation_id, payload, payload)
    return context, payload, True


def require_restore_guard(runtime):
    reporting = next((m for m in runtime.modules.ordered() if m.id == "reporting"), None)
    if reporting is None or reporting.on_activate is None:
        raise CoreError("RESTORE_GUARD_UNAVAILABLE", "Chưa có bộ chặn gửi sau khôi phục.", 503)


def complete_activation(runtime, actor, access_token, operation_id, payload):
    return write_receipt(
        runtime,
        actor,
        access_token,
        ACTIVATION_COMPLETED,
        operation_id,
        payload,
        payload,
    )
