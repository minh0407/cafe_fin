# Generic file/job read scopes

Core generic file GET routes now require current `files.read` plus file ownership
or an active Admin role. Possessing a file UUID or a module read permission does
not share another actor's file. Ownership comes from exactly one
`core_audit(entity='core_file', action='CREATE', entity_id=file_id)` record.
Missing/ambiguous provenance fails closed for Admin as well as Operator. Existing
schema, migrations and source bytes are unchanged.

Public module ingress helper:

```python
with runtime.reader() as conn:
    conn.exec_driver_sql("BEGIN")
    current = runtime.auth.authorize(conn, principal, "accounting.write")
    runtime.files.require_owner_or_admin(conn, current, source_file_id)
    original = runtime.files.get(source_file_id, connection=conn)
```

For a mutation, run the authorization and helper on the writer connection in the
same transaction as the saved domain reference. The helper returns `None` and
only checks existing file provenance/ownership; it does not authenticate, check
session revocation, check module/book/contract permission, or grant shared access.
Callers must revalidate auth on the same connection before calling it. IDs must
be canonical lowercase hyphenated UUID strings; uppercase, braces and compact
aliases fail with `FILE_ID_INVALID` rather than use mismatched lookup identities.

Generic metadata uses one explicit readonly snapshot for current authorization,
ownership and metadata. Downloads check before opening, verify original bytes,
then recheck current authorization/provenance in a fresh readonly snapshot before
HTTP headers. A revocation during hashing closes the source and returns an error;
no DB read transaction is held while hashing/streaming a large original. A response
already started is not interrupted by a later account change.

An explicitly authorized module download may use trusted `FileStore.read` after
checking its own saved domain reference and permission. Core generic endpoints do
not infer that domain authorization from a supplied file ID. Module routes must
validate incoming references with this helper and their own domain rules.

Generic non-foundation job status additionally requires current module read
permission and `job.actor == principal.id` or Admin. It revalidates current auth
in an explicit readonly snapshot. Generic module job mutation stays blocked by
the existing module-endpoint boundary. The small `foundation.sample` registration
proof retains its existing generic behavior, including without registered modules.

## Validation

PASS: 42 focused regressions in 38.42 seconds, including 12 new scope cases:

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_read_scopes.py tests/core/test_storage.py tests/core/test_api_job_boundaries.py tests/core/test_file_transfer.py tests/core/test_api_recovery.py tests/core/test_api_sidecar.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/storage.py backend/cafe_fin/core/api.py tests/core/test_read_scopes.py
```

The cases cover owner/Admin metadata and original hash, another Operator denied
before opening, missing/duplicate CREATE provenance, UUID aliases, direct helper
use after auth on the same connection, real revocation after request capture and
during file verification, private accounting-prefixed job status despite baseline
`accounting.read`, and unchanged foundation proof behavior without modules.
Existing real sidecar upload/download, export recovery, corruption and module job
boundaries also pass. Ruff and scoped Git whitespace checks pass. One existing
Starlette/httpx deprecation warning remains.

All fixtures are synthetic; tests use real local users, SQLite, file bytes and
HTTP handlers. Deterministic revocation hooks only choose race timing; they still
perform genuine authenticated account changes. The accounting-prefixed handler
is a registered synthetic core-job fixture; these tests do not claim that a
production accounting closed-book ACL or a contracts shared-download route has
been integrated. Those module routes must apply their own authorization rules.
Native installer/clean-client tests were not rerun for this API/service change.
