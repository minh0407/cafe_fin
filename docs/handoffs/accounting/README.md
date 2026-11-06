# Accounting lane handoff (development, not release acceptance)

Baseline `cafe-fin-foundation-ready-v1` =
`e668355c227322994902f7e2e38ed7ffb19ff647`.
Worktree `C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`,
branch `codex/cafe-fin-accounting-20261106`. No push/merge/READY tag.

## Delivered behavior

Independent configurable books, stable column IDs/logical positions, immutable
schema revisions and reusable mapping profiles. Optional CRM references remain
text; no CRM/stock/payment writes. Exact money uses core scale-2 int64 checks,
Decimal strings and Python Decimal/integer aggregates beyond SQLite SUM limits.

Server-paged React Data Grid with real versioned CRUD, audited soft delete/restore,
bounded draft undo/redo, selected TSV copy/paste and drag-fill preview, cell issues,
conflict comparison, filter/sort/search, frozen/resizable columns and dirty guards.
Actor/generation-scoped cache and drafts; no full workbook in browser state.

Immutable original FileStore bytes/hash; CSV/XLSX/XLSM safe streaming projection,
native XML numbers never authoritative float. Persistent staging, patches, issues,
source identities, exact/candidate duplicate warnings and explicit decisions.
Each confirm pins server validation/schema/mapping/decision revisions, locks the
batch until complete, and builds sealed immutable manifests in <=500-row chunks.
Core claims/receipts + pending rows + progress commit together; final publication
uses JobContext.finalize and a short state flip, without updating a million stage
rows. Published lineage is derived from core published claims. All record queries,
CRUD, totals, exports and public bridge use the core visibility predicate.

Durable module outbox covers command commit before job submission; superseded
tasks are fenced. Actor permissions are rechecked inside each chunk/finalization.
Cancellation preserves hidden pending/snapshot for explicit resume and prohibits
edits/new confirms over a retained attempt. Partial import errors can be repaired
and revalidated after publication; published source rows never become new entries.

Before/new/after provisional totals, per-currency totals and configured dimensions
(interactive report max1000 groups), read-only connection-bound reporting provider,
CSV/XLSX derived export jobs and whole unresolved-issue exports. XLSX emits exact
numeric XML up to Excel's 15-digit precision boundary, exact text above it, typed
dates, literal text and an explicit fidelity notice sheet. Originals are separate.

## Integration and migration

See [shared-change-request.md](shared-change-request.md) and the reviewable
[shared-integration.patch](shared-integration.patch); patch applies to the unchanged
foundation shared files (`git apply --check` PASS). Coordinator owns applying it.
It wires module/feature, preserves API error details, and proposes closing core
cross-actor job/file read routes. The scope regressions conditionally XFAIL while
those shared routes return200; module endpoints themselves return403.

`accounting.module.module_manifest()` exports namespace migration `accounting:1`,
router, permissions, four resumable job handlers and startup recovery/outbox hook.
DDL/checksum is in `schema.py`; never alter an applied migration after integration.
Future changes append migrations. No down/drop/truncate/reset operation exists.
Application rollback to a build without this namespace must refuse newer schema;
restore a verified backup into a separate root or keep the compatible application.
Tests use fresh synthetic roots; no production migration or real data was touched.

Public reporting import: `from cafe_fin.accounting.public import AccountingReadProvider`.
Pass `connection=conn` from a caller-owned `runtime.reader()` after `BEGIN` and the
first snapshot read. Records and accounting must share that exact connection.
Provider neither opens another reader nor commits/rolls back/closes the supplied
connection. Core DTO v1 remains unchanged; `through_on` is exclusive VN business
date, cutoff belongs to the capture. Reporting freezes DTOs/files before sending.

## Formula and operational limits shown to users

The supported engine/grammar/blank/criteria/round/copy semantics are documented in
[formulas.md](formulas.md). No eval, macros, external workbooks or network formula.
Source formulas calculate only inside the mapped selected-sheet scope; missing,
unsupported/shared follower formulas keep errors, never silently use cache/zero.
Raw formula/cache/provenance survives manual overrides and audit.

Saved book formula templates use current stable logical row references such as
`=ROUND(A{row}*1.1,2)`, so CRUD recalculates the row and display sorting does not
change meanings. Static cross-row templates reject `FORMULA_BOOK_SCOPE` rather
than leave stale persisted results. Imported source ranges support the engine's
bounded references over immutable staging. Logical row slots are never renumbered;
insert appends and delete leaves a slot. Source calculation is a snapshot, not an
Excel workbook with every dependency/structural edit emulated.

Page max500; UI default200; selection/copy/fill500 cells within loaded page;
larger data uses source-file staging/export jobs. Parser limits and reread/skip
resume costs are explicit in [parsers.md](parsers.md). Encoding/delimiter, dates,
hidden/blank/merged handling and mapping must be confirmed; totals/header repeats
are not inferred. No XLS support, macro execution or full Excel fidelity claim.

## Verification and remaining release gates

Unit suites, real SQLite WAL workers/API, true subprocess crash probes, and
Chromium UI with real local sidecar are checked separately. See tests under
`tests/accounting`; UI harness and UAT are documented in `ui.md` when finalized.
Browser bootstrap replaces native invoke only; API/auth/files/jobs are real.
Native WebView2/clean-Windows installer acceptance remains NOT RUN in this lane.

Benchmark generator/method: [benchmark-method.md](benchmark-method.md). Initial
development50k full partial-import run PASS96.70s, but source changed while it ran;
that is exploratory evidence, not frozen performance acceptance. Frozen50k/500k/1m
and near-limit XLSX results will be appended after running them. No giant fixture,
DB, sensitive log or generated user data is committed.
