"""Durable, cooperative local jobs; interrupted effects resume only by explicit request."""

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
)

from .db import Database, WriteCoordinator, canonical_json
from .errors import CoreError
from .modules import Migration, schema_checksum
from .time import utc_now

_metadata = MetaData()
JOBS = Table(
    "core_jobs",
    _metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("state", String, nullable=False),
    Column("phase", String, nullable=False),
    Column("counts_json", Text, nullable=False),
    Column("checkpoint_json", Text, nullable=False),
    Column("cancel_requested", Boolean, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("error_code", String),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)
RECEIPTS = Table(
    "core_job_receipts",
    _metadata,
    Column("job_id", String, ForeignKey("core_jobs.id"), primary_key=True),
    Column("chunk_id", String, primary_key=True),
    Column("payload_hash", String, nullable=False),
    Column("result_json", Text, nullable=False),
)
MIGRATIONS = (
    Migration(
        "core_jobs",
        1,
        "durable_jobs_and_receipts",
        _metadata.create_all,
        checksum=schema_checksum(_metadata),
    ),
)


def _dto(row):
    return {
        key: row[key]
        for key in (
            "id",
            "kind",
            "actor",
            "state",
            "phase",
            "attempts",
            "error_code",
            "created_at",
            "updated_at",
        )
    } | {
        "counts": json.loads(row["counts_json"]),
        "checkpoint": json.loads(row["checkpoint_json"]),
        "cancel_requested": row["cancel_requested"],
    }


@dataclass(frozen=True)
class JobHandler:
    run: Callable[["JobContext", dict], None]
    resumable: bool = False


class JobInterrupted(Exception):
    pass


class JobService:
    def __init__(
        self,
        database: Database,
        writer: WriteCoordinator,
        handlers: dict[str, JobHandler] | None = None,
    ):
        self.database, self.writer = database, writer
        self.handlers = handlers or {}
        self.wake = threading.Event()

    def submit(self, actor: str, kind: str, payload: dict, request_key: str):
        if kind not in self.handlers:
            raise CoreError("UNKNOWN_JOB", "Tác vụ chưa được đăng ký.")
        if len(canonical_json(payload).encode()) > 64 * 1024:
            raise CoreError(
                "JOB_PAYLOAD_TOO_LARGE", "Tác vụ phải tham chiếu snapshot, không gửi dữ liệu lớn."
            )

        def operation(conn):
            job_id, now = str(uuid.uuid4()), utc_now()
            conn.execute(
                insert(JOBS).values(
                    id=job_id,
                    kind=kind,
                    actor=actor,
                    payload_json=canonical_json(payload),
                    state="WAITING",
                    phase="queued",
                    counts_json="{}",
                    checkpoint_json="{}",
                    cancel_requested=False,
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            return {"job_id": job_id, "state": "WAITING"}

        result = self.writer.execute(
            actor, "jobs.submit", request_key, {"kind": kind, "payload": payload}, operation
        )
        self.wake.set()
        return result

    def status(self, job_id: str):
        with self.database.read() as conn:
            row = conn.execute(select(JOBS).where(JOBS.c.id == job_id)).mappings().first()
        if row is None:
            raise CoreError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
        return _dto(row)

    def cancel(self, job_id: str):
        def operation(conn):
            row = conn.execute(select(JOBS).where(JOBS.c.id == job_id)).mappings().first()
            if row is None:
                raise CoreError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
            if row.state == "COMPLETED":
                raise CoreError(
                    "JOB_ALREADY_COMPLETED", "Tác vụ đã hoàn tất; cần thao tác hoàn tác riêng.", 409
                )
            state = "CANCELLED" if row.state != "RUNNING" else "RUNNING"
            conn.execute(
                JOBS.update()
                .where(JOBS.c.id == job_id)
                .values(state=state, cancel_requested=True, updated_at=utc_now())
            )

        self.writer.run(operation)
        return self.status(job_id)

    def resume(self, job_id: str):
        def operation(conn):
            row = conn.execute(select(JOBS).where(JOBS.c.id == job_id)).mappings().first()
            if row is None:
                raise CoreError("JOB_NOT_FOUND", "Không tìm thấy tác vụ.", 404)
            handler = self.handlers.get(row.kind)
            if not handler or not handler.resumable:
                raise CoreError("JOB_NOT_RESUMABLE", "Tác vụ này không hỗ trợ chạy tiếp.", 409)
            if row.state not in {"RECOVERABLE", "FAILED", "CANCELLED"}:
                raise CoreError(
                    "JOB_STATE_CONFLICT", "Trạng thái hiện tại không cho phép chạy tiếp.", 409
                )
            if row.attempts >= 3:
                raise CoreError(
                    "JOB_RETRY_LIMIT", "Đã hết số lần thử; cần kiểm tra nguyên nhân.", 409
                )
            conn.execute(
                JOBS.update()
                .where(JOBS.c.id == job_id)
                .values(
                    state="WAITING", cancel_requested=False, error_code=None, updated_at=utc_now()
                )
            )

        self.writer.run(operation)
        self.wake.set()
        return self.status(job_id)

    def recover_interrupted(self):
        def operation(conn):
            conn.execute(
                JOBS.update()
                .where(JOBS.c.state == "RUNNING")
                .values(state="RECOVERABLE", error_code="PROCESS_INTERRUPTED", updated_at=utc_now())
            )

        self.writer.run(operation)


class JobContext:
    def __init__(self, service: JobService, job_id: str, stop: threading.Event):
        self.service, self.job_id, self.stop = service, job_id, stop

    def checkpoint(self):
        return self.service.status(self.job_id)["checkpoint"]

    def check_cancelled(self):
        status = self.service.status(self.job_id)
        if self.stop.is_set() or status["cancel_requested"]:
            raise JobInterrupted()

    def commit_chunk(
        self,
        chunk_id: str,
        payload: dict,
        *,
        checkpoint: dict,
        counts: dict[str, int],
        phase: str,
        effect: Callable,
    ):
        """Effect, receipt and progress share a transaction; retries never reapply effect."""
        self.check_cancelled()
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise CoreError("INVALID_JOB_COUNTS", "Tiến độ tác vụ không hợp lệ.")
        if len(canonical_json(checkpoint).encode()) > 64 * 1024:
            raise CoreError("CHECKPOINT_TOO_LARGE", "Checkpoint phải tham chiếu snapshot theo ID.")
        digest = hashlib.sha256(
            canonical_json(
                {"payload": payload, "checkpoint": checkpoint, "counts": counts, "phase": phase}
            ).encode()
        ).hexdigest()

        def operation(conn):
            row = conn.execute(select(JOBS).where(JOBS.c.id == self.job_id)).mappings().one()
            if row.state != "RUNNING" or row.cancel_requested or self.stop.is_set():
                raise JobInterrupted()
            receipt = (
                conn.execute(
                    select(RECEIPTS).where(
                        RECEIPTS.c.job_id == self.job_id, RECEIPTS.c.chunk_id == chunk_id
                    )
                )
                .mappings()
                .first()
            )
            if receipt:
                if receipt.payload_hash != digest:
                    raise CoreError("JOB_CHUNK_CONFLICT", "Chunk đã dùng cho dữ liệu khác.", 409)
                return json.loads(receipt.result_json)
            result = effect(conn)
            conn.execute(
                insert(RECEIPTS).values(
                    job_id=self.job_id,
                    chunk_id=chunk_id,
                    payload_hash=digest,
                    result_json=canonical_json(result),
                )
            )
            conn.execute(
                JOBS.update()
                .where(JOBS.c.id == self.job_id)
                .values(
                    checkpoint_json=canonical_json(checkpoint),
                    counts_json=canonical_json(counts),
                    phase=phase,
                    updated_at=utc_now(),
                )
            )
            return result

        return self.service.writer.run(operation)

    def finalize(self, effect: Callable):
        """Final publication and COMPLETED are atomic against concurrent cancellation."""

        def operation(conn):
            row = conn.execute(select(JOBS).where(JOBS.c.id == self.job_id)).mappings().one()
            if row.state != "RUNNING" or row.cancel_requested or self.stop.is_set():
                raise JobInterrupted()
            result = effect(conn)
            conn.execute(
                JOBS.update()
                .where(JOBS.c.id == self.job_id)
                .values(state="COMPLETED", error_code=None, updated_at=utc_now())
            )
            return result

        return self.service.writer.run(operation)


class JobRunner:
    def __init__(self, service: JobService):
        self.service = service
        self.stop_event = threading.Event()
        self.error_code: str | None = None
        self.thread = threading.Thread(target=self._loop, name="cafe-fin-jobs", daemon=True)

    def start(self):
        self.service.recover_interrupted()
        self.thread.start()

    def _claim(self, conn):
        row = (
            conn.execute(
                select(JOBS)
                .where(JOBS.c.state == "WAITING")
                .order_by(JOBS.c.created_at, JOBS.c.id)
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row:
            conn.execute(
                JOBS.update()
                .where(JOBS.c.id == row.id)
                .values(state="RUNNING", attempts=row.attempts + 1, updated_at=utc_now())
            )
            return dict(row)

    def _write_with_backpressure(self, operation: Callable, *, finish: bool = False):
        while finish or not self.stop_event.is_set():
            try:
                return self.service.writer.run(operation)
            except CoreError as exc:
                if exc.code != "WRITER_BUSY":
                    raise
                # A claimed job must durably finish even during graceful shutdown.
                # Other failures are surfaced by _loop; never retry programming errors.
                if finish and self.stop_event.is_set():
                    time.sleep(0.05)
                else:
                    self.stop_event.wait(0.05)
        return None

    def _loop(self):
        try:
            self._run_loop()
        except CoreError as exc:
            self.error_code = exc.code
            self.stop_event.set()
        except Exception:
            # Health exposes only the stable code, never payloads or exception text.
            self.error_code = "JOB_RUNNER_FAILED"
            self.stop_event.set()

    def _run_loop(self):
        while not self.stop_event.is_set():
            row = self._write_with_backpressure(self._claim)
            if row is None:
                self.service.wake.wait(0.2)
                self.service.wake.clear()
                continue
            state, error = "COMPLETED", None
            try:
                handler = self.service.handlers.get(row["kind"])
                if not handler:
                    raise CoreError("UNKNOWN_JOB", "Tác vụ chưa được đăng ký.")
                context = JobContext(self.service, row["id"], self.stop_event)
                context.check_cancelled()
                handler.run(context, json.loads(row["payload_json"]))
                if self.service.status(row["id"])["state"] != "COMPLETED":
                    context.check_cancelled()
            except JobInterrupted:
                cancelled = self.service.status(row["id"])["cancel_requested"]
                state, error = ("CANCELLED", None) if cancelled else ("RECOVERABLE", "APP_SHUTDOWN")
            except CoreError as exc:
                state, error = "FAILED", exc.code
            except Exception:
                state, error = "FAILED", "JOB_FAILED"

            def finish(conn):
                current = conn.execute(select(JOBS).where(JOBS.c.id == row["id"])).mappings().one()
                if current.state == "COMPLETED":
                    return
                final_state = (
                    "CANCELLED" if current.cancel_requested and state == "COMPLETED" else state
                )
                conn.execute(
                    JOBS.update()
                    .where(JOBS.c.id == row["id"])
                    .values(state=final_state, error_code=error, updated_at=utc_now())
                )

            self._write_with_backpressure(finish, finish=True)

    def close(self):
        self.stop_event.set()
        self.service.wake.set()
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise CoreError("JOB_SHUTDOWN_TIMEOUT", "Tác vụ chưa dừng tại ranh giới an toàn.", 503)
