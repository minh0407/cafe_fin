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
[shared-integration.patch](shared-integration.patch). The refreshed patch only
wires the module/feature and expands test discovery; `git apply --check` PASS.
Coordinator owns applying it and preserving other lane registrations. Approved
root22ca543/48858654 are already cherry-picked as59d94da/1be5a0f; scope checks now
assert403 directly without XFAIL, and structured cell errors reach the UI.

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
connection. Per coordinator's common date-only contract, both endpoints including `through_on` are included, using VN business
date, cutoff belongs to the capture. Reporting freezes DTOs/files before sending.

Approved root bridge-v2 commit `57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a`
is cherry-picked as `0da9c87` on this branch. Provider now emits explicit v2
`metric.meaning` only from configured `semantics.metric_meanings`. Missing meaning
remains null with a flag; an absent expense mapping does not invent a zero metric.
Non-VND is retained separately and omitted from VND DTO metrics with a flag.
Negative/refund or invalid deposit-subset classification keeps the signed exact
amount but clears known meaning and flags it for review. Multiple same-meaning
columns must first use one explicit derived total column, avoiding double counts.

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

## Independent review fixes after the 45bc416 benchmark freeze

- FileStore source references check creation actor/Admin inside the mutation,
  before creating any new batch. Fixing generic file GET alone is insufficient;
  Operator cannot reuse an Admin file ID to read new accounting staging.
- Retained unpublished confirmations lock schema changes, including cosmetic
  renames. Cancellation keeps the lock until resume/publication, so no revision
  change can strand pending rows. Published attempts permit compatible changes.
- Recalculated date formulas discard cached date interpretation metadata.
  Formula `=2` with stale ISO cache yields1900-01-02. Raw cache remains provenance.
- Date-only periods include both endpoints and accept a single day, per the
  common contract. UTC timestamp windows remain half-open.
- Exact rows sharing an explicit business key are reviewable warnings; differing
  normalized payloads remain conflicts, including a final publish recheck.
  Duplicate review includes bounded in-file counterpart details.
- Source/manual/merged rows are capped at256KiB UTF-8. Parse, normalization,
  snapshot reads and pending selection are bounded by4MiB payload and500 rows.
  Formula evaluation has a shared100k cost budget per row and cancellation checks.
  Originals are never truncated. Source ordinal checkpoints survive chunk-budget
  changes across resume.
- XLSX shared-string spool uses trusted app-data imports, ignoring profile paths,
  and closes/removes temporary cache on normal/error exit.

Before the final million-row freeze: full `pytest tests/accounting tests/core -q`
PASS411/XFAIL3(shared core actor scope), one existing Starlette warning. Subsequent
focused review/meaning/formula checks PASS13. `test_review_regressions.py` covers
the three independent repros, inclusive/Vietnam/single-day date boundaries and
invalid periods; `test_hardening_edges.py` covers byte budgets, exact-vs-differing
key matches and trusted spool. Migration tests preserve existing foundation rows,
refuse checksum edits and refuse an old app opening a newer module schema.

Benchmark generator/method: [benchmark-method.md](benchmark-method.md). Initial
development50k full partial-import run PASS96.70s, but source changed while it ran;
that is exploratory evidence, not frozen performance acceptance. Frozen50k/500k/1m
and near-limit XLSX results will be appended after running them. No giant fixture,
DB, sensitive log or generated user data is committed.
