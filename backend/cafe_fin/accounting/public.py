"""Supported read integration. No consumer needs accounting ORM/schema internals.

Within caller-owned `runtime.reader() as conn`, explicitly BEGIN a read transaction
before first source read. Construct AccountingReadProvider(runtime, principal,
connection=conn), then call book_summary with the capture cutoff. Provider neither
opens another connection nor commits/rolls back/closes the supplied connection.
SQLite pins the snapshot at the first read; reporting must use this same connection
for its records provider and freeze the returned DTOs in its own snapshot artifact.
"""

from .service import AccountingReadProvider

__all__ = ["AccountingReadProvider"]
