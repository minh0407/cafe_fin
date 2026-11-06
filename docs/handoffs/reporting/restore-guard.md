# Reporting owner restore guard

Reporting implements the default manifest's `on_activate(runtime, principal,
ActivationContext)` hook. A verified restore suspends automatic generation and
Zalo delivery before core recovery, startup hooks, JobRunner or PeriodicRunner.
Move keeps its existing configuration. This is a reporting implementation handoff;
native/four-module acceptance and the core failures below remain integration gates.

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-reporting\cafe_fin`.
Branch: `codex/cafe-fin-reporting-20261106`. No push, merge or READY tag.
Backend/tests commit: `18951a63745ed29d2ed219f89a7820a0cc8b590d`.
The following UI/handoff commit completes this change; integrate both in order.

## Applied shared dependencies

The coordinator-approved commits were cherry-picked in the requested order:

| Root original (already owned by coordinator) | Lane duplicate |
| --- | --- |
| `2fb38e323520697d745b7aab7ddde5e327755265` | `e5045f8c63005cf1e44a86f80891c7ffbf69a0cc` |
| `6294e41706e8d878adddfa76e0c72ff4c74f52d4` | `08e653760ca367bb0893ccac87cc6bcc90a78dbb` |
| `b998a25948635094dd26450432813a5f2a0fa24d` | `a4b96053b3060df93c0712966b2d7c0ed21954d0` |

Skip those local duplicates when integrating reporting's new commits. No further
core, shared contract, dependency, registry or migration file was edited.

## Guard transaction and replay

`reporting/restore.py` validates the frozen public context against core's bound
candidate marker. Every guard call checks current `core.manage`; the serialized
receipt transaction checks it again before looking up a committed receipt.
Namespace `reporting.activation` / `reporting.activation_guard`, keyed by
activation ID, is only receipt identity. Audit uses the actual target Admin ID.
A different current Admin can replay a receipt; revoked/stale authority cannot.
The hook does not copy, delete, read or replace OS credentials and makes no
provider call. Root UUID/OA credential keys deliberately remain unchanged.

For restore, one atomic owner transaction:

- Converts WAITING, FAILED, UNCONFIGURED, SENDING and UNKNOWN to UNKNOWN with
  `RESTORE_REVIEW_REQUIRED`, unless durable complete positive receipt IDs already
  prove delivery. Complete proof means a valid text receipt and, for an attached
  export, a valid file receipt; proven rows become SENT. Existing SENT rows stay
  unchanged. Text-prefix-only attachment receipts remain UNKNOWN.
- Preserves payload, receipt columns, attempts, snapshots, report hashes and
  canonical export bytes. Affected outbox rows increment version once.
- Holds unfinished PENDING/RUNNING/FAILED/BLOCKED daily runs as NEEDS_MANUAL,
  retaining pins and attempts.
- Increments settings version, disables `enabled` and `auto_generate_daily`,
  clears automatic activation/actor binding, and persists `restore_review`
  metadata (activation ID, counts, required flag and review timestamps/actor).
- Records settings before/after and the activation disposition/counts with the
  real Admin. It creates no fake provider delivery attempt.

Move writes its idempotent activation audit/receipt and does not change schedules
or outbox dispositions. A completed activation or restart does not repeat the
guard. Explicit receipt replay also leaves a later Admin choice untouched. A new
restore activation ID applies quarantine again.

## Review and continued work

While review is required, tick/dispatch report suspension, catch-up queues zero,
and enqueue/retry/reconcile/connection-check reject delivery work. Authorization
and suspension run before enqueue/retry receipt replay, so an old WAITING receipt
cannot bypass the hold. After review, replay returns the current delivery state.
Public settings reports `sender_status=RESTORE_SUSPENDED`,
`restore_review_required=true`, and `credential_configured=null` because stored
credentials have deliberately not been consulted.

The existing Admin settings command performs review: inspect OA/group/time,
explicitly turn on the schedule and save a fresh version/key. Saving disabled
settings or changing credentials keeps the hold. The server records review actor
and timestamp; the client cannot author the guard metadata. Automatic generation
remains a separate opt-in switch, cleared by restore.

Old restore UNKNOWN rows never become retryable because credentials, enabled state
or destination changed. Automatic catch-up excludes their entire day/book series
across destinations, including an existing newer SAVED version. Daily generation
checks the series hold before either queued/saved reuse or creating a replacement
version; it records NEEDS_MANUAL with
`RESTORE_REQUIRES_MANUAL`. Future days can create/save/export/send normally after
review. Explicit provider reconciliation can establish SENT only with the existing
positive evidence rules. There is no forced retry or manual fake-SENT command.

Local preview/save/export remain usable during reporting suspension. The Admin UI
shows a restore banner, preserves these actions, and disables enqueue, retry,
reconcile and connection check. Operator calls are still enforced by the backend;
the existing settings endpoint remains Admin-only. No HTTP/native path or extra
approval workflow was introduced.

## Files and schema

- Backend: `restore.py`, `module.py`, `service.py`, `sender.py`, `schedule.py`.
- Frontend: `ReportingPage.tsx`, `types.ts`, `DailyScheduleHistory.tsx`.
- Tests: new `test_restore_guard.py`; existing local-export backup test now uses
  public prepare/dormant activation. The process-kill timer test now permits the
  observed brief startup-job BUSY lock and waits boundedly for IDLE, checking no
  resend and persistent UNKNOWN. Browser coverage extends `ui/check-books.mjs`.
- **No migration.** Existing reporting v1/v2/v3 DDL/checksums are unchanged.

## Verification (initial guard)

Environment: Windows 11 build 26200, Python 3.12.16, SQLite 3.53.1. Synthetic local
SQLite/FileStore backups and default reporting manifest, fake transport and an
instrumented credential store are used. Actual dormant/activate/restart, receipt
commit/ACK fault and current-user revocation paths run; these are not a mock of
core activation. No real DB, Excel, credential, bank data or screenshot is committed.

```powershell
.venv/Scripts/python.exe -m pytest tests/reporting/test_restore_guard.py -q
.venv/Scripts/python.exe -m pytest tests/reporting -q -k 'not real_production_60_second_timer' -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/core/test_runtime_maintenance.py tests/core/test_job_status_connection.py tests/core/test_storage.py tests/core/test_module_registration.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/core/test_activation.py tests/core/test_maintenance_operations.py --collect-only -q
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.venv/Scripts/python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
git diff --check
# In frontend:
npm run build
node node_modules/@playwright/test/cli.js test --config ../tests/reporting/ui/playwright.config.ts
```

- PASS: 8 focused restore tests, including hook order before recovery/threads,
  partial receipts, version/audit/bytes, old enqueue/retry receipt replay,
  cross-Admin replay, fresh authorization after queued revocation, lost initial
  guard ACK, post-review restart, new restore ID, move, destination/credential
  changes, and next-day generation without replacing an old UNKNOWN.
- PASS: **117 reporting tests**, 1 intentionally deselected 60-second timer case,
  61.11s. The existing Starlette/httpx deprecation warning remains.
- PASS: Ruff lint and format (36 files), whitespace, TypeScript and Vite build.
  Existing large-bundle warning remains; no shared build policy was changed.
- PASS: 1 Playwright wrapper (15.1s), containing 21 main + 14 picker/restore
  assertion groups, not 35 separate Playwright tests. Owned Vite 1431 stopped.
  Synthetic logs/screenshots remain in `%TEMP%\cafe-fin-reporting-ui-bWLCII`;
  `reporting-restore-review.png` was visually inspected.
- FAIL: the four selected shared core files produce **40 PASS / 1 FAIL**. Failure:
  `test_dormant_lifespan_has_no_recovery_hooks_jobs_or_timer_until_current_admin_activation`
  expects GET `/api/v1/users` to return 200 after activation; this checkout's core
  API registers POST and PATCH users but no GET, so it returns 405. Its sample-only
  module fixture does not register reporting. Shared code/test was left unchanged.
- NOT RUN: core activation/maintenance-operations cases. Collection produces two
  errors because `cafe_fin.accounting` is absent and the shared fixture imports it
  at module load. No stub, skip, shared test edit or accounting cherry-pick was
  introduced to hide this dependency. Coordinator must run its real four-module
  integration checkout.
- NOT RUN: the 60-second timer case, full backend suite, native storage protocol/
  Explorer/tray/installer, clean Windows acceptance, large benchmark and live Zalo.

## Remaining core boundaries

If the guard commits but activation ACK/startup/completion fails, reporting's
receipt can reconcile idempotently, but core correctly remains FAILED_HELD or
DORMANT/ACTIVATION_REPLAY_REQUIRED. Reporting does not bypass that admission gate;
the supplied core increment has no recovery/disposition API to finish it.
Constructor migrations changing original backup DB bytes also remain a core
cross-version restore limitation. Neither boundary is claimed resolved here.

## Follow-up: existing saved versions in a held series

Coordinator review reproduced v1 WAITING plus v2 SAVED but not queued in a backup.
After restore and Admin settings review, the initial report-ID filter left v1
UNKNOWN but automatically queued/sent v2. Both auto-generation settings could take
this path. The original 117-case result above predates this correction.

`held_series(series_key)` now correlates any restore UNKNOWN/REVIEW_CODE version
with the full same-day/book series. Catch-up filters newly selected reports and
UNCONFIGURED automatic promotion by this predicate. Daily selection checks it
before queued/saved reuse, so an already-existing v2 cannot bypass the hold.
Explicit Admin enqueue/retry/dispatch after global review keeps its existing
behavior; the automatic hold does not become a new manual-send approval workflow.
No migration, UI, shared interface, receipt, report hash or export bytes changed.

New parameterized real backup/dormant/activation tests first failed in both modes
with observed refresh/verify/text calls, then passed after the predicate change.
Two repeated automatic ticks leave zero provider calls and zero delivery attempts,
do not capture a replacement, and preserve the old UNKNOWN row exactly. The same
test verifies an unheld future day sends normally, an explicit Admin enqueue of v2
can send, and both original snapshots/export bytes stay unchanged.

```powershell
.venv/Scripts/python.exe -m pytest tests/reporting/test_restore_guard.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/reporting/test_sender.py tests/reporting/test_daily_generation.py -q -p no:cacheprovider
```

PASS: **10 restore cases in 13.63s**, **29 sender/daily cases in 10.88s**, Ruff
lint/format (4 Python paths) and Git whitespace. Full backend, full reporting,
build and browser are NOT RUN for this Python
predicate-only follow-up, as requested; the coordinator owns integration runs.
