"""Immutable contracts migration history, registered by the module manifest."""

from .v001 import MIGRATIONS as V001
from .v002 import MIGRATIONS as V002

MIGRATIONS = V001 + V002

__all__ = ["MIGRATIONS"]
