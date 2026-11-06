"""Module registration is explicit; discovery never executes arbitrary disk plugins."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable

from sqlalchemy import Connection, MetaData
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from .errors import CoreError

if TYPE_CHECKING:
    from .jobs import JobHandler
    from .periodic import PeriodicTask
    from .runtime import Runtime


def schema_checksum(metadata: MetaData, statements: Iterable[str] = ()) -> str:
    """Fingerprint deterministic SQLite DDL, including indexes and declared triggers.

    Data-only/ALTER migrations must also pass their exact ordered SQL statements here.
    No runtime source introspection is needed, so signatures work in frozen sidecars.
    """
    dialect = sqlite.dialect()
    ddl: list[str] = []
    for table in sorted(metadata.tables.values(), key=lambda item: item.fullname):
        ddl.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        ddl.extend(
            sorted(
                str(CreateIndex(index).compile(dialect=dialect)).strip() for index in table.indexes
            )
        )
    ddl.extend(statement.replace("\r\n", "\n").strip() for statement in statements)
    encoded = json.dumps(ddl, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Migration:
    namespace: str
    version: int
    name: str
    apply: Callable[[Connection], None]
    checksum: str = ""

    @property
    def fingerprint(self) -> str:
        return (
            self.checksum
            or hashlib.sha256(f"{self.namespace}:{self.version}:{self.name}".encode()).hexdigest()
        )


@dataclass(frozen=True)
class ModuleManifest:
    id: str
    api_prefix: str
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    migrations: tuple[Migration, ...] = ()
    router: object | None = field(default=None, compare=False)
    job_handlers: Mapping[str, JobHandler] = field(default_factory=dict, compare=False)
    on_startup: Callable[[Runtime], None] | None = field(default=None, compare=False)
    periodic_tasks: Mapping[str, PeriodicTask] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        # Registration is a frozen handoff, not a live plugin dictionary.
        object.__setattr__(self, "job_handlers", MappingProxyType(dict(self.job_handlers)))
        if not isinstance(self.periodic_tasks, Mapping):
            raise CoreError("INVALID_PERIODIC_TASK", "Timer module phải là mapping.")
        object.__setattr__(self, "periodic_tasks", MappingProxyType(dict(self.periodic_tasks)))


class ModuleRegistry:
    def __init__(self, modules: tuple[ModuleManifest, ...] = ()):
        self._modules: dict[str, ModuleManifest] = {}
        for module in modules:
            self.register(module)

    def register(self, module: ModuleManifest) -> None:
        from .jobs import JobHandler
        from .periodic import MAX_MODULE_TASKS, MAX_RUNTIME_TASKS, PeriodicTask

        if not re.fullmatch(r"[a-z][a-z0-9_]*", module.id) or module.id in self._modules:
            raise CoreError("INVALID_MODULE", "Module trùng hoặc tên không hợp lệ.")
        if module.api_prefix != f"/{module.id}":
            raise CoreError("INVALID_MODULE", "API prefix không thuộc module.")
        if any(m.namespace != module.id for m in module.migrations):
            raise CoreError("INVALID_MIGRATION", "Migration phải thuộc namespace module.")
        if any(not re.fullmatch(r"[0-9a-f]{64}", m.checksum) for m in module.migrations):
            raise CoreError(
                "MIGRATION_CHECKSUM_REQUIRED",
                "Migration module phải khai báo checksum schema/SQL hợp lệ.",
            )
        if module.on_startup is not None and not callable(module.on_startup):
            raise CoreError("INVALID_MODULE_HOOK", "Startup hook của module phải là callable.")
        if (
            len(module.periodic_tasks) > MAX_MODULE_TASKS
            or len(module.periodic_tasks)
            + sum(len(registered.periodic_tasks) for registered in self._modules.values())
            > MAX_RUNTIME_TASKS
        ):
            raise CoreError("PERIODIC_TASK_LIMIT", "Vượt giới hạn timer module hoặc ứng dụng.")
        for name, task in module.periodic_tasks.items():
            if (
                not isinstance(name, str)
                or len(name) > 128
                or not name.startswith(module.id + ".")
                or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", name)
            ):
                raise CoreError("INVALID_PERIODIC_NAMESPACE", "Tên timer phải thuộc module.")
            if not isinstance(task, PeriodicTask):
                raise CoreError("INVALID_PERIODIC_TASK", "Timer module không hợp lệ.")
        existing_jobs = {
            kind for registered in self._modules.values() for kind in registered.job_handlers
        }
        for kind, handler in module.job_handlers.items():
            prefix = module.id + "."
            if not isinstance(kind, str) or not kind.startswith(prefix) or len(kind) == len(prefix):
                raise CoreError("INVALID_JOB_NAMESPACE", "Loại job phải có prefix của module.")
            if kind in existing_jobs:
                raise CoreError("DUPLICATE_JOB_KIND", "Loại job đã được đăng ký.")
            if not isinstance(handler, JobHandler) or not callable(handler.run):
                raise CoreError("INVALID_JOB_HANDLER", "Job handler của module không hợp lệ.")
        self._modules[module.id] = module

    def ordered(self) -> tuple[ModuleManifest, ...]:
        done, visiting, result = set(), set(), []

        def visit(name: str):
            if name in visiting or name not in self._modules:
                raise CoreError("MODULE_DEPENDENCY", "Thiếu module hoặc có vòng phụ thuộc.")
            if name in done:
                return
            visiting.add(name)
            module = self._modules[name]
            for dependency in module.dependencies:
                visit(dependency)
            visiting.remove(name)
            done.add(name)
            result.append(module)

        for name in self._modules:
            visit(name)
        return tuple(result)
