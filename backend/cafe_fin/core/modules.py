"""Module registration is explicit; discovery never executes arbitrary disk plugins."""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import Connection

from .errors import CoreError


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
