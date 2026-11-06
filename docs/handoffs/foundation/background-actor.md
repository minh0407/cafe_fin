# Trusted background actor resolution

`AuthService.resolve_actor(conn, actor_id, permission) -> Principal` reads the
current user row on the supplied connection. Missing, disabled or unsupported-role
users fail closed with sanitized `BACKGROUND_ACTOR_UNAVAILABLE` (403). Current
permissions are checked; an active Operator cannot resolve an Admin-only action.
The returned principal carries the current role and version. No token, login,
session, audit or user row is created by resolution; no schema/migration changes.

This is a trusted local-job/scheduler primitive. The actor ID must come from an
already authorized persisted job or an Admin-configured schedule. It is not
authentication for an actor ID in a client command/header, and must never let a
client choose an arbitrary Admin. The caller must still authorize the saved job,
schedule and domain scope. Do not bind a global Admin or create batch API logins.

```python
with runtime.reader() as conn:
    conn.exec_driver_sql("BEGIN")
    actor = runtime.auth.resolve_actor(conn, trusted_schedule.actor_id, "reporting.read")
    # Capture authorized local source DTOs in this short snapshot.

def publish(conn):
    runtime.auth.authorize(conn, actor, "reporting.write")
    return publish_captured_report(conn)

context.finalize(publish)
```

Every writer chunk/finalization must call `authorize(conn, captured_actor, ...)`
inside its transaction before domain effects; `JobContext` itself only fences the
job lease/cancellation. A role, active-state or version change after capture makes
the captured principal stale and aborts the transaction. Do not re-resolve inside
the same in-flight attempt to conceal that change. Recover/retry according to the
module's authorized job policy and capture a new principal/snapshot explicitly.

An intentional new resolution uses the current permitted account even after a
password/version change; it does not verify an interactive password. A password
change does not itself disable a configured schedule identity. Disable/revoke the
user or schedule to stop future resolutions. Interactive logout invalidates its
token; an already authorized persisted local schedule may still resolve the active
identity without creating a replacement session. Resolution observes the supplied
SQLite snapshot; keep captures short, then revalidate on each writer transaction.

## Validation

PASS: 23 focused regressions in 11.64 seconds, including 13 new background-actor
cases. Scoped Ruff check/format and Git whitespace checks pass.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_background_actor.py tests/core/test_auth_jobs.py tests/core/test_review_auth_jobs_edges.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/auth.py tests/core/test_background_actor.py
```

Checks include active Admin/Operator permissions, unknown/disabled identity,
demotion, unchanged persistent state/sessions, logout, password/version rotation,
reading uncommitted account changes on the supplied connection, and real job
chunk/finalization rollback of effects, audit, receipts and progress after each
active/role/version change. Fixtures use real local users, Argon2 credentials,
SQLite writer/job transactions and synthetic data. The credential-rotation fixture
models a trusted future operation; this change adds no password-reset or scheduler
API. Full module scheduler capture and native installer acceptance were not run
for this small service primitive.
