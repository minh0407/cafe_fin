# Reporting lane handoff

Development candidate; **integration/live acceptance remains pending**. No push,
merge or READY tag has been made by this lane.

Latest integration follow-ups:

- [Daily local generation, durable recovery and delegated Admin](daily-generation.md)
  adds opt-in capture/save/export/queue and migration reporting v2. **210 tests
  (74 reporting + 136 core), 12 synthetic browser cases PASS**.
- [Actor-scoped read source factory](actor-source-factory.md), commit `82e6913`.
- [Independent QA recovery fixes](review-recovery.md), commit `82cd941`.
- [Inclusive date contract v1](date-range-v1.md), commit `5aa4722`. New snapshots
  are JSON schema 2 with explicit inclusive date/half-open UTC markers; unmarked
  legacy ranges are preserved without reinterpretation.

The 168 combined tests and export hashes below describe the earlier candidate.
Root's lifecycle periodic-task interface is pending an approved shared commit;
the lane currently exposes a finite tick and does not claim native timer binding.

## Checkout and baseline

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-reporting\cafe_fin`
- Branch: `codex/cafe-fin-reporting-20261106`
- Foundation tag peeled SHA: `e668355c227322994902f7e2e38ed7ffb19ff647`.
- Initial schema/commands commit: `f6606c5fc9edebe9df927c7dae5d3a3c8c25c003`.
- Approved shared update: root `57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a`,
  cherry-picked without conflict as `64ae735` (CONTRACT_VERSION=2).
- Backend/report/outbox implementation: `b86e8009a20dc8df92d91a15beb37146eb03a8e7`.
- Approved OS adapter: root `13222da90c0d504b9d95cdeb804dd8fc466aa130`,
  cherry-picked without conflict as `84abda4`. Reporting integration test uses
  genuine Credential Manager and fake transport, then deletes only its exact test key.
- Approved background actor helper: root
  `3021059351a6bf6033eedfdf83e2381c9d95b95e`, cherry-picked unchanged as `60c7ba8`.
  Root already owns the original shared commits and should skip their local duplicates.
- Daily backend generation: `151c666`. Remaining candidate commits are recorded
  in the chat handoff.

Lane-owned changes only touch reporting backend/frontend/tests/handoff paths;
the ten shared files in `64ae735`/`84abda4`/`60c7ba8` are exactly the
coordinator-approved cherry-picks.
No production
data, DB, real Excel, token, account information, images or generated binaries are
committed. Test transport never contacts Zalo.

## Behavior

User selects inclusive Vietnam business dates; snapshots record corresponding
UTC `[from,to)` bounds, UTC capture cutoff, source DTOs, mapping revisions,
coverage, consistency attestation and SHA-256. Preview captures once; save does
not re-read sources. A new version for the same date/book series requires a
reason. SQLite triggers prevent content edits/deletes and reversion of saved
reports. Old exports keep their immutable FileStore identity/hash.

Money/kg never use float. Totals can exceed int64 without losing digits. XLSX
values are explicit text so Excel's 15-digit numeric precision cannot silently
change them or interpret source strings as formulas. PDF uses core's bundled
Noto font/renderer. PDF/XLSX bytes are deterministic for retry after a file was
stored but before its reporting export receipt was registered. Rendering/file
work occurs outside writer transactions; duplicate exports are serialized with
the public render lock and deduplicated by report/format.

No combined money total exists across CRM/books. No invoice-to-cash inference.
Only explicit typed metric meanings are interpreted; keys such as `income`,
`expense`, `deposit`, `offset` are not semantics. Null/unknown meanings remain
visible locally with a warning and are omitted from shareable summaries.
Missing mapping or missing production breakdown is unavailable, never zero.
There is no QC/approval/hold workflow and hold is never added to stock.

All current exports are **summary-only**, with ordinal warehouse/product/book
labels and no arbitrary source descriptions, IDs, notes, paths or provider flags.
The local detail screen retains DTO source IDs for inspection. Summary files
point back to the local snapshot by hash, without a localhost link. Only a
reporting-owned summary export of that same report can be explicitly selected
as an attachment. Schedules never choose attachments automatically.

Reports (`PREVIEW`,`SAVED`) and deliveries (`WAITING`,`SENDING`,`SENT`,`FAILED`,
`UNKNOWN`,`UNCONFIGURED`) have independent states, paginated lists, search,
validated server sort/filter, version checks and actor-generation UI reset.

## Registration / read bridge

Coordinator registers `cafe_fin.reporting.module.module_manifest` and frontend
`reportingFeature` from `frontend/src/features/reporting/index.ts`.

```python
module_manifest(
    actor_source_factory=lambda runtime, actor: AtomicSources(
        runtime.reader,
        records_callback_bound_to_current_actor(runtime, actor),
        accounting_callback_bound_to_current_actor(runtime, actor),
    ),
    secret_store=foundation_os_secret_store,
    transport=OfficialGMF(),
    heartbeat_bound=False,  # True only after runtime timer is actually integrated
)
```

The factory runs on each actual capture. Bind both public providers to that
current principal; never retain an earlier request's Admin. The two returned
connection-aware helpers receive `(conn, first_date, last_date,
cutoff=aware_utc)` and accounting additionally receives `book_id` after conn.
`AtomicSources` explicitly BEGINs a read-only transaction: SQLite legacy SELECT
autobegin alone is insufficient for snapshot isolation. It never imports either
owner's ORM/tables. `BridgeSources(records,accounting)` remains a convenience for
existing public bridge protocols but marks cutoff-only consistency as a warning.
Default source raises `REPORT_SOURCES_UNCONFIGURED`; it never creates fake zeros.

Module manifest includes migration, router, finite `reporting.dispatch` core job
and startup recovery/catch-up. It installs no new job runner. Coordinator binds
`ReportingService(...).tick()` to the core/native lifecycle timer and stops the
timer before closing writer/root. Default current heartbeat is one request/minute
while Reporting screen is mounted. Status text states this limit. Startup also
performs one catch-up/dispatch. Native tray/background timer is an integration
gate, not claimed complete by browser tests.

Files: backend `models.py` (commands), `migrations.py` (schema v1),
`schedule_migrations.py` (append-only v2), `schedule.py` (daily orchestration), `sources.py`
(public/atomic adapters), `service.py` (reports/config/outbox), `exports.py`
(summary renderers), `zalo.py` (official transport/secret protocol), `sender.py`
(single sender/receipts/reconcile), `module.py` (manifest/router/job). Frontend
`ReportingPage.tsx`, `types.ts`, `index.ts`; all regression and synthetic UI/evidence
helpers are under `tests/reporting/**`.

Migration: namespace `reporting`, versions 1 and 2, checksummed DDL and immutable triggers.
Tables: `reporting_reports`, `reporting_exports`, `reporting_settings`,
`reporting_outbox`, `reporting_attempts`, `reporting_locks`. No central version
table or another lane's migration was modified. V2 adds `reporting_daily_runs`
and `reporting_daily_cursor`; the v1 file/checksum is unchanged.

## Delivery guarantees and limits

Outbox key is immutable report UUID (which fixes period/series/version), OA and
destination. Payload/attachment selection cannot be changed after enqueue.
Only one sender holds the durable module lock; configuration/credential edits
cannot race that lock. Core owns runtime single-instance and execution. Network
operations never retain the writer transaction. State transitions/receipts and
retry actions are audited without credential bytes.

Text message_id is committed before uploading/sending an optional attachment.
A known failed file step can retry without resending confirmed text. An absent,
malformed or wrong-group send receipt cannot become SENT. Post-send timeout or
process death becomes UNKNOWN; UNKNOWN has no retry action. Known preflight/
refresh/upload failures do not falsely say a message was sent. A text receipt
already durable with no attachment is recovered as SENT.

Official adapter uses fixed HTTPS OA endpoints, TLS verification, no redirect
credential forwarding, no proxy-from-environment and fixed redacted errors.
No public webhook, personal-account library or cloud sidecar is introduced.
Initial credentials are supplied through Admin and the injected OS SecretStore;
they never enter core request receipts, DB, audit, URLs, reports or logs.
Refresh tokens are single-use: the OS credential stores REFRESHING before the
request and a complete replacement pair atomically after success. Crash/ambiguous
refresh requires reauthorization; it does not blindly reuse the old refresh token.

Default SecretStore is unavailable until coordinator injects the approved
`core.secrets.WindowsCredentialStore()` into the manifest/runtime service.
Credential write fails explicitly, connection
check says UNCONFIGURED and reports remain local. No plaintext-file fallback.
The OS adapter has a 2,560-byte UTF-8 JSON blob limit; oversized replacement
returns a fixed clear error and preserves the prior pair. Reporting's genuine-OS
test proves Admin write, atomic refresh replacement across store instances, no
credential in request receipts/audit, and exact-key cleanup. Credential backup
does not move to another Windows user/machine; re-enter credentials there.
The app must have suitable OA/app/group permissions/services and the user must
authorize a specific verified live target before any real send test.

No exactly-once guarantee is made: documented send API does not provide a usable
idempotency key. Official reconciliation checks available history but does not
accept a text/time match alone as proof; unresolved items remain UNKNOWN. A
stronger positively correlated receipt adapter is needed for automatic resolution.

File-message API is documented; the upload endpoint/account capability still
requires verification. `OfficialGMF.upload_verified` defaults false and attachment
deliveries fail preflight before sending text. Do not enable the flag until the
current upload contract and real OA/app capability are confirmed.

Manual-only catch-up considers saved immutable reports, preserving their business
date. With daily generation opted in, the durable daily orchestrator owns the
selected series: capture today's data, reuse compatible saved manual reports,
or resume already frozen input. Old days without a snapshot become MISSED;
failed exports never fall through to implicit sending. See the daily handoff for
the pinned config/manual-version policy. Sleep/off/closed app cannot send on time.
No Codex automation is used as a product scheduler.

## Official capability review, 06/11/2026

- [GMF text](https://docs.zaloplatforms.com/docs/OA/nhom-chat-gmf/tin-nhan/text_message)
- [GMF file](https://docs.zaloplatforms.com/docs/OA/nhom-chat-gmf/tin-nhan/file_message)
- [OA authorization / rotating refresh](https://docs.zaloplatforms.com/docs/OA/bat-dau/xac-thuc-va-uy-quyen-cho-ung-dung-new)
- [Group status](https://docs.zaloplatforms.com/docs/OA/nhom-chat-gmf/quan-ly/get_group_info)
- [GMF service conditions](https://oa.zalo.me/home/documents/vie/guides/quan-ly-nhom-gmf_1954166378348758227)
- [Group Bot](https://bot.zapps.me/docs/build-bot-interaction-with-group/): still
  states internal testing; not selected as a default alternative.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run typecheck
npm --prefix frontend run build
# Separate terminal, synthetic UI harness; registry remains coordinator-owned:
node frontend/node_modules/vite/bin/vite.js --config tests/reporting/ui/vite.config.mjs
node tests/reporting/ui/check.mjs
.\.venv\Scripts\python.exe tests/reporting/generate_evidence.py --output $env:TEMP/cafe-fin-reporting-qa
```

Final combined run: **168 PASS (45 reporting + 123 core), 60.00s**, one baseline
Starlette/httpx deprecation warning, no skips. OS-adapter focused increment:
16 PASS (15 core + 1 reporting), genuine Windows API with exact-key cleanup.
After compacting PDF metadata to avoid an orphan last page, the 18 relevant
report/export/v2 tests passed again in 7.57s; final two-page render was inspected.
Python 3.12.16 / SQLite
3.53.1 / Windows development host. Ruff, frontend typecheck/build and git diff
checks PASS. Tests cover exact aggregates,
VN month boundary, late edit/version/replay, missing mapping, no key-based cash
inference, redacted summaries, real FileStore/PDF/XLSX, deterministic export,
HTTP/auth/Admin boundary, server paging/sort/filter, concurrent sender/scheduler,
token rotation/expiry, wrong group, unknown timeout/receipt and attachment retry.
Real subprocess test exits with code 37 after a fake transport side effect and
proves restart keeps UNKNOWN without resending. Synthetic visibility provider
uses real core import manifests/chunks/publish/claims and proves pending hidden,
published once, next corrected row not recounting previous attempt, and immutable
worker input after staging/mapping edits. The v2 consumer test uses actual frozen
InventoryMovementSummaryDTO/MappedBookMetricDTO values, proves received 16 kg
is only purchased 10 kg, separate production/transfer/adjustment categories,
closing 7 kg, and deposits remain subsets rather than added cash.
AtomicSources test commits a user edit
between owner helpers while the report retains one read snapshot.

Browser harness passed eight cases: paging URL/server, snapshot precise kg/missing mapping,
v2 stock components/typed cash/deposit-subset labels,
UNKNOWN no retry, unresolved reconcile, unavailable secret store, connection
check without send and actor reset. Generated screenshots are under
`%TEMP%\cafe-fin-reporting-qa` (synthetic, outside Git). Latest v2 Vietnamese PDF
was rendered with bundled Poppler and both pages visually inspected; no
clipped text or missing glyphs. UI snapshots (including v2) were also inspected.
The native development-host export evidence hashes are:

| Artifact | SHA-256 | Bytes |
| --- | --- | --- |
| reporting-demo.pdf | `73b50ad06f88691d178d80cf46dab4a35e3bb54252f994f1e874eed7158558d6` | 36,231 |
| reporting-demo.xlsx | `11d81026004544c99e04adad0b43ba0c1b681f9c5db0949cc9d1142e74926cfe` | 6,452 |
| reporting-demo.txt | `332660b2e496fc4c96b4e4db0c940dbc583cada4c7013ec3d7405d24cbde0837` | 566 |

Captured snapshot SHA: `c20801e3eebc62b3ceff67d4b9b7b926bac395b1c97a4ccc77ec66b2164c717e`.

Production build still uses the foundation registry stub until coordinator binds
the feature; typecheck and separate Vite harness compile the actual feature.

Known baseline warnings remain: Starlette/httpx TestClient deprecation and Vite
chunk >500KB. No dependency/config changes or warning suppression were made.

## Acceptance still required

1. Shared DTO v2 has been applied and tested with actual typed synthetic providers;
   this does not prove real records/accounting implementations.
2. Bind real records/accounting helpers, run full pending/publish/resume/corrected
   import and simultaneous-edit integration through those providers.
3. The OS adapter and reporting integration are tested; bind the adapter and
   lifecycle heartbeat in the coordinator registry/runtime. Native tray/close/sleep/reopen,
   data-root move/backup/recovery integration remains coordinator-owned.
4. Verify official upload capability and live OA/app/group access, then run a
   specifically authorized synthetic live send; no real send has been attempted.
5. Clean-Windows installer, native/library license and million-row release gates
   remain as documented by coordination; this lane does not mark them PASS.
