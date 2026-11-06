# Runtime maintenance phase 1

This increment implements in-process admission, dormant activation and terminal
quiescence. It does not prepare/copy a backup, move/restore files, persist a native
transition journal, switch machine configuration, add stdio commands or activate
restore quarantine hooks. It is not sufficient by itself for safe restore/sender
resumption. The native controller must persist its transition intent before any
quiesce call; phase 2 must bind operation/physical-root receipts and activation.

## Public interface

```python
runtime = Runtime(path, initialize=False, modules=registry, activation_mode="dormant")
runtime.maintenance.status()
runtime.activate(operation_id, access_token=current_target_admin_token)
runtime.quiesce(operation_id, access_token=current_admin_token, drain_timeout_seconds=10)
runtime.close(drain_timeout_seconds=10)
```

`activation_mode` is `active` by default, preserving ordinary app startup. Only
`active` and `dormant` are accepted. `create_app` continues calling `runtime.start`
in lifespan; dormant `start` intentionally does no recovery, module startup,
JobRunner start or PeriodicRunner start. Constructing a Runtime still validates
and migrates its database and opens core resources. Dormant does not mean a
read-only database constructor or an untrusted-file sandbox.

Maintenance operation IDs must be canonical lowercase UUID strings. They are not
permissions and are not interpreted by legacy `start`. Drain timeouts accept
finite numbers from 1 through 300 seconds, excluding bool. The quiesce deadline
covers admitted-business-request drain plus producer joins. Its final serialized
authorization fence runs only after those tracked producers/requests have ended.
The close timeout applies to all admitted HTTP requests; existing timer and job
close joins retain their separate original ten-second limits.

`maintenance.status()` returns only bounded core state: `state`, `operation_id`,
`requests`, `business_requests`, `error_code`. No token, actor details, file paths,
exception messages or filesystem operation results are exposed.

## States and admission

- `ACTIVE`: normal business HTTP admission. An ordinary Runtime starts as ACTIVE;
  dormant activation opens this state only after every startup step succeeds.
- `DORMANT`: no recovery/startup hooks/workers/timer. Only secured health, login
  and logout HTTP paths are admitted. Setup, user mutations, business reads,
  writes and preflights return `MAINTENANCE_REQUIRED` 503.
- `ACTIVATING`: still permits only those safe paths. Current target Admin is
  authenticated and serialized authorization runs before startup. Success opens
  ACTIVE. Repeating the same activation ID while ACTIVE reauthenticates and returns
  status without rerunning startup. A different activation ID conflicts.
- `QUIESCING`: business admission is held atomically with request lease acquisition.
  Both producers receive cooperative stop before any waits. Already admitted
  business requests may finish with the writer available.
- `QUIESCED`: business admission remains held and both producers have joined.
  A fresh final writer transaction reauthenticates/revalidates the captured Admin
  after any earlier admitted writes/revocation. Writer/DB/root remain open for
  later trusted maintenance work; there is no snapshot operation in this phase.
- `FAILED_HELD`: failure never reopens business admission. Activation errors have
  sanitized `MAINTENANCE_ACTIVATION_FAILED`; partial startup effects are retained,
  stop is requested on both producers and activation cannot rerun the hook.
  Drain/join/auth fence errors retain their fixed core code. Resources stay open
  until successful close; an activation attempt never silently falls back.
- `CLOSING`: all new HTTP requests, including health/login/logout, are denied
  before waiting for every admitted request. Only after drain and producer joins
  are writer/database/log/root resources closed. A failed close remains
  FAILED_HELD with all new HTTP admission still disabled; `close` can be retried.
- `CLOSED`: idempotent close, no new admission and root lease released.

Quiesce is terminal for this Runtime instance. `start` cannot restart stopped
Thread objects. A later quiesce with the same operation ID can finish after a
timeout or replay status after successful quiescence; it still requires current
authorization and a fresh fence. A different operation conflicts while held.
The completed activation ID may be replaced by a new quiesce ID after ACTIVE.
Reopening requires a new Runtime under the later controller's recovery rules.

## Request and producer lifetimes

ScopeGuard acquires one core admission lease before authentication or any request
DB access. Its lifetime covers body buffering/uploads, the whole ASGI call,
stream response completion/disconnect and resource cleanup. HTTP methods do not
change the admission policy. Native calls are trusted direct calls on another
control thread; maintenance/close must not be invoked from a handler that owns
the request lease it would need to drain.

The gate condition lock protects both closing business admission and acquiring
leases, eliminating a check-then-enter race. Quiesce drains business leases while
health/login/logout may continue; close drains all leases and blocks all new ones.
Safe routes keep their original app-session, Host/Origin and bearer requirements.
Health does not misclassify an intentionally stopped held worker as a failed
ACTIVE worker; its existing response DTO is unchanged.

JobRunner and PeriodicRunner expose `request_stop()` to signal without joining.
Their existing `close()` behavior remains the same. Quiesce signals both before
drain/join and never holds a writer barrier while a callback/request needs the
writer to finish. Producer joins share the remaining quiesce deadline. No database
backup is taken and no snapshot is copied while an open writer transaction exists.

All HTTP and existing core producer writes must stay within these tracked
lifetimes. This seam does not authorize arbitrary untracked module threads or
external writer use during maintenance. The trusted controller must serialize
its own direct operations. Phase 2 cannot release admission merely because
quiesce returned or treat an eight-second native kill as verified clean closure.

## Authentication and failure evidence

Both activate and quiesce authenticate the supplied current token and authorize
`core.manage` against the target Runtime database. Operator, missing/expired token
or already revoked Admin fails before changing admission. Activate performs a
serialized writer authorization fence before any startup effect. Quiesce captures
the current principal before holding admission, then reauthenticates and validates
that captured role/version in the final writer fence. Logout or account revocation
committed by an admitted request therefore prevents a success result.

An operation ID cannot select a database, path or arbitrary actor, and this API
does not create a login/session or transfer tokens across Runtime instances.
The new lifecycle methods are Python interfaces only; no new HTTP maintenance
endpoint or parent stdio command is installed in phase 1.

## Verification

PASS: **21 new focused cases in 16.14 seconds**. Combined regression PASS:
**91 cases in 67.38 seconds**, including all 21 new cases and existing periodic,
auth/jobs, job boundary, API/sidecar, file-transfer/disconnect, process recovery,
module registration and job-snapshot tests. Only the existing Starlette/httpx
deprecation warning remains. No reporting 60-second timer or full backend suite
was rerun for this scoped phase.

The new tests use actual FastAPI/TestClient and SQLite/WAL: an admitted writer
finishes while later requests are denied; an unfinished response stream keeps
its lease; admitted revocation defeats the final fence; timer/job and HTTP drain
timeouts retain writer/DB/root locks; dormant startup executes no hooks/jobs/timer
until a fresh Admin login activates; partial startup failure remains held without
rerunning; close waits for admitted health and retries after a drain timeout.
Events choose race boundaries; no network, reboot, policy or credential-value
operations are performed.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_runtime_maintenance.py tests/core/test_periodic.py tests/core/test_auth_jobs.py tests/core/test_review_auth_jobs_edges.py tests/core/test_api_job_boundaries.py tests/core/test_api_sidecar.py tests/core/test_file_transfer.py tests/core/test_api_recovery.py tests/core/test_module_registration.py tests/core/test_job_status_connection.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/runtime.py backend/cafe_fin/core/api.py backend/cafe_fin/core/maintenance.py backend/cafe_fin/core/periodic.py backend/cafe_fin/core/jobs.py tests/core/test_runtime_maintenance.py
```

Scoped Ruff lint/format and Git whitespace checks pass. Evidence is outside Git
in the session visualization directory as
`runtime-maintenance-phase1-20261107.xml` and `.txt`. No schema/migration, dependency,
package, native, registry, hook, UI or filesystem-controller changes are included.
