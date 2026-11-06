# Job status in a caller-owned snapshot

`JobService.status(job_id, *, connection=None)` keeps the existing public DTO,
formatter and `JOB_NOT_FOUND` 404 behavior. Omitting `connection` still opens a
fresh core reader. The formatter remains private.

Trusted module code may pass its own `runtime.reader()` connection after explicit
`BEGIN`. It must belong to this JobService's database engine, remain open and
valid, have an active SQLAlchemy transaction and physical SQLite transaction, and
have `PRAGMA query_only=ON`. Invalid connections fail with sanitized
`READ_ONLY_SNAPSHOT_REQUIRED` 409 before querying jobs. A different engine is
rejected even if it points to the same path; engine identity is supplied by core,
never selected from HTTP input.

```python
with runtime.reader() as conn:
    conn.exec_driver_sql("BEGIN")
    runtime.auth.authorize(conn, principal, "accounting.read")
    # Validate the requested domain resource and its ownership in this same conn.
    status = runtime.jobs.status(job_id, connection=conn)
    # Combine only authorized domain data and status from this same snapshot.
```

This helper grants no permission or ownership. Callers must freshly authorize the
captured principal and enforce domain/job ownership with the same connection.
No token, actor, path or database is accepted as an alternative authority. The
caller owns snapshot boundaries and connection lifetime; this method does not
begin, commit, roll back or close a supplied connection. Status is read at each
call from the supplied snapshot; retaining a previous DTO across transactions
does not revalidate authorization. Writer operations must still revalidate in
their current writer transaction.

The focused tests use actual SQLite WAL connections: a second writer cancels a
job between two borrowed reads; both borrowed reads retain the old DTO while a
fresh reader sees cancellation. Tests also verify exact unchanged DTO fields,
connection/transaction lifetime, missing-job 404 and rejection of implicit,
SQLAlchemy-only, closed, invalidated, write-enabled and foreign connections.

Validation PASS: **21 focused cases in 8.02 seconds**, including eight new
connection/snapshot cases and existing auth/job/API boundary regressions. The
existing Starlette/httpx deprecation warning remains. Scoped Ruff lint, format
check and Git whitespace check pass.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_job_status_connection.py tests/core/test_auth_jobs.py tests/core/test_review_auth_jobs_edges.py tests/core/test_api_job_boundaries.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/jobs.py tests/core/test_job_status_connection.py
.venv/Scripts/python.exe -m ruff format --check backend/cafe_fin/core/jobs.py tests/core/test_job_status_connection.py
```

No schema, migration, module authorization policy or DTO field changes. This
additive core seam does not itself integrate an accounting export endpoint; its
owner must use the same authorized domain snapshot and run the export regression.
