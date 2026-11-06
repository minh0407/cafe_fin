"""Short SQLite transactions through one bounded writer; readers use fresh connections."""

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import quote

from sqlalchemy import (
    URL,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from .errors import CoreError
from .modules import Migration, schema_checksum
from .time import utc_now

T = TypeVar("T")
metadata = MetaData()
SCHEMA = Table(
    "core_schema_migrations",
    metadata,
    Column("namespace", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("name", String, nullable=False),
    Column("checksum", String, nullable=False),
    Column("applied_at", String, nullable=False),
)
REQUESTS = Table(
    "core_requests",
    metadata,
    Column("actor", String, primary_key=True),
    Column("action", String, primary_key=True),
    Column("request_key", String, primary_key=True),
    Column("payload_hash", String, nullable=False),
    Column("result_json", Text, nullable=False),
    Column("created_at", String, nullable=False),
)
AUDIT = Table(
    "core_audit",
    metadata,
    Column("id", String, primary_key=True),
    Column("actor", String, nullable=False),
    Column("entity", String, nullable=False),
    Column("entity_id", String, nullable=False),
    Column("action", String, nullable=False),
    Column("before_json", Text),
    Column("after_json", Text),
    Column("recorded_at", String, nullable=False),
)


def canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


class Database:
    def __init__(self, path: Path | str, *, create: bool = True):
        self.path = Path(path).resolve()
        self._allow_initialize = create
        if sqlite3.sqlite_version_info < (3, 51, 3) or sqlite3.sqlite_version_info == (3, 52, 0):
            raise CoreError(
                "SQLITE_UNSUPPORTED",
                "Runtime SQLite chưa có bản sửa WAL được hỗ trợ.",
                503,
                details={"sqlite_version": sqlite3.sqlite_version},
            )
        if not self.path.is_file():
            if not create:
                raise CoreError(
                    "DATABASE_MISSING",
                    "Không tìm thấy cơ sở dữ liệu đã cấu hình. Kiểm tra ổ đĩa và khôi phục dữ liệu.",
                    409,
                )
            try:
                with self.path.open("xb"):
                    pass
            except OSError as exc:
                raise CoreError(
                    "DATABASE_UNAVAILABLE", "Không thể tạo cơ sở dữ liệu tại thư mục đã chọn.", 409
                ) from exc
        elif not create and self.path.stat().st_size == 0:
            raise CoreError(
                "DATABASE_INVALID",
                "Cơ sở dữ liệu hiện có bị rỗng; cần kiểm tra hoặc khôi phục bản sao lưu.",
                409,
            )
        # Every subsequent connection is mode=rw: losing the file can never create an
        # empty replacement. Quote URI metacharacters while retaining the drive prefix.
        database_uri = "file:" + quote(self.path.as_posix(), safe="/:")
        self._source_uri = database_uri + "?mode=rw"
        self.engine = create_engine(
            URL.create("sqlite", database=database_uri, query={"mode": "rw", "uri": "true"}),
            poolclass=NullPool,
            connect_args={"timeout": 10, "check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA synchronous=FULL")

        with self.engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
            if mode.lower() != "wal":
                raise CoreError("WAL_UNAVAILABLE", "Không bật được WAL cho cơ sở dữ liệu.", 503)
            conn.commit()

    @contextmanager
    def read(self):
        with self.engine.connect() as conn:
            # Readers cannot accidentally bypass the serialized writer or retain writes.
            # NullPool ensures this connection-local restriction never reaches a writer.
            conn.exec_driver_sql("PRAGMA query_only=ON")
            yield conn

    def migrate(self, migrations: tuple[Migration, ...] = ()) -> None:
        """Run at boot before readers/jobs. Versions are contiguous within each namespace."""
        planned = {
            ("core", 1): Migration(
                "core",
                1,
                "foundation_tables",
                metadata.create_all,
                checksum=schema_checksum(metadata),
            )
        }
        for migration in migrations:
            key = migration.namespace, migration.version
            if key in planned:
                raise CoreError("DUPLICATE_MIGRATION", "Migration bị đăng ký lặp.", 503)
            planned[key] = migration
        namespaces = list(dict.fromkeys(key[0] for key in planned))
        for namespace in namespaces:
            versions = sorted(v for ns, v in planned if ns == namespace)
            if versions != list(range(1, len(versions) + 1)):
                raise CoreError("MIGRATION_GAP", "Thiếu thứ tự migration.", 503)
        with self.engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                if not self._allow_initialize and not conn.dialect.has_table(conn, SCHEMA.name):
                    raise CoreError(
                        "DATABASE_INVALID",
                        "Cơ sở dữ liệu chưa có registry Cafe Fin; không tự khởi tạo dữ liệu thay thế.",
                        409,
                    )
                SCHEMA.create(conn, checkfirst=True)
                applied = {
                    (row.namespace, row.version): row
                    for row in conn.execute(select(SCHEMA)).mappings()
                }
                for key, row in applied.items():
                    migration = planned.get(key)
                    if migration is None:
                        raise CoreError(
                            "SCHEMA_NEWER_THAN_APP", "Dữ liệu cần phiên bản ứng dụng mới hơn.", 409
                        )
                    if row.checksum != migration.fingerprint:
                        raise CoreError(
                            "MIGRATION_CHANGED", "Migration đã áp dụng bị thay đổi.", 409
                        )
                # Preserve first-seen namespace dependency order, sorting versions inside
                # each namespace even when a caller supplied its migration tuple backwards.
                ordered_keys = [
                    key
                    for namespace in namespaces
                    for key in sorted(planned)
                    if key[0] == namespace
                ]
                for key in ordered_keys:
                    migration = planned[key]
                    if key not in applied:
                        migration.apply(conn)
                        conn.execute(
                            insert(SCHEMA).values(
                                namespace=migration.namespace,
                                version=migration.version,
                                name=migration.name,
                                checksum=migration.fingerprint,
                                applied_at=utc_now(),
                            )
                        )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def backup_to(self, destination: Path | str) -> None:
        """Call inside writer.barrier, with no write transaction held."""
        with (
            closing(sqlite3.connect(self._source_uri, uri=True)) as source,
            closing(sqlite3.connect(destination)) as target,
        ):
            source.backup(target, pages=256)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CoreError("BACKUP_INVALID", "Snapshot cơ sở dữ liệu không hợp lệ.", 500)

    def close(self) -> None:
        self.engine.dispose()


class WriteCoordinator:
    def __init__(self, database: Database, capacity: int = 64):
        self.database = database
        self._slots = threading.BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cafe-fin-writer")
        self._state = threading.Lock()
        self._closed = False
        self._worker = threading.local()

    def _submit(self, operation: Callable[[Connection], T], transactional: bool) -> T:
        if getattr(self._worker, "active", False):
            raise CoreError("NESTED_WRITE", "Không gọi writer lồng nhau.", 500)
        if not self._slots.acquire(blocking=False):
            raise CoreError("WRITER_BUSY", "Hàng đợi ghi đang đầy, vui lòng thử lại.", 503)

        def work():
            self._worker.active = True
            try:
                with self.database.engine.connect() as conn:
                    if transactional:
                        conn.exec_driver_sql("BEGIN IMMEDIATE")
                    try:
                        result = operation(conn)
                        if transactional:
                            conn.commit()
                        return result
                    except BaseException:
                        conn.rollback()
                        raise
            finally:
                self._worker.active = False

        try:
            with self._state:
                if self._closed:
                    raise CoreError("WRITER_CLOSED", "Ứng dụng đang đóng.", 503)
                future = self._executor.submit(work)
            return future.result()
        finally:
            self._slots.release()

    def run(self, operation: Callable[[Connection], T]) -> T:
        return self._submit(operation, True)

    def barrier(self, operation: Callable[[Connection], T]) -> T:
        """Exclusive writer slot without BEGIN, for DB snapshot plus immutable file inventory."""
        return self._submit(operation, False)

    def execute(
        self,
        actor: str,
        action: str,
        request_key: str,
        payload,
        operation: Callable[[Connection], T],
    ) -> T:
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 128:
            raise CoreError("INVALID_REQUEST_KEY", "Thiếu khóa chống ghi lặp hợp lệ.")
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()

        def command(conn):
            existing = (
                conn.execute(
                    select(REQUESTS).where(
                        REQUESTS.c.actor == actor,
                        REQUESTS.c.action == action,
                        REQUESTS.c.request_key == request_key,
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                if existing.payload_hash != digest:
                    raise CoreError(
                        "IDEMPOTENCY_CONFLICT", "Khóa yêu cầu đã dùng cho dữ liệu khác.", 409
                    )
                return json.loads(existing.result_json)
            result = operation(conn)
            conn.execute(
                insert(REQUESTS).values(
                    actor=actor,
                    action=action,
                    request_key=request_key,
                    payload_hash=digest,
                    result_json=canonical_json(result),
                    created_at=utc_now(),
                )
            )
            return result

        return self.run(command)

    def close(self) -> None:
        with self._state:
            self._closed = True
        self._executor.shutdown(wait=True)
