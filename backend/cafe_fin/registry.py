"""Coordinator-owned registration point. Lanes deliver manifests without editing core."""

from cafe_fin.core.example import module_manifest
from cafe_fin.core.modules import ModuleRegistry


def registered_modules() -> ModuleRegistry:
    return ModuleRegistry((module_manifest(),))
