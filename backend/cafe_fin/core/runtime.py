"""Trusted bootstrap. Native selection owns absolute paths; modules use service handles."""

from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy.engine import Connection

from . import auth, imports, jobs, storage
from .activation import begin_activation, boot_preflight, complete_activation, guarded_boot_mode
from .auth import AuthService
from .backup import BackupService
from .db import Database, WriteCoordinator
from .errors import CoreError
from .jobs import JobHandler, JobRunner, JobService
from .maintenance import AdmissionGate, drain_timeout, operation_identity
from .modules import ModuleRegistry
from .periodic import PeriodicRunner
from .storage import DataRootService, FileStore
from .workbook_spike import WorkbookSpike


def sample_job(context, payload):
    """Small registration proof, never a production import or report."""
    next_step = context.checkpoint().get("next", 0)
    for index in range(next_step, 3):
        context.check_cancelled()
        context.commit_chunk(
            str(index),
            {"step": index},
            checkpoint={"next": index + 1},
            counts={"steps": index + 1},
            phase="foundation_sample",
            effect=lambda conn: {"step": index},
        )
    context.finalize(lambda conn: {"sample_complete": True})


class Runtime:
    def __init__(
        self,
        path: Path | str,
        *,
        initialize: bool = False,
        modules: ModuleRegistry | None = None,
        activation_mode: str = "active",
    ):
        self.maintenance = AdmissionGate(activation_mode)
        self.root = DataRootService(path)
        self.database = self.writer = self.runner = self.periodic = None
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self._closing = False
        self._started = False
        if initialize:
            self.root.initialize()
        else:
            self.root.open_existing()
        self.root.acquire_lock()
        try:
            context = boot_preflight(self.root)
            self.database = Database(self.root.database_path, create=initialize)
            if modules is None:
                from cafe_fin.registry import registered_modules

                modules = registered_modules()
            self.modules = modules
            migrations = auth.MIGRATIONS + jobs.MIGRATIONS + storage.MIGRATIONS + imports.MIGRATIONS
            migrations += tuple(m for module in self.modules.ordered() for m in module.migrations)
            self.database.migrate(migrations)
            self.maintenance = AdmissionGate(
                guarded_boot_mode(self.root, self.database, activation_mode, context)
            )
            self.reader: Callable[[], AbstractContextManager[Connection]] = self.database.read
            self.writer = WriteCoordinator(self.database)
            self.auth = AuthService(self.database, self.writer)
            self.files = FileStore(self.root, self.database, self.writer)
            self.workbook_spike = WorkbookSpike(self.files)
            self.backups = BackupService(self.root, self.database, self.writer)
            self.render_lock = threading.Lock()
            handlers = {"foundation.sample": JobHandler(sample_job, resumable=True)}
            for module in self.modules.ordered():
                for kind, handler in module.job_handlers.items():
                    if kind in handlers:
                        raise CoreError(
                            "DUPLICATE_JOB_KIND",
                            "Loại job đã được core hoặc module khác đăng ký.",
                            503,
                        )
                    handlers[kind] = handler
            self.jobs = JobService(
                self.database,
                self.writer,
                handlers,
            )
            self.runner = JobRunner(self.jobs)
            self.periodic = PeriodicRunner(
                self,
                {
                    name: task
                    for module in self.modules.ordered()
                    for name, task in module.periodic_tasks.items()
                },
            )
            self.logger = logging.getLogger(f"cafe_fin.{id(self)}")
            self.logger.propagate = False
            self.logger.setLevel(logging.INFO)
            self.log_handler = logging.handlers.RotatingFileHandler(
                self.root.resolve_key("logs/app.log"),
                maxBytes=1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            self.log_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            self.logger.addHandler(self.log_handler)
        except BaseException:
            self.close()
            raise

    def start(self):
        with self._lifecycle_lock:
            if self._closed or self._closing:
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            if self.maintenance.status()["state"] != "ACTIVE":
                return
            self._start_services(cleanup_on_failure=True)

    def _start_services(self, *, cleanup_on_failure: bool):
        if not self._started:
            try:
                # Recovery/hooks finish before jobs, then the independent timer starts.
                self.jobs.recover_interrupted()
                for module in self.modules.ordered():
                    if module.on_startup is not None:
                        module.on_startup(self)
                self.runner.start()
                self.periodic.start()
                self._started = True
            except BaseException:
                if cleanup_on_failure:
                    self.close()
                raise

    def _maintenance_actor(self, access_token):
        actor = self.auth.authenticate(access_token)
        with self.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.auth.authorize(conn, actor, "core.manage")
        return actor

    def _maintenance_fence(self, actor, access_token):
        def authorize(conn):
            current = self.auth.authenticate(access_token)
            if current.id != actor.id:
                raise CoreError("SESSION_EXPIRED", "Phiên đăng nhập không còn hiệu lực.", 401)
            self.auth.authorize(conn, actor, "core.manage")

        self.writer.run(authorize)

    def activate(self, operation_id: str, *, access_token: str) -> dict:
        operation_id = operation_identity(operation_id)
        with self._lifecycle_lock:
            if self._closed or self._closing:
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            actor = self._maintenance_actor(access_token)
            # Serialized current authorization precedes any hook, recovery or worker.
            self._maintenance_fence(actor, access_token)
            state = self.maintenance.status()
            replay = state["state"] == "ACTIVE" and state["operation_id"] == operation_id
            if not replay and (state["state"] != "DORMANT" or state["operation_id"] is not None):
                raise CoreError("MAINTENANCE_CONFLICT", "Trạng thái bảo trì không phù hợp.", 409)
            context, activation_payload, run_hooks = begin_activation(
                self, actor, access_token, operation_id
            )
            if replay:
                return state
            if not self.maintenance.begin_activation(operation_id):
                return self.maintenance.status()
            try:
                if context is not None and run_hooks:
                    for module in self.modules.ordered():
                        if module.on_activate is not None:
                            module.on_activate(self, actor, context)
                self._start_services(cleanup_on_failure=False)
                if run_hooks:
                    complete_activation(self, actor, access_token, operation_id, activation_payload)
            except BaseException:
                self.periodic.request_stop()
                self.runner.request_stop()
                self.maintenance.failed("MAINTENANCE_ACTIVATION_FAILED")
                raise CoreError(
                    "MAINTENANCE_ACTIVATION_FAILED", "Không kích hoạt được dữ liệu.", 503
                ) from None
            self.maintenance.activated()
            return self.maintenance.status()

    def quiesce(self, operation_id: str, *, access_token: str, drain_timeout_seconds=10) -> dict:
        operation_id = operation_identity(operation_id)
        timeout = drain_timeout(drain_timeout_seconds)
        with self._lifecycle_lock:
            if self._closed:
                raise CoreError("RUNTIME_CLOSED", "Dịch vụ dữ liệu đang đóng hoặc đã dừng.", 503)
            actor = self._maintenance_actor(access_token)
            self.maintenance.hold(operation_id)
            self._closing = True  # Terminal: start cannot restart either stopped thread.
            self.periodic.request_stop()
            self.runner.request_stop()
            deadline = time.monotonic() + timeout
            try:
                self.maintenance.wait_for_drain(deadline, include_safe=False)
                for thread, code in (
                    (self.periodic.thread, "PERIODIC_SHUTDOWN_TIMEOUT"),
                    (self.runner.thread, "JOB_SHUTDOWN_TIMEOUT"),
                ):
                    if thread.ident is not None:
                        thread.join(timeout=max(0, deadline - time.monotonic()))
                    if thread.is_alive():
                        raise CoreError(code, "Tác vụ chưa dừng tại ranh giới an toàn.", 503)
                self._maintenance_fence(actor, access_token)
            except BaseException as exc:
                self.maintenance.failed(
                    exc.code if isinstance(exc, CoreError) else "MAINTENANCE_FAILED"
                )
                if isinstance(exc, CoreError):
                    raise
                raise CoreError("MAINTENANCE_FAILED", "Không hoàn tất được bảo trì.", 503) from None
            self.maintenance.quiesced()
            return self.maintenance.status()

    def close(self, *, drain_timeout_seconds=10):
        timeout = drain_timeout(drain_timeout_seconds)
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
            self.maintenance.begin_close()
            try:
                self.maintenance.wait_for_drain(time.monotonic() + timeout, include_safe=True)
                self._close_resources()
            except BaseException as exc:
                self.maintenance.failed(
                    exc.code if isinstance(exc, CoreError) else "MAINTENANCE_CLOSE_FAILED"
                )
                raise
            self._closed = True
            self.maintenance.closed()

    def _close_resources(self):
        # Either join may fail closed. Do not tear down writer/DB/root while
        # a live callback or job still depends on them; close can be retried.
        if self.periodic:
            self.periodic.close()
        if self.runner and self.runner.thread.ident is not None:
            self.runner.close()
        if self.writer:
            self.writer.close()
        if self.database:
            self.database.close()
        if hasattr(self, "log_handler"):
            self.logger.removeHandler(self.log_handler)
            self.log_handler.close()
        self.root.release_lock()
