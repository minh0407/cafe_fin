"""Trusted bootstrap. Native selection owns absolute paths; modules use service handles."""

from __future__ import annotations

import logging
import logging.handlers
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from sqlalchemy.engine import Connection

from . import auth, imports, jobs, storage
from .auth import AuthService
from .backup import BackupService
from .db import Database, WriteCoordinator
from .errors import CoreError
from .jobs import JobHandler, JobRunner, JobService
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
        self, path: Path | str, *, initialize: bool = False, modules: ModuleRegistry | None = None
    ):
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
            self.database = Database(self.root.database_path, create=initialize)
            if modules is None:
                from cafe_fin.registry import registered_modules

                modules = registered_modules()
            self.modules = modules
            migrations = auth.MIGRATIONS + jobs.MIGRATIONS + storage.MIGRATIONS + imports.MIGRATIONS
            migrations += tuple(m for module in self.modules.ordered() for m in module.migrations)
            self.database.migrate(migrations)
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
                    self.close()
                    raise

    def close(self):
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
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
            self._closed = True
