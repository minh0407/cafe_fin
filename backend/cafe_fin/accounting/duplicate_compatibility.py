"""Indexed duplicate compatibility across additive nullable schema revisions.

Fingerprint v1 remains unchanged. Historical rows keep their original values,
fingerprints and schema revision; a missing later nullable field equals null.
"""

import json
from collections import defaultdict

from sqlalchemy import and_, func, select, true

from cafe_fin.core.imports import visibility_predicate

from . import schema as s
from .validation import fingerprint


def historical_shapes(conn, book):
    """Group revisions by column IDs, so display-only revisions share one query."""
    if book["schema_revision"] <= 1:
        return []
    current = frozenset(c["id"] for c in json.loads(book["columns_json"]))
    shapes = set()
    for (columns_json,) in conn.execute(
        select(s.schemas.c.columns_json).where(
            s.schemas.c.book_id == book["id"],
            s.schemas.c.revision < book["schema_revision"],
            s.schemas.c.revision.in_(
                select(s.entries.c.schema_revision).where(
                    s.entries.c.book_id == book["id"],
                    s.entries.c.deleted_at.is_(None),
                    visibility_predicate(s.entries.c.import_attempt_id),
                )
            ),
        )
    ):
        columns = frozenset(c["id"] for c in json.loads(columns_json))
        if columns < current:
            shapes.add(columns)
    return [(tuple(sorted(columns)), current - columns) for columns in shapes]


def projected_fingerprints(typed, shapes):
    for columns, added in shapes:
        if all(typed.get(column) is None for column in added):
            yield fingerprint(typed, columns)


def historical_counts(conn, book_id, rows, shapes, visibility):
    """Return at most one count per input fingerprint, with bounded SQL groups."""
    counts = defaultdict(int)
    if not shapes:
        return counts
    typed_rows = [(row.fingerprint, json.loads(row.typed_json)) for row in rows]
    for columns, added in shapes:
        projected = {}
        for current_fp, typed in typed_rows:
            if all(typed.get(column) is None for column in added):
                projected[fingerprint(typed, columns)] = current_fp
        if not projected:
            continue
        for old_fp, count in conn.execute(
            select(s.entries.c.fingerprint, func.count())
            .where(
                s.entries.c.book_id == book_id,
                s.entries.c.fingerprint.in_(tuple(projected)),
                s.entries.c.deleted_at.is_(None),
                visibility,
            )
            .group_by(s.entries.c.fingerprint)
        ):
            counts[projected[old_fp]] += count
    return counts


def same_values(left_json, right_json, columns):
    """SQLite IS compares normalized text/null exactly; no numeric casts/REAL."""
    return and_(
        true(),
        *(
            func.json_extract(left_json, "$." + json.dumps(column["id"])).is_(
                func.json_extract(right_json, "$." + json.dumps(column["id"]))
            )
            for column in columns
        ),
    )
