# Daily generation and actor authorization handoff

Prerequisite shared commit: root `3021059351a6bf6033eedfdf83e2381c9d95b95e`,
approved and cherry-picked unchanged as `60c7ba8`. No shared source was authored
by this lane. Root must already have this helper before applying the daily code.
Actor factory and independent-QA fixes are in `82e6913` and `82cd941` separately.

## Public wiring

Use `module_manifest(actor_source_factory=..., secret_store=..., transport=...,
heartbeat_bound=...)`. The factory receives `(runtime, current_principal)` on
each actual capture and returns a ReportSource, normally AtomicSources callbacks
bound to public records/accounting providers and that principal. Source/static
source_factory modes remain mutually exclusive fixture alternatives. Never bind
one global Admin or retain the principal from an earlier HTTP request.

`ReportingService.tick(now=None)` is a finite public call: at most 100 gap records,
one generation/resume with at most three selected exports, then one delivery.
The registered `reporting.dispatch` job invokes it. Root owns the lifecycle timer,
shutdown/drain and native tray behavior; no extra backend runner/thread, tray or
Codex automation is installed. UI heartbeat still only works while Reporting is
mounted unless root has actually wired the runtime timer.

## Admin configuration and authority

- `auto_generate_daily` defaults false and is an explicit opt-in.
- `daily_book_ids` is unique/sorted, max 100 IDs of max 128 characters each.
- `daily_export_formats` contains unique pdf/xlsx/txt values, at least one when
  auto-generation is opted in. Formats are for local storage, not attachments.
- `enabled` activates the schedule; `send_at` and timezone are user-selected.
  Automatic local generation may be enabled without OA/group/credential. The
  resulting immutable report/exports remain available and outbox is UNCONFIGURED.
- Backend derives `scheduled_actor_id` from the Admin who saves configuration.
  It is not accepted in the client command (strict extra-field rejection).
- Each generation attempt resolves that persisted actor with
  `auth.resolve_actor(conn,id,'core.manage')`, then keeps the SAME captured
  principal through capture/save/export/queue/final progress writes. Each writer
  step revalidates its active state, role and version. It never re-resolves in the
  middle of a failed attempt to conceal revocation. A subsequent finite retry is
  a new counted attempt and may resolve the currently permitted account.
- Logout requires no replacement login/session. Disabled/demoted owners block
  generation and sending. Final config-version guards also prevent an in-flight
  worker from changing its book set/target when Admin edits staging/settings.
  Existing legacy configurations without a trusted actor need an Admin save;
  the code never chooses an arbitrary Admin on their behalf.

## Day, snapshot and duplicate policy

The trigger uses the current date/time in the configured scheduler timezone;
the captured report is always the **current Vietnam business date**. Default VN
timezone therefore means the configured hour on that same VN day. Date-only
from_on=through_on and inclusive contract v1 / UTC half-open bounds are unchanged.

The one configured delivery profile has ID `delivery`. A durable unique
`(profile_id,business_on)` record and a persisted singleton generation lock protect
two ticks, concurrent UI/runtime ticks and restarts. Run pins (config, actor,
books, formats, target and original scheduled due instant) are immutable.

When due, a new run captures current read-bridge DTOs, stores a preview, saves it,
exports every selected summary format under data root reports, then queues only
sanitized text. Automatic work never selects a new attachment. Snapshot records
`generation.kind='scheduled_daily'`, run/profile IDs, original scheduled_due_at,
created_late and the actual capture cutoff. If preparation crosses VN midnight,
capture is blocked rather than reading a past day with today's state.

Same-day late start is allowed and explicitly marked created_late. Missing old
days since opt-in become MISSED / MISSED_REQUIRES_MANUAL, with no source read or
invented numbers. Gap bookkeeping is bounded independently of today's capture.
Already captured immutable input can resume save/export/queue later; the real
process crash test proves the next-day resume works with sources deliberately
unbound, retaining the original cutoff. Saved manual reports can also be reused.

Manual same-series/day policy is explicit: reuse an already queued version for
that destination first; otherwise reuse the latest compatible SAVED manual
snapshot. Its original cutoff is retained. No new automatic version is captured
or silently sent on top of that manual report. Manual PREVIEWs and unclassified
legacy snapshots are not treated as proof of a valid saved daily snapshot.

Config edits do not mutate an existing run's pins or create a second automatic
run for that profile/day. A pending run whose config version changed becomes
NEEDS_MANUAL; completed runs stay pinned. New settings apply to later days, or the
user can create/queue an explicit manual adjustment. In particular, changing an
empty or old destination does not silently retarget old immutable payloads.
Adding credentials to the same configured OA/group can resume its UNCONFIGURED
queue without a new report or attachment choice.

## Persistence, recovery and UI

Append-only migration **reporting v2** is in `schedule_migrations.py`; v1 file and
checksum are unchanged. It creates `reporting_daily_runs` and
`reporting_daily_cursor`, with immutable pins/report-reference triggers. The
manifest appends v2 after v1; the foundation migration runner remains unchanged.

Partial progress is durable: stable preview/save/export/queue request keys reuse
the same report/version/file/outbox. Failures retain snapshots, files, receipts
and phase/error state. A failed generation/export does not fall through to the
generic saved-report scheduler or sender. The independent sender still records
its own SENT/FAILED/UNKNOWN state; daily COMPLETED means local creation/queue
finished, not a claim that Zalo accepted a message.

`GET /reporting/scheduler/daily-runs?page=1&page_size=25` returns paged states,
policy, phase, attempts and report/outbox refs. Admin UI exposes explicit opt-in,
book IDs, selected formats, policy/closed-app limits and a separate run history.
MISSED/NEEDS_MANUAL/BLOCKED/FAILED are visible, and the late-capture alert appears
when inspecting its snapshot. All secret fields remain OS-store-only.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run build
node frontend/node_modules/vite/bin/vite.js --config tests/reporting/ui/vite.config.mjs
node tests/reporting/ui/check.mjs
```

PASS **210 tests (74 reporting + 136 core), 78.80s**, one baseline Starlette/httpx
warning, no skip. Scoped Ruff check/format, frontend typecheck/build, whitespace
checks PASS; baseline Vite large-chunk warning retained. Python 3.12.16 /
SQLite 3.53.1 on Windows development host; not clean-client/installer acceptance.
PASS 12 synthetic browser cases, including explicit opt-in, bounded book/format
payloads, no client actor spoof, and visible missed days. Screenshots remain in
`%TEMP%\cafe-fin-reporting-qa` outside Git.

Daily tests cover missing credentials with all three real local export formats,
configured fake-channel send once, simultaneous ticks, restart, process death
after immutable capture, next-day frozen resume without a source, missing old
days, midnight crossing, late cutoff, manual older queued version reuse, export
failure/retry without recapture, disable during capture, demotion after export,
logout, config change/pin immutability and a genuine v1-to-v2 migration preserving
old snapshot/hash. No real Zalo send was made. Shared OS adapter tests still use
only scoped synthetic keys and clean them up.

NOT RUN in this lane: root registry/lifecycle timer and real records/accounting
provider integration, actual OA/app/group/live permissions, clean Windows,
installer/native license and million-row release gates. Existing official sender,
no-exactly-once and unresolved UNKNOWN limits remain unchanged. Root integrates
and reviews these changes before push; this lane creates no READY tag.
