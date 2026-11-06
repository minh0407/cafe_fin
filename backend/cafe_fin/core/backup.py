"""Verified SQLite snapshot backups. Restores and moves always keep the old root."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .errors import CoreError
from .storage import FILES, LAYOUT, MARKER, DataRootService, _io_error, atomic_json, sha256_file


def _safe_join(root: Path, key: str) -> Path:
    # Reuse exactly the same containment policy as the live store.
    return DataRootService(root).resolve_key(key)


def _check_database(path: Path) -> list[dict]:
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CoreError(
                    "BACKUP_DATABASE_INVALID",
                    "DB sao lưu không vượt kiểm tra toàn vẹn.",
                    status=409,
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise CoreError(
                    "BACKUP_DATABASE_INVALID", "DB sao lưu có tham chiếu không hợp lệ.", status=409
                )
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(f"SELECT * FROM {FILES.name}")]
    except sqlite3.Error:
        raise CoreError(
            "BACKUP_DATABASE_INVALID", "Không đọc được DB sao lưu.", status=409
        ) from None


class BackupService:
    def __init__(self, root: DataRootService, database, writer):
        self.root, self.database, self.writer = root, database, writer

    def create(self, trusted_native_destination: Path) -> dict:
        return self._create(trusted_native_destination, inside_barrier=False)

    def _create(self, trusted_native_destination: Path, *, inside_barrier: bool) -> dict:
        destination = Path(trusted_native_destination).absolute()
        if destination.exists():
            raise CoreError(
                "BACKUP_EXISTS", "Thư mục sao lưu đã tồn tại. Chọn thư mục mới.", status=409
            )
        if destination == self.root.path or self.root.path.is_relative_to(destination):
            raise CoreError("BACKUP_LOCATION_INVALID", "Vị trí sao lưu không hợp lệ.")
        partial = destination.with_name(destination.name + ".partial-" + uuid.uuid4().hex)

        def snapshot(_conn):
            try:
                partial.mkdir(parents=True, exist_ok=False)
                for part in LAYOUT:
                    (partial / part).mkdir()
                db_target = partial / "database" / "cafe_fin.db"
                self.database.backup_to(db_target)
                references = _check_database(db_target)
                shutil.copyfile(self.root.path / MARKER, partial / MARKER)
                entries = []
                for key in [
                    MARKER,
                    "database/cafe_fin.db",
                    *(row["relative_key"] for row in references),
                ]:
                    target = _safe_join(partial, key)
                    if key not in (MARKER, "database/cafe_fin.db"):
                        source = self.root.resolve_key(key)
                        if not source.is_file():
                            raise CoreError(
                                "BACKUP_FILE_MISSING",
                                "Tệp dữ liệu đang bị thiếu; chưa thể hoàn tất sao lưu.",
                                status=409,
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                    with target.open("r+b") as stream:
                        os.fsync(stream.fileno())
                    entries.append(
                        {"key": key, "size": target.stat().st_size, "sha256": sha256_file(target)}
                    )
                manifest = {
                    "format": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "files": entries,
                    "referenced_file_count": len(references),
                }
                atomic_json(partial / "backup-manifest.json", manifest)
                self.verify(partial)
                os.rename(partial, destination)
                return {
                    "status": "VERIFIED",
                    "file_count": len(entries),
                    "manifest_sha256": sha256_file(destination / "backup-manifest.json"),
                }
            except OSError as exc:
                # Leave only this operation's partial directory for diagnosis/recovery.
                raise _io_error(exc) from None

        # SQLite's backup API yields a consistent DB snapshot while ordinary writers
        # continue. Referenced content is immutable and core has no file-deletion API,
        # so copying/hashing it needs no writer slot. Move calls this while holding its
        # explicit maintenance barrier to prepare a single quiescent cutoff.
        return snapshot(None)

    @staticmethod
    def verify(backup: Path) -> dict:
        backup = Path(backup).absolute()
        try:
            manifest = json.loads((backup / "backup-manifest.json").read_text(encoding="utf-8"))
            if manifest.get("format") != 1 or not isinstance(manifest.get("files"), list):
                raise ValueError("invalid backup format")
            entries = {}
            for entry in manifest["files"]:
                key = entry["key"]
                if key in entries:
                    raise ValueError("duplicate file key")
                path = _safe_join(backup, key)
                if (
                    not path.is_file()
                    or path.stat().st_size != entry["size"]
                    or sha256_file(path) != entry["sha256"]
                ):
                    raise CoreError(
                        "BACKUP_HASH_MISMATCH",
                        "Tệp trong bản sao lưu thiếu hoặc sai hash.",
                        status=409,
                    )
                entries[key] = entry
            if MARKER not in entries or "database/cafe_fin.db" not in entries:
                raise ValueError("missing required files")
            references = _check_database(backup / "database" / "cafe_fin.db")
            for row in references:
                entry = entries.get(row["relative_key"])
                if (
                    entry is None
                    or entry["sha256"] != row["sha256"]
                    or entry["size"] != row["size"]
                ):
                    raise CoreError(
                        "BACKUP_REFERENCE_INVALID",
                        "Manifest không khớp các tệp được DB tham chiếu.",
                        status=409,
                    )
            if len(references) != manifest["referenced_file_count"]:
                raise ValueError("reference count mismatch")
            DataRootService(backup).open_existing(writable=False)
            return manifest
        except CoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            raise CoreError(
                "BACKUP_INVALID", "Bản sao lưu không có manifest hợp lệ.", status=409
            ) from None

    @classmethod
    def restore(cls, backup: Path, trusted_native_destination: Path) -> DataRootService:
        backup, destination = Path(backup).absolute(), Path(trusted_native_destination).absolute()
        if destination.exists():
            raise CoreError(
                "RESTORE_DESTINATION_EXISTS", "Khôi phục cần thư mục mới chưa tồn tại.", status=409
            )
        if (
            backup == destination
            or backup.is_relative_to(destination)
            or destination.is_relative_to(backup)
        ):
            raise CoreError("RESTORE_LOCATION_INVALID", "Không khôi phục bên trong bản sao lưu.")
        manifest = cls.verify(backup)
        partial = destination.with_name(destination.name + ".restore-" + uuid.uuid4().hex)
        try:
            partial.mkdir(parents=True, exist_ok=False)
            for part in LAYOUT:
                (partial / part).mkdir()
            for entry in manifest["files"]:
                source, target = _safe_join(backup, entry["key"]), _safe_join(partial, entry["key"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                with target.open("r+b") as stream:
                    os.fsync(stream.fileno())
            atomic_json(partial / "backup-manifest.json", manifest)
            cls.verify(partial)
            os.rename(partial, destination)
            return DataRootService(destination).open_existing()
        except OSError as exc:
            raise _io_error(exc) from None

    def move(self, trusted_native_destination: Path) -> DataRootService:
        """Prepare a verified replacement; caller switches native config after shutdown.

        The existing root is retained. No module may update its absolute root while
        readers/writers still use it. Callers close the app's services then relaunch.
        """
        destination = Path(trusted_native_destination).absolute()
        if destination.exists():
            raise CoreError(
                "MOVE_DESTINATION_EXISTS",
                "Chuyển dữ liệu cần thư mục mới chưa tồn tại.",
                status=409,
            )
        if destination.is_relative_to(self.root.path) or self.root.path.is_relative_to(destination):
            raise CoreError(
                "MOVE_LOCATION_INVALID", "Thư mục mới phải độc lập với thư mục dữ liệu cũ."
            )
        # Serialize snapshot, verification and copy with all mutations so the move
        # candidate represents one cutoff. Source remains the only active root.
        snapshot = self.root.path / "backups" / ("move-" + uuid.uuid4().hex)

        def prepare(_conn):
            self._create(snapshot, inside_barrier=True)
            return self.restore(snapshot, destination)

        return self.writer.barrier(prepare)
