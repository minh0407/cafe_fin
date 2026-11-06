"""Module registration is explicit; discovery never executes arbitrary disk plugins."""

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import Connection, MetaData
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from .errors import CoreError


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


class ModuleRegistry:
    def __init__(self, modules: tuple[ModuleManifest, ...] = ()):
        self._modules: dict[str, ModuleManifest] = {}
        for module in modules:
            self.register(module)

    def register(self, module: ModuleManifest) -> None:
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
