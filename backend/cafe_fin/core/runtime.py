"""Trusted bootstrap. Native selection owns absolute paths; modules use service handles."""

import logging
import logging.handlers
import threading
from pathlib import Path

from . import auth, imports, jobs, storage
from .auth import AuthService
from .backup import BackupService
from .db import Database, WriteCoordinator
from .jobs import JobHandler, JobRunner, JobService
from .modules import ModuleRegistry
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
        self.database = self.writer = self.runner = None
        self._closed = False
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
            self.writer = WriteCoordinator(self.database)
            self.auth = AuthService(self.database, self.writer)
            self.files = FileStore(self.root, self.database, self.writer)
            self.workbook_spike = WorkbookSpike(self.files)
            self.backups = BackupService(self.root, self.database, self.writer)
            self.render_lock = threading.Lock()
            self.jobs = JobService(
                self.database,
                self.writer,
                {"foundation.sample": JobHandler(sample_job, resumable=True)},
            )
            self.runner = JobRunner(self.jobs)
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
            if self.writer:
                self.writer.close()
            if self.database:
                self.database.close()
            self.root.release_lock()
            raise

    def start(self):
        if not self._started:
            self.runner.start()
            self._started = True

    def close(self):
        if self._closed:
            return
        if self.runner and self._started:
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
