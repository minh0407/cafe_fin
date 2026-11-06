# Core-owned periodic callbacks

Modules declare trusted callbacks without accessing a private registry closure:

```python
from cafe_fin.core.periodic import PeriodicTask

manifest = ModuleManifest(
    "reporting", "/reporting",
    periodic_tasks={"reporting.tick": PeriodicTask(lambda rt: service(rt).tick(), 60)},
)
```

`PeriodicTask` is immutable. Its callable receives the current Runtime. Intervals
are strict integers from 1 to 86400 seconds; bool/float values are rejected. The
manifest mapping is copied/frozen. Names use lowercase ASCII module/segments,
start with `module.id + '.'`, and are at most 128 characters. Limits are 16 tasks
per module and 64 across one registry/runtime. No schema/migration/dependency or
network service is added.

`Runtime.periodic` owns one daemon timer thread, independent of the existing single
JobRunner. Empty task sets start no extra thread. First execution is due after the
declared interval, measured with `time.monotonic`. Callbacks run sequentially;
none overlaps another callback. Missed intervals are skipped while preserving
monotonic phase; there is no catch-up burst. Event waiting makes stop immediate
while idle. A slow JobRunner handler outside the writer does not block a timer
tick. A callback that waits on a long writer transaction can still be delayed.

Callbacks must be short/bounded, use public services, and derive actor/domain
permission from authorized persisted configuration. The timer grants no auth,
does not dispatch arbitrary client code, and does not replace durable jobs,
checkpoint/idempotency, reporting schedule/catch-up rules or Zalo authorization.
Modules own durable scheduled-work decisions. Never call Runtime start/close or
wait for its shutdown from inside a callback.

## Lifecycle and status

Migrations finish in construction. Runtime start then recovers jobs, runs module
startup hooks in dependency order, starts JobRunner, and starts the timer. Startup
failure closes core resources and releases the root; use a new Runtime to retry.
Repeated successful start is idempotent.

Runtime close signals/joins the timer before touching JobRunner, writer, DB, logger
or root lock. A callback exceeding the 10-second shutdown deadline raises
`PERIODIC_SHUTDOWN_TIMEOUT`; those resources remain open so it can finish safely.
No forced thread termination or second worker is created. Release/cooperatively
finish the callback, then retry close. Once closing starts, start is refused. The
native parent's existing bounded process termination/crash recovery remains the
last resort, rather than tearing resources out from under a live callback.

`runtime.periodic.error_code` and `status()` expose only fixed codes. Status includes
state, running, active task name, current/last error, per-task errors, run counts and
failure counts. Callback errors become `PERIODIC_TASK_FAILED` and later ticks
continue; a succeeding run clears that task's current error, retaining failure
count/last error. Thread startup/internal failures use `PERIODIC_START_FAILED` and
`PERIODIC_RUNNER_FAILED`. Exception messages, payloads, paths and tracebacks are
not returned or logged by the timer. API/desktop health integration should inspect
this public status in addition to JobRunner health; no API files are changed here.

## Validation

PASS: 30 timer/module-registration cases in 23.70 seconds, including 26 new timer
cases. PASS: 7 existing API/real-source-sidecar recovery cases in 20.47 seconds.
Scoped Ruff check, format check and Git whitespace check pass. The existing
Starlette/httpx deprecation warning remains.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_periodic.py tests/core/test_module_registration.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/core/test_api_sidecar.py tests/core/test_api_recovery.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/periodic.py backend/cafe_fin/core/modules.py backend/cafe_fin/core/runtime.py tests/core/test_periodic.py
```

The real-Runtime/WAL cases prove startup ordering, sequential nonoverlap, unchanged
empty defaults, real callback writes, no callbacks after close, writer availability
while stopping, continued ticks after sanitized RuntimeError/SystemExit, and timer
progress while a real JobRunner handler is blocked outside the writer. Startup
hook failure, timer-thread start failure and failure after the worker starts all
release core resources. A real 10-second timeout retains the worker/writer/DB/log
and root lock, lets the released callback finish its write, and permits a second
close and data-root reopen. Validation also covers frozen mappings/types, strict
names/intervals and per-module/runtime task limits.

No heavy import benchmark, external network/send, native installer or Codex
automation was run for this core timer change. A callback blocked indefinitely
cannot be cancelled safely as a Python thread; the retained-resource timeout and
existing parent process recovery are intentional safeguards.
