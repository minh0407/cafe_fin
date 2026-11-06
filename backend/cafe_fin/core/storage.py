"""Local, contained, immutable file storage. No workbook content is executed here."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterator

from sqlalchemy import BigInteger, Column, MetaData, String, Table, select
from sqlalchemy.engine import Connection

from .audit import AuditService
from .auth import Principal
from .db import AUDIT
from .errors import CoreError
from .modules import Migration, schema_checksum

LAYOUT = ("database", "documents", "workbooks", "imports", "reports", "backups", "logs")
MARKER = ".cafe-fin-root.json"
FILES = Table(
    "core_files",
    MetaData(),
    Column("id", String, primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("relative_key", String, nullable=False, unique=True),
    Column("category", String, nullable=False),
    Column("original_name", String, nullable=False),
    Column("media_type", String, nullable=False),
    Column("created_at", String, nullable=False),
)


def _migrate(conn):
    FILES.create(conn)


MIGRATIONS = (
    Migration(
        "core_files",
        1,
        "immutable file metadata",
        _migrate,
        checksum=schema_checksum(FILES.metadata),
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _io_error(exc: OSError) -> CoreError:
    code = "DISK_FULL" if exc.errno == 28 or getattr(exc, "winerror", None) == 112 else "STORAGE_IO"
    return CoreError(code, "Không thể ghi tệp. Kiểm tra dung lượng và quyền truy cập.", status=409)


def atomic_json(path: Path, value: dict) -> None:
    """Persist a small manifest; never expose a half-written JSON file."""
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise _io_error(exc) from None
    finally:
        temporary.unlink(missing_ok=True)


class DataRootService:
    """Created only by trusted native selection, never from a public file-path API."""

    def __init__(self, path: Path | str):
        self.path = Path(path).absolute()
        self._lock = None

    def preflight_location(self) -> Path:
        """Validate a trusted native local location, including nonexistent leaf paths."""
        self._validate_local()
        return self.path.resolve()

    def _validate_local(self) -> None:
        candidate = self.path.resolve()
        if str(candidate).startswith(("\\\\", "//")):
            raise CoreError("DATA_ROOT_REMOTE", "Chọn thư mục trên ổ đĩa local.")
        if os.name == "nt":
            drive = candidate.anchor
            if ctypes.windll.kernel32.GetDriveTypeW(str(drive)) not in (2, 3):
                raise CoreError("DATA_ROOT_UNAVAILABLE", "Ổ đĩa local chưa sẵn sàng.", status=409)
        for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            cloud = os.environ.get(key)
            if cloud and candidate.is_relative_to(Path(cloud).resolve()):
                raise CoreError(
                    "DATA_ROOT_SYNCED", "Không đặt DB đang chạy trong thư mục đồng bộ cloud."
                )
        # Reparse points can redirect a previously verified local root or its parents.
        for component in (self.path, *self.path.parents):
            if component.exists() and (
                component.is_symlink()
                or (hasattr(component, "is_junction") and component.is_junction())
            ):
                raise CoreError(
                    "DATA_ROOT_LINK", "Không dùng đường dẫn liên kết cho thư mục dữ liệu."
                )

    def check_writable(self, required_bytes: int = 256 * 1024 * 1024) -> None:
        if required_bytes < 0:
            raise ValueError("required_bytes must be nonnegative")
        if not self.path.is_dir():
            raise CoreError(
                "DATA_ROOT_UNAVAILABLE", "Thư mục dữ liệu không còn sẵn sàng.", status=409
            )
        self._validate_local()
        try:
            if shutil.disk_usage(self.path).free < required_bytes:
                raise CoreError(
                    "DISK_SPACE_LOW", "Ổ dữ liệu không đủ dung lượng trống.", status=409
                )
            with tempfile.TemporaryFile(dir=self.path) as probe:
                probe.write(b"cafe-fin-write-probe")
                probe.flush()
                os.fsync(probe.fileno())
        except OSError as exc:
            raise _io_error(exc) from None

    def initialize(self) -> "DataRootService":
        self._validate_local()
        try:
            if self.path.exists() and any(self.path.iterdir()):
                raise CoreError(
                    "DATA_ROOT_EXISTS", "Thư mục đã có dữ liệu. Hãy mở dữ liệu có sẵn.", status=409
                )
            self.path.mkdir(parents=True, exist_ok=True)
            self.check_writable()
            for directory in LAYOUT:
                (self.path / directory).mkdir()
            atomic_json(self.path / MARKER, {"format": 1, "root_id": str(uuid.uuid4())})
        except OSError as exc:
            raise _io_error(exc) from None
        return self

    def open_existing(
        self, *, require_database: bool = True, writable: bool = True
    ) -> "DataRootService":
        self._validate_local()
        if not self.path.is_dir():
            raise CoreError(
                "DATA_ROOT_UNAVAILABLE", "Thư mục dữ liệu cũ không còn sẵn sàng.", status=409
            )
        try:
            marker = json.loads(self.resolve_key(MARKER).read_text(encoding="utf-8"))
            if marker.get("format") != 1:
                raise CoreError(
                    "DATA_ROOT_VERSION",
                    "Định dạng dữ liệu mới hơn hoặc không được hỗ trợ.",
                    status=409,
                )
            uuid.UUID(marker["root_id"])
        except (OSError, ValueError, KeyError, TypeError):
            raise CoreError(
                "DATA_ROOT_INVALID", "Thư mục không có dấu nhận dạng Cafe Fin hợp lệ.", status=409
            ) from None
        if any(not (self.path / part).is_dir() for part in LAYOUT):
            raise CoreError(
                "DATA_ROOT_INCOMPLETE",
                "Cấu trúc dữ liệu thiếu thư mục. Cần khôi phục từ bản sao lưu.",
                status=409,
            )
        if require_database and not self.database_path.is_file():
            raise CoreError(
                "DATABASE_MISSING",
                "Không tìm thấy DB cũ. Không tự tạo DB rỗng thay thế.",
                status=409,
            )
        if writable:
            self.check_writable()
        return self

    @property
    def database_path(self) -> Path:
        return self.resolve_key("database/cafe_fin.db")

    def resolve_key(self, key: str) -> Path:
        parts = PurePosixPath(key)
        if (
            not key
            or "\\" in key
            or ":" in key
            or parts.is_absolute()
            or any(p in ("", ".", "..") for p in key.split("/"))
        ):
            raise CoreError("FILE_KEY_INVALID", "Mã tệp không hợp lệ.")
        candidate = self.path.joinpath(*parts.parts)
        if not candidate.resolve().is_relative_to(self.path.resolve()):
            raise CoreError("FILE_KEY_INVALID", "Mã tệp nằm ngoài thư mục dữ liệu.")
        for component in (candidate, *candidate.parents):
            if component == self.path.parent:
                break
            if component.exists() and (
                component.is_symlink()
                or (hasattr(component, "is_junction") and component.is_junction())
            ):
                raise CoreError("FILE_KEY_INVALID", "Không truy cập tệp qua liên kết.")
        return candidate

    def acquire_lock(self) -> None:
        if self._lock is not None:
            return
        if not self.path.is_dir():
            raise CoreError("DATA_ROOT_UNAVAILABLE", "Thư mục dữ liệu không sẵn sàng.", status=409)
        stream = (self.path / ".instance.lock").open("a+b")
        try:
            stream.seek(0)
            if not stream.read(1):
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise CoreError(
                "DATA_ROOT_LOCKED", "Dữ liệu đang được một phiên Cafe Fin khác sử dụng.", status=409
            ) from None
        self._lock = stream

    def release_lock(self) -> None:
        if self._lock is not None:
            self._lock.close()
            self._lock = None


@dataclass(frozen=True)
class StoredFile:
    id: str
    sha256: str
    size: int
    relative_key: str
    category: str
    original_name: str
    media_type: str
    created_at: str


class FileStore:
    def __init__(self, root: DataRootService, database, writer, *, max_bytes: int = 2 * 1024**3):
        self.root, self.database, self.writer, self.max_bytes = root, database, writer, max_bytes

    def put(
        self,
        source: BinaryIO,
        *,
        category: str,
        original_name: str,
        actor: str,
        request_key: str,
        media_type: str = "application/octet-stream",
        authorize: Callable | None = None,
    ) -> StoredFile:
        if category not in ("workbooks", "documents", "reports", "imports"):
            raise CoreError("FILE_CATEGORY_INVALID", "Loại tệp không hợp lệ.")
        if (
            not original_name
            or len(original_name) > 255
            or any(char in original_name for char in ("/", "\\", "\x00"))
        ):
            raise CoreError("FILE_NAME_INVALID", "Tên tệp không hợp lệ.")
        self.root.check_writable()
        identifier = str(uuid.uuid4())
        staging = self.root.resolve_key(f"imports/{identifier}.upload-part")
        digest, size = hashlib.sha256(), 0
        try:
            with staging.open("xb") as output:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise CoreError(
                            "FILE_TOO_LARGE", "Tệp vượt giới hạn dung lượng cho phép.", status=413
                        )
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            key = f"{category}/{identifier}-{digest.hexdigest()}.bin"
            destination = self.root.resolve_key(key)
            record = StoredFile(
                identifier,
                digest.hexdigest(),
                size,
                key,
                category,
                original_name,
                media_type,
                datetime.now(timezone.utc).isoformat(),
            )

            def register(conn):
                # Hashing/streaming has finished. Only the short atomic rename joins
                # the write transaction; an idempotent replay skips it entirely.
                os.replace(staging, destination)
                conn.execute(FILES.insert().values(**asdict(record)))
                AuditService.record(
                    conn,
                    actor=actor,
                    entity="core_file",
                    entity_id=record.id,
                    action="CREATE",
                    after=asdict(record),
                )
                return asdict(record)

            payload = {
                "sha256": record.sha256,
                "size": size,
                "category": category,
                "original_name": original_name,
                "media_type": media_type,
            }
            result = self.writer.execute(
                actor, "files.put", request_key, payload, register, authorize=authorize
            )
            return StoredFile(**result)
        except OSError as exc:
            raise _io_error(exc) from None
        finally:
            staging.unlink(missing_ok=True)

    def require_owner_or_admin(self, conn: Connection, principal: Principal, file_id: str) -> None:
        """Check file provenance after the caller revalidates auth on this connection.

        A file ID is a reference, not a capability. This helper does not authenticate
        the principal or grant access to a module's domain object. Trusted module
        download routes may separately authorize their saved domain references.
        """
        try:
            if not isinstance(file_id, str) or str(uuid.UUID(file_id)) != file_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise CoreError(
                "FILE_ID_INVALID", "ID tệp phải là UUID canonical chữ thường.", 422
            ) from None
        if (
            conn.execute(select(FILES.c.id).where(FILES.c.id == file_id)).scalar_one_or_none()
            is None
        ):
            raise CoreError("FILE_NOT_FOUND", "Không tìm thấy tệp.", status=404)
        owners = (
            conn.execute(
                select(AUDIT.c.actor)
                .where(
                    AUDIT.c.entity == "core_file",
                    AUDIT.c.entity_id == file_id,
                    AUDIT.c.action == "CREATE",
                )
                .limit(2)
            )
            .scalars()
            .all()
        )
        if (
            len(owners) != 1
            or not owners[0]
            or (principal.role != "admin" and owners[0] != principal.id)
        ):
            raise CoreError("PERMISSION_DENIED", "Bạn không có quyền đọc tệp này.", 403)

    def get(self, file_id: str, *, connection: Connection | None = None) -> StoredFile:
        if connection is None:
            with self.database.read() as conn:
                return self.get(file_id, connection=conn)
        row = connection.execute(select(FILES).where(FILES.c.id == file_id)).mappings().first()
        if row is None:
            raise CoreError("FILE_NOT_FOUND", "Không tìm thấy tệp.", status=404)
        return StoredFile(**dict(row))

    @contextmanager
    def read(self, file_id: str) -> Iterator[BinaryIO]:
        record = self.get(file_id)
        path = self.root.resolve_key(record.relative_key)
        try:
            source = path.open("rb")
        except FileNotFoundError:
            raise CoreError(
                "FILE_MISSING",
                "Tệp được tham chiếu đang bị thiếu. Cần kiểm tra bản sao lưu.",
                status=409,
            ) from None
        except OSError as exc:
            raise _io_error(exc) from None
        with source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
            if (
                os.fstat(source.fileno()).st_size != record.size
                or digest.hexdigest() != record.sha256
            ):
                raise CoreError(
                    "FILE_HASH_MISMATCH", "Nội dung tệp không khớp bản đã lưu.", status=409
                )
            source.seek(0)
            yield source

    def export(self, file_id: str, trusted_native_destination: Path) -> dict:
        """Destination comes from a scoped native save dialog, not a renderer path."""
        destination = Path(trusted_native_destination)
        if destination.exists():
            raise CoreError("EXPORT_EXISTS", "Tệp đích đã tồn tại. Chọn tên mới.", status=409)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        try:
            with self.read(file_id) as source, temporary.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            # Hard-link is atomic and refuses replacement, including a destination race.
            os.link(temporary, destination)
            return {"sha256": sha256_file(destination), "size": destination.stat().st_size}
        except OSError as exc:
            raise _io_error(exc) from None
        finally:
            temporary.unlink(missing_ok=True)

    def reconcile(self) -> dict[str, list[str]]:
        with self.database.read() as conn:
            rows = [StoredFile(**dict(row)) for row in conn.execute(select(FILES)).mappings()]
        known = {row.relative_key for row in rows}
        missing, mismatched = [], []
        for row in rows:
            path = self.root.resolve_key(row.relative_key)
            if not path.is_file():
                missing.append(row.id)
            elif path.stat().st_size != row.size or sha256_file(path) != row.sha256:
                mismatched.append(row.id)
        orphans = []
        for category in ("workbooks", "documents", "reports", "imports"):
            for path in (self.root.path / category).rglob("*"):
                if path.is_file() and path.relative_to(self.root.path).as_posix() not in known:
                    orphans.append(path.relative_to(self.root.path).as_posix())
        return {
            "missing_file_ids": missing,
            "mismatched_file_ids": mismatched,
            "orphan_keys": sorted(orphans),
        }
