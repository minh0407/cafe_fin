"""Authenticated private native operations; filesystem paths never enter public HTTP."""

import hashlib
import sqlite3
from contextlib import closing

from .activation import (
    ACTIVATION_COMPLETED,
    ACTIVATION_INTENT,
    ACTIVATION_MARKER,
    INTENT,
    OPERATION_MARKER,
    PREPARED,
    RECEIPT_ACTOR,
    ActivationContext,
    activation_context,
    authorize_current,
    canonical_location,
    location_fingerprint,
    read_control_json,
    receipt,
    require_restore_guard,
    root_identity,
    write_receipt,
)
from .backup import BackupService
from .db import canonical_json
from .errors import CoreError
from .maintenance import operation_identity
from .storage import DataRootService, atomic_json, sha256_file


class MaintenanceOperations:
    """Caller must persist native intent first and serialize all control operations."""

    def __init__(self, runtime, *, generation: str):
        self.runtime = runtime
        self.generation = operation_identity(generation)

    def _get(self, action, operation_id):
        with self.runtime.reader() as conn:
            return receipt(conn, action, operation_id)

    def _source(self):
        source = canonical_location(self.runtime.root.path)
        return source, location_fingerprint(source), root_identity(self.runtime.root)

    def _intent(self, operation_id, origin_generation):
        stored = self._get(INTENT, operation_id)
        if stored is None:
            raise CoreError("MAINTENANCE_OPERATION_NOT_FOUND", "Không tìm thấy lần bảo trì.", 404)
        intent = stored["intent"]
        if intent["origin_generation"] != origin_generation:
            raise CoreError("IDEMPOTENCY_CONFLICT", "Lần bảo trì không khớp phiên gốc.", 409)
        _, fingerprint, root_id = self._source()
        if intent["source_fingerprint"] != fingerprint or intent["source_root_id"] != root_id:
            raise CoreError("MAINTENANCE_SOURCE_CONFLICT", "Nguồn bảo trì không khớp.", 409)
        return intent

    def _locations(self, kind, destination, backup_source):
        source, _, _ = self._source()
        destination = canonical_location(destination)
        if source.is_relative_to(destination) or destination.is_relative_to(source):
            raise CoreError(
                "MAINTENANCE_LOCATION_INVALID", "Đích cần độc lập với dữ liệu đang mở.", 409
            )
        if not destination.parent.is_dir():
            raise CoreError("MAINTENANCE_LOCATION_INVALID", "Thư mục cha không còn sẵn sàng.", 409)
        if kind != "restore" and backup_source is not None:
            raise CoreError(
                "MAINTENANCE_SOURCE_INVALID", "Loại bảo trì không nhận nguồn khôi phục.", 400
            )
        backup = None
        if kind == "restore":
            if backup_source is None:
                raise CoreError(
                    "MAINTENANCE_SOURCE_INVALID", "Thiếu bản sao lưu để khôi phục.", 400
                )
            backup = canonical_location(backup_source)
            if backup.is_relative_to(destination) or destination.is_relative_to(backup):
                raise CoreError("MAINTENANCE_LOCATION_INVALID", "Nguồn và đích phải độc lập.", 409)
            BackupService.verify(backup)
        return destination, backup

    @staticmethod
    def _metadata(intent):
        return {
            "format": 1,
            "operation_id": intent["operation_id"],
            "payload_hash": hashlib.sha256(canonical_json(intent).encode()).hexdigest(),
            "binding": {
                key: intent[key]
                for key in (
                    "kind",
                    "origin_generation",
                    "source_root_id",
                    "source_fingerprint",
                    "candidate_fingerprint",
                    "backup_manifest_sha256",
                )
            },
        }

    def _verify_artifact(self, intent, expected_hash=None):
        destination, backup = self._locations(
            intent["kind"], intent["destination"], intent["backup_source"]
        )
        if not destination.is_dir():
            raise CoreError("MAINTENANCE_REPLAY_REQUIRED", "Candidate chưa được xuất bản.", 409)
        root = DataRootService(destination)
        if read_control_json(root.resolve_key(OPERATION_MARKER)) != self._metadata(intent):
            raise CoreError(
                "MAINTENANCE_ARTIFACT_CONFLICT", "Đích không thuộc lần bảo trì này.", 409
            )
        BackupService.verify(destination)
        manifest_hash = sha256_file(root.resolve_key("backup-manifest.json"))
        if expected_hash is not None and manifest_hash != expected_hash:
            raise CoreError("MAINTENANCE_ARTIFACT_CONFLICT", "Hash candidate đã thay đổi.", 409)
        if expected_hash is not None and intent["kind"] in ("move", "restore"):
            context = activation_context(root)
            if context is None or context.activation_id != intent["operation_id"]:
                raise CoreError(
                    "ACTIVATION_BINDING_INVALID", "Candidate thiếu dấu kích hoạt đúng.", 409
                )
        if intent["kind"] == "restore":
            if sha256_file(backup / "backup-manifest.json") != intent["backup_manifest_sha256"]:
                raise CoreError("MAINTENANCE_SOURCE_CONFLICT", "Bản sao lưu gốc đã thay đổi.", 409)
            if manifest_hash != intent["backup_manifest_sha256"]:
                raise CoreError(
                    "MAINTENANCE_ARTIFACT_CONFLICT", "Candidate không khớp bản sao lưu.", 409
                )
        else:
            # The snapshot must contain the committed intent, not just a loose sidecar.
            try:
                with closing(
                    sqlite3.connect(root.database_path.as_uri() + "?mode=ro", uri=True)
                ) as conn:
                    row = conn.execute(
                        "SELECT payload_hash FROM core_requests WHERE actor=? AND action=? AND request_key=?",
                        (RECEIPT_ACTOR, INTENT, intent["operation_id"]),
                    ).fetchone()
                if row is None or row[0] != self._metadata(intent)["payload_hash"]:
                    raise CoreError(
                        "MAINTENANCE_ARTIFACT_CONFLICT", "Snapshot thiếu ý định bảo trì.", 409
                    )
            except sqlite3.Error:
                raise CoreError(
                    "MAINTENANCE_ARTIFACT_CONFLICT", "Không kiểm chứng được snapshot.", 409
                ) from None
        return root, manifest_hash

    def _prepared(self, intent, root, manifest_hash):
        result = {
            "state": "PREPARED",
            "operation_id": intent["operation_id"],
            "kind": intent["kind"],
            "origin_generation": intent["origin_generation"],
            "source_root_id": intent["source_root_id"],
            "candidate_root_id": root_identity(root),
            "source_fingerprint": intent["source_fingerprint"],
            "candidate_fingerprint": intent["candidate_fingerprint"],
            "manifest_sha256": manifest_hash,
        }
        if intent["kind"] in ("move", "restore"):
            context = ActivationContext(
                activation_id=intent["operation_id"],
                kind=intent["kind"],
                origin_generation=intent["origin_generation"],
                source_root_id=intent["source_root_id"],
                candidate_root_id=result["candidate_root_id"],
                source_fingerprint=intent["source_fingerprint"],
                candidate_fingerprint=intent["candidate_fingerprint"],
                manifest_sha256=manifest_hash,
            )
            marker = root.resolve_key(ACTIVATION_MARKER)
            if marker.exists():
                if activation_context(root) != context:
                    raise CoreError("ACTIVATION_BINDING_INVALID", "Dấu kích hoạt không khớp.", 409)
            else:
                atomic_json(marker, context.marker())
            result["activation_id"] = context.activation_id
        return result

    def prepare(
        self,
        operation_id,
        kind,
        *,
        access_token,
        origin_generation,
        destination,
        backup_source=None,
    ):
        operation_id, origin_generation = (
            operation_identity(operation_id),
            operation_identity(origin_generation),
        )
        if kind not in ("backup", "move", "restore"):
            raise CoreError("MAINTENANCE_KIND_INVALID", "Loại bảo trì không hợp lệ.", 400)
        with self.runtime._lifecycle_lock:
            actor = authorize_current(self.runtime, access_token)
            if kind == "restore":
                require_restore_guard(self.runtime)
            destination, backup = self._locations(kind, destination, backup_source)
            prefix = "CafeFinBackup-" if kind == "backup" else "CafeFinData-"
            if destination.name != prefix + operation_id:
                raise CoreError("MAINTENANCE_LOCATION_INVALID", "Đích không khớp mã bảo trì.", 409)
            source, fingerprint, root_id = self._source()
            intent = {
                "operation_id": operation_id,
                "kind": kind,
                "origin_generation": origin_generation,
                "source": str(source),
                "source_fingerprint": fingerprint,
                "source_root_id": root_id,
                "destination": str(destination),
                "candidate_fingerprint": location_fingerprint(destination),
                "backup_source": str(backup) if backup else None,
                "backup_manifest_sha256": sha256_file(backup / "backup-manifest.json")
                if backup
                else None,
            }
            stored = self._get(INTENT, operation_id)
            if stored is not None and stored["intent"] != intent:
                raise CoreError(
                    "IDEMPOTENCY_CONFLICT", "Khóa bảo trì đã gắn với yêu cầu khác.", 409
                )
            if stored is None and origin_generation != self.generation:
                raise CoreError("MAINTENANCE_GENERATION_CONFLICT", "Phiên gốc không khớp.", 409)
            state = self.runtime.maintenance.status()
            if kind in ("move", "restore") and (
                state["state"] != "QUIESCED" or state["operation_id"] != operation_id
            ):
                raise CoreError("MAINTENANCE_REQUIRED", "Cần quiesce đúng lần bảo trì trước.", 503)
            if kind == "backup" and stored is None and state["state"] != "ACTIVE":
                raise CoreError("MAINTENANCE_REQUIRED", "Dữ liệu chưa hoạt động để sao lưu.", 503)
            if stored is None and destination.exists():
                raise CoreError(
                    "MAINTENANCE_DESTINATION_EXISTS", "Đích đã tồn tại; không ghi đè.", 409
                )
            write_receipt(
                self.runtime, actor, access_token, INTENT, operation_id, intent, {"intent": intent}
            )
            completed = self._get(PREPARED, operation_id)
            if completed is not None:
                self._verify_artifact(intent, completed["manifest_sha256"])
                return completed
            # Revalidate trusted paths immediately before use. Unknown partials remain untouched.
            self._locations(kind, destination, backup)
            if not destination.exists():
                if kind == "restore":
                    if (
                        sha256_file(backup / "backup-manifest.json")
                        != intent["backup_manifest_sha256"]
                    ):
                        raise CoreError(
                            "MAINTENANCE_SOURCE_CONFLICT", "Bản sao lưu gốc đã thay đổi.", 409
                        )
                    BackupService.restore(
                        backup, destination, operation_metadata=self._metadata(intent)
                    )
                else:
                    self.runtime.backups.create(
                        destination, operation_metadata=self._metadata(intent)
                    )
            root, manifest_hash = self._verify_artifact(intent)
            result = self._prepared(intent, root, manifest_hash)
            return write_receipt(
                self.runtime, actor, access_token, PREPARED, operation_id, intent, result
            )

    def status(self, operation_id, *, access_token, origin_generation):
        operation_id, origin_generation = (
            operation_identity(operation_id),
            operation_identity(origin_generation),
        )
        with self.runtime._lifecycle_lock:
            authorize_current(self.runtime, access_token)
            context = activation_context(self.runtime.root)
            if context is not None and context.activation_id == operation_id:
                if context.origin_generation != origin_generation:
                    raise CoreError("IDEMPOTENCY_CONFLICT", "Phiên gốc không khớp candidate.", 409)
                complete = self._get(ACTIVATION_COMPLETED, operation_id)
                started = self._get(ACTIVATION_INTENT, operation_id)
                return {
                    **context.marker(),
                    "operation_id": operation_id,
                    "state": "REPLAY_REQUIRED"
                    if started and not complete
                    else self.runtime.maintenance.status()["state"],
                    "activation_completed": complete is not None,
                }
            intent = self._intent(operation_id, origin_generation)
            complete = self._get(PREPARED, operation_id)
            if complete is None:
                return {
                    "operation_id": operation_id,
                    "kind": intent["kind"],
                    "state": "REPLAY_REQUIRED",
                }
            try:
                self._verify_artifact(intent, complete["manifest_sha256"])
            except CoreError as error:
                return {
                    "operation_id": operation_id,
                    "kind": intent["kind"],
                    "state": "FAILED_HELD",
                    "code": error.code,
                }
            return complete

    def authorize_source_identity(self, access_token):
        """Read the current physical binding before native persists transition intent."""
        with self.runtime._lifecycle_lock:
            authorize_current(self.runtime, access_token)
            _, fingerprint, root_id = self._source()
            return {"root_id": root_id, "source_fingerprint": fingerprint}

    def authorize_open_reports(self, access_token):
        with self.runtime._lifecycle_lock:
            authorize_current(self.runtime, access_token, "reporting.read")
            canonical_location(self.runtime.root.path)
            path = self.runtime.root.resolve_key("reports")
            if not path.is_dir():
                raise CoreError("DATA_ROOT_UNAVAILABLE", "Thư mục báo cáo không còn sẵn sàng.", 409)
            return {"allowed": True, "root_id": self._source()[2]}

    def activate(self, operation_id, *, access_token, origin_generation):
        operation_id, origin_generation = (
            operation_identity(operation_id),
            operation_identity(origin_generation),
        )
        with self.runtime._lifecycle_lock:
            authorize_current(self.runtime, access_token)
            context = activation_context(self.runtime.root)
            if (
                context is None
                or context.activation_id != operation_id
                or context.origin_generation != origin_generation
            ):
                raise CoreError(
                    "ACTIVATION_BINDING_INVALID", "Candidate không khớp lần kích hoạt.", 409
                )
            return self.runtime.activate(operation_id, access_token=access_token)

    def authorize_close(self, operation_id, *, access_token, origin_generation):
        operation_id, origin_generation = (
            operation_identity(operation_id),
            operation_identity(origin_generation),
        )
        with self.runtime._lifecycle_lock:
            authorize_current(self.runtime, access_token)
            context = activation_context(self.runtime.root)
            if context is not None and context.activation_id == operation_id:
                if context.origin_generation != origin_generation:
                    raise CoreError("IDEMPOTENCY_CONFLICT", "Phiên gốc không khớp.", 409)
            else:
                self._intent(operation_id, origin_generation)
            # This is authorization only, never clean process exit or closure proof.
            return {"operation_id": operation_id, "state": "CLOSE_AUTHORIZED"}
