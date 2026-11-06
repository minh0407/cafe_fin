"""Schema/index compatibility and bounded duplicate metadata regressions.

Prepared during the benchmark freeze; do not execute until the benchmark slot is
released. Only synthetic local databases/files are created by these tests.
"""

import csv
import io
import time
from uuid import uuid4

import pytest
from cafe_fin.accounting import schema as s
from cafe_fin.accounting.duplicate_compatibility import historical_shapes
from cafe_fin.accounting.module import module_manifest
from cafe_fin.accounting.service import AccountingService
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from sqlalchemy import event, select


def key():
    return str(uuid4())


@pytest.fixture
def account(tmp_path):
    runtime = Runtime(
        tmp_path / "schema-duplicate-edges",
        initialize=True,
        modules=ModuleRegistry((module_manifest(),)),
    )
    session = runtime.auth.setup("schema-admin", "synthetic-schema-password")
    actor = runtime.auth.authenticate(session["access_token"])
    runtime.start()
    try:
        yield runtime, actor, AccountingService(runtime)
    finally:
        runtime.close()


def book(account, semantics=None, *, old_nullable=False):
    _, actor, service = account
    columns = [
        {"id": "code", "name": "Code", "kind": "text", "required": True},
        {"id": "day", "name": "Day", "kind": "date", "required": True},
        {"id": "amount", "name": "Amount", "kind": "money", "required": True},
    ]
    if old_nullable:
        columns.append({"id": "old_optional", "name": "Existing nullable", "kind": "text"})
    return service.create_book(actor, "Schema duplicate test", columns, semantics or {}, key())


def published_row(account, created):
    _, actor, service = account
    return service.create_row(
        actor, created["id"], {"code": "000001", "day": "2026-02-01", "amount": "10.25"}, key()
    )


def wait(account, batch_id):
    _, actor, service = account
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        imported = service.get_batch(actor, batch_id)
        state = imported["job"]["state"]
        if state == "COMPLETED" and imported["state"] in {
            "UPLOADED",
            "PARSING",
            "VALIDATING",
            "COMMITTING",
        }:
            time.sleep(0.01)
            continue
        if state in {"COMPLETED", "FAILED", "RECOVERABLE", "CANCELLED"}:
            assert state == "COMPLETED", imported.get("error_code")
            return imported
        time.sleep(0.01)
    pytest.fail("schema duplicate job deadline exceeded")


def ready(account, created, rows):
    runtime, actor, service = account
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([column["name"] for column in created["columns"]])
    for row in rows:
        writer.writerow([row.get(column["id"]) for column in created["columns"]])
    stored = runtime.files.put(
        io.BytesIO(output.getvalue().encode()),
        category="workbooks",
        original_name="synthetic-schema.csv",
        actor=actor.id,
        request_key=key(),
        authorize=service.authorize(actor),
    )
    imported = service.create_batch(actor, created["id"], stored.id, {}, key())
    imported = wait(account, imported["id"])
    mapping = {column["id"]: chr(65 + index) for index, column in enumerate(created["columns"])}
    imported = service.mapping(actor, imported["id"], imported["version"], mapping, {}, key())
    service.validate(actor, imported["id"], imported["version"], key())
    return wait(account, imported["id"])


def confirm(account, imported):
    _, actor, service = account
    service.confirm(
        actor,
        imported["id"],
        {
            "expected_version": imported["version"],
            "staging_revision": imported["revision"],
            "mapping_revision": imported["mapping_revision"],
            "decision_revision": imported["decision_revision"],
            "validation_token": imported["validation_token"],
            "mode": "valid_rows_only",
            "request_key": key(),
        },
    )
    return wait(account, imported["id"])


@pytest.mark.parametrize("business_key", [False, True])
@pytest.mark.parametrize("old_nullable", [False, True])
def test_adding_nullable_column_preserves_existing_duplicate_identity(
    account, business_key, old_nullable
):
    _, actor, service = account
    created = book(
        account,
        {"business_key_columns": ["code"]} if business_key else {},
        old_nullable=old_nullable,
    )
    original = published_row(account, created)
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        created["semantics"],
        key(),
    )
    imported = ready(
        account,
        revised,
        [{"code": "000001", "day": "2026-02-01", "amount": "10.250", "new_optional": ""}],
    )
    assert imported["counts"]["valid"] == 1
    assert imported["counts"]["conflicts"] == 0
    assert imported["counts"]["potential_duplicates"] == 1
    assert imported["counts"]["eligible"] == 0
    staged = service.staging_page(actor, imported["id"])["items"][0]
    assert staged["typed_values"]["new_optional"] is None
    assert staged["duplicate_count"] >= 1
    # Original identity/value payload stays intact when only the schema expands.
    existing = service.list_rows(actor, created["id"])["items"][0]
    assert existing["id"] == original["id"]
    assert existing["values"]["amount"] == "10.25"
    if business_key:
        # Validation success alone is insufficient: the final live conflict
        # recheck must also understand historical missing == current nullable.
        imported = service.decisions(actor, imported["id"], imported["version"], [], "keep", key())
        confirm(account, imported)
        assert service.list_rows(actor, created["id"])["total"] == 2


@pytest.mark.parametrize("action", ["create", "mutate", "restore"])
def test_equivalent_crud_payload_does_not_false_conflict_after_nullable_expansion(account, action):
    _, actor, service = account
    created = book(account, {"business_key_columns": ["code"]}, old_nullable=True)
    original = published_row(account, created)
    if action == "mutate":
        published_row(account, created)
    if action == "restore":
        original = service.mutate_row(
            actor, original["id"], original["version"], key(), action="delete"
        )
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        created["semantics"],
        key(),
    )
    equivalent = {"code": "000001", "day": "2026-02-01", "amount": "10.250", "new_optional": ""}
    if action == "create":
        changed = service.create_row(actor, revised["id"], equivalent, key())
    elif action == "mutate":
        changed = service.mutate_row(
            actor,
            original["id"],
            original["version"],
            key(),
            values={"amount": "10.250", "new_optional": ""},
        )
    else:
        # Old deleted payload vs a live row first created under the new schema.
        service.create_row(actor, revised["id"], equivalent, key())
        changed = service.mutate_row(
            actor, original["id"], original["version"], key(), action="restore"
        )
    assert changed["deleted_at"] is None
    assert changed["values"]["amount"] == "10.25"
    assert changed["values"].get("new_optional") is None
    assert service.list_rows(actor, created["id"])["total"] == 2


@pytest.mark.parametrize("action", ["create", "mutate", "restore", "import"])
def test_meaningful_nonblank_new_value_stays_business_key_conflict(account, action):
    _, actor, service = account
    created = book(account, {"business_key_columns": ["code"]}, old_nullable=True)
    original = published_row(account, created)
    if action == "mutate":
        published_row(account, created)
    if action == "restore":
        original = service.mutate_row(
            actor, original["id"], original["version"], key(), action="delete"
        )
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        created["semantics"],
        key(),
    )
    different = {
        "code": "000001",
        "day": "2026-02-01",
        "amount": "10.25",
        "new_optional": "meaningful new information",
    }
    if action == "import":
        imported = ready(account, revised, [different])
        assert imported["counts"]["conflicts"] == 1
        assert imported["counts"]["valid"] == 0
        imported = service.decisions(actor, imported["id"], imported["version"], [], "keep", key())
        with pytest.raises(CoreError) as error:
            confirm(account, imported)
        assert error.value.code == "NO_ELIGIBLE_ROWS"
        return
    if action == "restore":
        service.create_row(actor, revised["id"], different, key())
    with pytest.raises(CoreError) as error:
        if action == "create":
            service.create_row(actor, revised["id"], different, key())
        elif action == "mutate":
            service.mutate_row(
                actor,
                original["id"],
                original["version"],
                key(),
                values={"new_optional": different["new_optional"]},
            )
        else:
            service.mutate_row(actor, original["id"], original["version"], key(), action="restore")
    assert error.value.code == "BUSINESS_KEY_CONFLICT"


def test_new_nullable_column_with_a_value_changes_full_row_identity(account):
    _, actor, service = account
    created = book(account)
    published_row(account, created)
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        {},
        key(),
    )
    imported = ready(
        account,
        revised,
        [
            {
                "code": "000001",
                "day": "2026-02-01",
                "amount": "10.25",
                "new_optional": "new information",
            }
        ],
    )
    assert imported["counts"]["valid"] == 1
    assert imported["counts"]["potential_duplicates"] == 0
    assert imported["counts"]["eligible"] == 1


@pytest.mark.parametrize("rule", ["duplicate_columns", "business_key_columns"])
@pytest.mark.parametrize(
    "before,after",
    [([], ["code"]), (["code"], ["day"]), (["code"], []), (["code", "day"], ["day", "code"])],
)
def test_changed_duplicate_rules_require_explicit_reindex_or_rejection(
    account, rule, before, after
):
    runtime, actor, service = account
    created = book(account, {rule: before})
    published_row(account, created)
    # No reindex-job API currently exists. The minimal safe contract is an
    # explicit 409 while leaving schema/index rule revisions unchanged.
    with pytest.raises(CoreError) as error:
        service.update_schema(
            actor, created["id"], created["version"], created["columns"], {rule: after}, key()
        )
    assert error.value.status == 409
    assert error.value.code in {
        "SCHEMA_DATA_INCOMPATIBLE",
        "SCHEMA_DUPLICATE_RULES_LOCKED",
        "DUPLICATE_REINDEX_REQUIRED",
    }
    with runtime.reader() as connection:
        stored = (
            connection.execute(select(s.books).where(s.books.c.id == created["id"]))
            .mappings()
            .one()
        )
    assert stored["schema_revision"] == created["schema_revision"]
    assert stored["version"] == created["version"]
    assert service.get_books(actor)["items"][0]["semantics"].get(rule, []) == before


@pytest.mark.parametrize("rule", ["duplicate_columns", "business_key_columns"])
def test_unchanged_duplicate_rules_allow_display_rename_after_data(account, rule):
    _, actor, service = account
    created = book(account, {rule: ["code"]})
    published_row(account, created)
    columns = [dict(column, name=column["name"] + " renamed") for column in created["columns"]]
    revised = service.update_schema(
        actor, created["id"], created["version"], columns, created["semantics"], key()
    )
    assert revised["schema_revision"] == created["schema_revision"] + 1
    assert revised["semantics"][rule] == ["code"]


def test_empty_book_can_configure_duplicate_rules_without_reindex(account):
    _, actor, service = account
    created = book(account)
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"],
        {"duplicate_columns": ["code", "day"], "business_key_columns": ["code"]},
        key(),
    )
    assert revised["semantics"]["business_key_columns"] == ["code"]
    assert revised["semantics"]["duplicate_columns"] == ["code", "day"]


class CountedCursor:
    """Count materialized pair metadata without changing SQL/results/row values."""

    def __init__(self, cursor, observation):
        self.cursor, self.observation = cursor, observation

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def fetchone(self):
        row = self.cursor.fetchone()
        self.observation["rows"] += row is not None
        return row

    def fetchmany(self, *args, **kwargs):
        rows = self.cursor.fetchmany(*args, **kwargs)
        self.observation["rows"] += len(rows)
        return rows

    def fetchall(self):
        rows = self.cursor.fetchall()
        self.observation["rows"] += len(rows)
        return rows


def test_constant_business_key_does_not_materialize_all_file_fingerprints_per_chunk(account):
    runtime, _, _ = account
    created = book(account, {"business_key_columns": ["code"]})
    observations = []

    def inspect_pair_results(connection, cursor, statement, parameters, context, executemany):
        if not cursor.description:
            return
        names = [field[0] for field in cursor.description]
        if len(names) <= 4 and "business_key" in names and "fingerprint" in names:
            observation = {"rows": 0}
            observations.append(observation)
            context.cursor = CountedCursor(cursor, observation)

    event.listen(runtime.database.engine, "after_cursor_execute", inspect_pair_results)
    try:
        imported = ready(
            account,
            created,
            [
                {"code": "constant", "day": "2026-02-01", "amount": f"{index}.25"}
                for index in range(1, 1202)
            ],
        )
    finally:
        event.remove(runtime.database.engine, "after_cursor_execute", inspect_pair_results)
    assert imported["counts"]["conflicts"] == 1201
    # At most 500 source rows are normalized/deduplicated in one operational
    # chunk. Exact-pair result metadata must be bounded to those selected pairs;
    # a SQL-only EXISTS implementation returning no pair rows is also acceptable.
    assert max((observation["rows"] for observation in observations), default=0) <= 500


def test_unused_predata_subset_schemas_are_omitted_from_historical_shapes(account):
    runtime, actor, service = account
    created = book(account)
    full_columns = created["columns"]
    # Legal configuration changes before any row exists create unused subset
    # histories. They must not become duplicate queries for later real data.
    for columns in (full_columns[:1], full_columns[:2], full_columns):
        created = service.update_schema(
            actor, created["id"], created["version"], columns, {}, key()
        )
    published_row(account, created)
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        {},
        key(),
    )
    with runtime.reader() as connection:
        stored_book = (
            connection.execute(select(s.books).where(s.books.c.id == revised["id"]))
            .mappings()
            .one()
        )
        shapes = historical_shapes(connection, stored_book)
    assert len(shapes) == 1
    columns, added = shapes[0]
    assert set(columns) == {"code", "day", "amount"}
    assert added == {"new_optional"}
    imported = ready(account, revised, [{"code": "000001", "day": "2026-02-01", "amount": "10.25"}])
    assert imported["counts"]["potential_duplicates"] == 1
    assert imported["counts"]["valid"] == 1


def test_many_active_display_revisions_collapse_to_one_nullable_shape_with_bounded_binds(account):
    runtime, actor, service = account
    created = book(account)
    published_row(account, created)
    for index in range(32):
        renamed = [
            dict(column, name=f"Display {index} {column['id']}") for column in created["columns"]
        ]
        created = service.update_schema(
            actor, created["id"], created["version"], renamed, {}, key()
        )
        service.create_row(
            actor,
            created["id"],
            {"code": f"{index + 2:06d}", "day": "2026-02-01", "amount": "10.25"},
            key(),
        )
    revised = service.update_schema(
        actor,
        created["id"],
        created["version"],
        created["columns"] + [{"id": "new_optional", "name": "New nullable", "kind": "text"}],
        {},
        key(),
    )
    with runtime.reader() as connection:
        active_revisions = (
            connection.execute(select(s.entries.c.schema_revision).distinct()).scalars().all()
        )
        stored_book = (
            connection.execute(select(s.books).where(s.books.c.id == revised["id"]))
            .mappings()
            .one()
        )
        shapes = historical_shapes(connection, stored_book)
    assert len(active_revisions) == 33
    assert len(shapes) == 1
    columns, added = shapes[0]
    assert set(columns) == {"code", "day", "amount"}
    assert added == {"new_optional"}
    bind_counts = []

    def observe_count_query(connection, cursor, statement, parameters, context, executemany):
        sql = statement.lower()
        if (
            sql.lstrip().startswith("select")
            and "accounting_entries.fingerprint" in sql
            and "count(" in sql
        ):
            bind_counts.append(len(parameters))

    event.listen(runtime.database.engine, "before_cursor_execute", observe_count_query)
    try:
        imported = ready(
            account, revised, [{"code": "000001", "day": "2026-02-01", "amount": "10.25"}]
        )
    finally:
        event.remove(runtime.database.engine, "before_cursor_execute", observe_count_query)
    assert imported["counts"]["potential_duplicates"] == 1
    assert bind_counts
    assert max(bind_counts) <= 10  # No per-display-revision IN-list expansion.
