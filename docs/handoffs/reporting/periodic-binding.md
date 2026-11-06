# Reporting lifecycle timer binding

## Approved prerequisite and public registration

Root commit `e4f35947d086c6d892f03fe8b9a852c3cb9a28f5` was cherry-picked unchanged as
`8ed4f77`; its five shared files are the only shared changes for this increment.
Root already has the original commit and must skip this local duplicate.

`module_manifest()` now registers:

```python
periodic_tasks={
    "reporting.tick": PeriodicTask(lambda runtime: service(runtime).tick(), 60)
}
```

Core owns the thread, monotonic interval, startup and shutdown. First periodic
execution follows the 60-second interval. Existing startup recovery and the one
finite dispatch job remain; durable generation/sender locks handle concurrent
startup, explicit manual and periodic ticks. Reporting creates no runner/thread.
The actor-scoped source factory, server-derived scheduled Admin, reauthorization,
config pins, immutable snapshots and missed-day policy are unchanged.

`heartbeat_bound` remains an accepted compatibility keyword, but it grants no
status claim. `public_settings()` derives registration from the actual public
`Runtime.periodic.status()['runs']` entry for `reporting.tick`. It returns
`scheduler_mode=APP_RUNTIME` only when registered, otherwise MANUAL, plus:

- `scheduler_status.registered`, `state`, `running`, `active`;
- fixed `error_code`, `last_error_code`, reporting `task_error_code`;
- reporting task `runs` and `failures`.

NEW/STOPPED/FAILED do not claim the timer is running. A true legacy flag without
registration still reports UNBOUND/MANUAL. No exception message or raw payload is
added to settings. These status fields are read-only and never posted back as a
configuration command.

## UI and lifecycle

The screen no longer drives a minute heartbeat. The Admin status panel polls
read-only settings every 30 seconds and exposes an explicit request-check button;
it never calls this button's POST automatically. Polling is separate from the
configuration form, preserving unsaved fields and the version originally loaded
for optimistic conflict detection. Current and last sanitized timer error codes
are distinct, so a recovered run can retain its prior failure history.

Backend ticks do not depend on Reporting being mounted or a live user session.
They still require the configured account to remain active and authorized. A
background callback remains subject to the existing network timeout/UNKNOWN
policy and may delay the next timer callback if its finite work is slow.

Core signals/joins its timer before JobRunner/writer/DB shutdown. Its 10-second
close timeout fails closed with resources kept available. Reporting adds no
shortcut around that behavior. The native parent's bounded termination remains a
separate release concern; if it kills a send with no receipt, startup recovery
must preserve UNKNOWN rather than resend.

Machines asleep/off and a stopped backend cannot execute a schedule. Tray/native
window-close behavior, real providers and live Zalo remain separate acceptance
gates. This binding proves an open backend timer, not Windows service execution.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting/test_periodic_binding.py -q
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run typecheck
npm --prefix frontend run build
node tests/reporting/ui/check.mjs
```

Focused PASS: **4 cases, 66.34s**, on Windows / Python 3.12.16 / SQLite 3.53.1.
One case uses the actual production 60-second interval, no browser, a real blocked
JobRunner handler outside the writer, and real SQLite/FileStore TXT export. It
proves the capture runs on `cafe-fin-periodic`, saves one version and one
UNCONFIGURED outbox without credentials, closes cleanly and reopens without a
second capture. Other short lifecycle tests replace only the test manifest's
interval with one second while retaining the actual reporting callback.

The real child-process case blocks fake send_text after fsync of a synthetic side
effect on the periodic thread, then the parent kills the process before any
receipt. `Runtime.start()` recovery produces UNKNOWN and dispatch does not resend.
No real network/send is involved. Error tests prove a callback exception becomes
fixed PERIODIC_TASK_FAILED, following ticks continue, current error clears and
last error/failure count remain. An unregistered runtime cannot claim a timer.

PASS: 14 synthetic browser cases, including actual status fields/current and last
errors, explicit manual requests, and preservation of an unsaved configuration
draft. Settings screenshot was visually inspected; synthetic evidence stays in
`%TEMP%\cafe-fin-reporting-qa` outside Git. Frontend typecheck/build passed with
the existing Vite chunk-size warning.

Initial UI runs had intermittent exact accessible-name lookup timeouts around
busy button transitions, with no page JavaScript errors. Explicit stable ARIA
labels now cover the manual and existing busy buttons; the final harness passed
three consecutive runs. Failure diagnostics save a synthetic screenshot and
accessible button snapshots outside Git. Manual requests retain their request
key after ambiguous network failure; out-of-order status reads are discarded.

Full-suite PASS: **240 tests (78 reporting + 162 core), 158.46s**, no skips,
one baseline Starlette/httpx deprecation warning. Scoped Ruff check/format and
whitespace checks pass. No migration or dependency is added by this binding.
Reporting v2 from `151c666` still appends after unchanged v1; no schema from
another module is modified.
