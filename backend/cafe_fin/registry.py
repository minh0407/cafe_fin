"""Coordinator-owned registration point. Lanes deliver manifests without editing core."""

from cafe_fin.core.example import module_manifest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.records.module import module_manifest as records_manifest


def registered_modules() -> ModuleRegistry:
    return ModuleRegistry((module_manifest(), records_manifest()))
