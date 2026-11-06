"""Local Argon2 credentials and ephemeral, revocable user sessions. No OAuth."""

import hashlib
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type, hash_secret_raw
from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, func, insert, select

from .audit import AuditService, require_version
from .db import Database, WriteCoordinator
from .errors import CoreError
from .modules import Migration
from .time import utc_now

_meta = MetaData()
USERS = Table(
    "core_users",
    _meta,
    Column("id", String, primary_key=True),
    Column("username", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
MIGRATIONS = (Migration("core_auth", 1, "local_users", _meta.create_all),)
OPERATOR_PERMISSIONS = (
    "core.read",
    "core.write",
    "files.read",
    "files.write",
    "jobs.read",
    "jobs.write",
    "spikes.use",
    "records.read",
    "records.write",
    "contracts.read",
    "contracts.write",
    "accounting.read",
    "accounting.write",
    "reporting.read",
)


@dataclass(frozen=True)
class Principal:
    id: str
    username: str
    role: str
    permissions: tuple[str, ...]

    def public(self):
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "permissions": list(self.permissions),
        }

    def require(self, permission: str):
        if "*" not in self.permissions and permission not in self.permissions:
            raise CoreError("PERMISSION_DENIED", "Bạn không có quyền thực hiện thao tác này.", 403)


class AuthService:
    def __init__(self, database: Database, writer: WriteCoordinator):
        self.database, self.writer = database, writer
        self._hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
        self._dummy = self._hasher.hash(secrets.token_urlsafe(24))
        self._lock = threading.Lock()
        self._sessions: dict[str, tuple[str, float]] = {}
        self._failures: deque[float] = deque()

    @staticmethod
    def _validate(username: str, password: str):
        if (
            not isinstance(username, str)
            or not 3 <= len(username) <= 64
            or username.strip() != username
        ):
            raise CoreError("INVALID_USERNAME", "Tên tài khoản cần từ 3 đến 64 ký tự.")
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise CoreError("WEAK_PASSWORD", "Mật khẩu cần từ 10 đến 128 ký tự.")

    def setup_required(self):
        with self.database.read() as conn:
            return conn.execute(select(func.count()).select_from(USERS)).scalar_one() == 0

    @staticmethod
    def _principal(row) -> Principal:
        return Principal(
            row["id"],
            row["username"],
            row["role"],
            ("*",) if row["role"] == "admin" else OPERATOR_PERMISSIONS,
        )

    def _issue(self, principal: Principal):
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.monotonic()
            self._sessions = {key: item for key, item in self._sessions.items() if item[1] > now}
            if len(self._sessions) >= 64:
                raise CoreError("SESSION_LIMIT", "Có quá nhiều phiên đăng nhập.", 429)
            self._sessions[hashlib.sha256(token.encode()).hexdigest()] = (
                principal.id,
                now + 8 * 3600,
            )
        return {"access_token": token, "user": principal.public()}

    def setup(self, username: str, password: str):
        self._validate(username, password)
        password_hash = self._hasher.hash(password)
        user_id = str(uuid.uuid4())

        def operation(conn):
            if conn.execute(select(func.count()).select_from(USERS)).scalar_one():
                raise CoreError("SETUP_COMPLETE", "Tài khoản quản trị đã được thiết lập.", 409)
            now = utc_now()
            conn.execute(
                insert(USERS).values(
                    id=user_id,
                    username=username,
                    password_hash=password_hash,
                    role="admin",
                    active=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            AuditService.record(
                conn,
                actor=user_id,
                entity="user",
                entity_id=user_id,
                action="setup",
                after={"username": username, "role": "admin"},
            )

        self.writer.run(operation)
        return self._issue(Principal(user_id, username, "admin", ("*",)))

    def login(self, username: str, password: str):
        if len(username) > 64 or len(password) > 128:
            raise CoreError("LOGIN_FAILED", "Tài khoản hoặc mật khẩu không đúng.", 401)
        with self._lock:
            now = time.monotonic()
            while self._failures and self._failures[0] < now - 60:
                self._failures.popleft()
            if len(self._failures) >= 8:
                raise CoreError(
                    "LOGIN_RATE_LIMIT", "Đăng nhập sai nhiều lần, hãy thử lại sau.", 429
                )
            # Reserve the attempt before expensive hashing to bound concurrent brute force.
            self._failures.append(now)
        with self.database.read() as conn:
            row = conn.execute(select(USERS).where(USERS.c.username == username)).mappings().first()
        try:
            valid = self._hasher.verify(row.password_hash if row else self._dummy, password)
        except (VerificationError, InvalidHashError):
            valid = False
        if not row or not valid or not row.active:
            raise CoreError("LOGIN_FAILED", "Tài khoản hoặc mật khẩu không đúng.", 401)
        return self._issue(self._principal(row))

    def authenticate(self, token: str | None) -> Principal:
        if not token or len(token) > 128:
            raise CoreError("LOGIN_REQUIRED", "Vui lòng đăng nhập lại.", 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            session = self._sessions.get(digest)
            if not session or session[1] <= time.monotonic():
                self._sessions.pop(digest, None)
                raise CoreError("SESSION_EXPIRED", "Phiên đăng nhập đã hết hạn.", 401)
        with self.database.read() as conn:
            row = conn.execute(select(USERS).where(USERS.c.id == session[0])).mappings().first()
        if not row or not row.active:
            raise CoreError("SESSION_EXPIRED", "Phiên đăng nhập không còn hiệu lực.", 401)
        return self._principal(row)

    def logout(self, token: str):
        with self._lock:
            self._sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def create_user(
        self, actor: Principal, *, username: str, password: str, role: str, request_key: str
    ):
        actor.require("core.manage")
        self._validate(username, password)
        if role not in {"admin", "operator"}:
            raise CoreError("INVALID_ROLE", "Nhóm quyền không hợp lệ.")
        password_hash = self._hasher.hash(password)

        def operation(conn):
            if conn.execute(select(USERS.c.id).where(USERS.c.username == username)).first():
                raise CoreError("USERNAME_EXISTS", "Tên tài khoản đã tồn tại.", 409)
            user_id, now = str(uuid.uuid4()), utc_now()
            conn.execute(
                insert(USERS).values(
                    id=user_id,
                    username=username,
                    password_hash=password_hash,
                    role=role,
                    active=True,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            result = {
                "id": user_id,
                "username": username,
                "role": role,
                "version": 1,
                "active": True,
            }
            AuditService.record(
                conn,
                actor=actor.id,
                entity="user",
                entity_id=user_id,
                action="create",
                after=result,
            )
            return result

        # A deterministic Argon2 binding preserves request replay across restarts without
        # creating a fast SHA password oracle in the persisted idempotency payload hash.
        salt = hashlib.sha256(f"{actor.id}:{request_key}".encode()).digest()[:16]
        credential_binding = hash_secret_raw(
            password.encode(),
            salt,
            time_cost=3,
            memory_cost=65536,
            parallelism=2,
            hash_len=32,
            type=Type.ID,
        ).hex()
        payload = {"username": username, "role": role, "credential_binding": credential_binding}
        return self.writer.execute(actor.id, "users.create", request_key, payload, operation)

    def update_user(
        self,
        actor: Principal,
        user_id: str,
        *,
        role: str,
        active: bool,
        expected_version: int,
        request_key: str,
    ):
        actor.require("core.manage")
        if role not in {"admin", "operator"}:
            raise CoreError("INVALID_ROLE", "Nhóm quyền không hợp lệ.")

        def operation(conn):
            row = conn.execute(select(USERS).where(USERS.c.id == user_id)).mappings().first()
            if not row:
                raise CoreError("NOT_FOUND", "Không tìm thấy tài khoản.", 404)
            version = require_version(row.version, expected_version)
            if row.role == "admin" and row.active and (role != "admin" or not active):
                admins = conn.execute(
                    select(func.count())
                    .select_from(USERS)
                    .where(USERS.c.role == "admin", USERS.c.active.is_(True))
                ).scalar_one()
                if admins <= 1:
                    raise CoreError(
                        "LAST_ADMIN", "Phải giữ ít nhất một quản trị viên hoạt động.", 409
                    )
            result = {
                "id": user_id,
                "username": row.username,
                "role": role,
                "active": active,
                "version": version,
            }
            conn.execute(
                USERS.update()
                .where(USERS.c.id == user_id)
                .values(role=role, active=active, version=version, updated_at=utc_now())
            )
            AuditService.record(
                conn,
                actor=actor.id,
                entity="user",
                entity_id=user_id,
                action="update",
                before={"role": row.role, "active": row.active, "version": row.version},
                after=result,
            )
            return result

        result = self.writer.execute(
            actor.id,
            "users.update",
            request_key,
            {"id": user_id, "role": role, "active": active, "expected_version": expected_version},
            operation,
        )
        with self._lock:
            self._sessions = {
                key: value for key, value in self._sessions.items() if value[0] != user_id
            }
        return result
