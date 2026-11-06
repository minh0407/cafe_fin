# Human-readable local export copies

## Behavior and integration

Existing canonical `reports/*.bin` identities/bytes/relative keys remain unchanged.
After the immutable reporting export receipt commits, `ReportingService.export`
ensures a derived human-readable copy using public `FileStore.export` into:

`reports/CafeFin-<from_on ISO>-v<report version>-<canonical report UUID>.<pdf|xlsx|txt>`

The selected data root already belongs to the user. Only validated internal date,
positive version, canonical UUID and whitelisted format form this name. No source
name/note/PII or frontend absolute path is accepted. Root.resolve_key checks the
contained destination, including reparse/symlink rejection. The module never
changes canonical core metadata or overwrites/deletes an existing human target.

An existing regular file is reused only when SHA-256 AND size match the canonical
receipt. A mismatched target (including a non-file target) is a durable
`LOCAL_EXPORT_CONFLICT`; no alternate name or false success is invented. Public
FileStore.export handles atomic non-overwriting creation; an EXPORT_EXISTS race
is reused only after the same full verification. A missing copy is recreated from
canonical bytes, without renderer/provider work. Normal retry retains canonical
report/export/file IDs, hashes and receipts; a ready matching retry also returns
stable local metadata without adding a new attempt.

## Durable projection and authority

Append-only **reporting migration v3** adds `reporting_local_exports`, keyed by
export ID, with immutable relative-key/hash/size pins, state, attempts, error code,
last successful verified_at and updated_at. V1/V2 DDL and fingerprints are
unchanged. States are COPYING, READY, FAILED, CONFLICT and PENDING (interrupted).
Existing exports are lazy: no row until an authorized export/retry requests a
human copy. No migration rewrites old canonical exports or touches other lanes.

Canonical idempotency receipts contain canonical fields only. Local-copy work is
performed after that receipt, including on replay, so a copy failure never loses
canonical progress and replay can repair the derived file. Existing render lock
serializes one runtime's export pipeline; no new thread/runner is introduced.
Each attempt checks current reporting.write, validates the saved report/export
and FileStore reference, performs IO outside the writer, and rechecks the same
captured principal/reference before READY. Role/version revocation cannot mark
READY; fixed failure bookkeeping records no new file access grant. Audit records
cover attempt/success/failure. A newer/READY attempt is not downgraded by an old
failure. Recovery changes interrupted COPYING to PENDING; retry verifies/reuses
any completed copy before writing.

The export response and detail.exports entries add `local_export` (null for an
unattempted legacy export), including a **relative_key** for display in the local
UI. The detail screen shows the copy state/path/error and last successful
verification time. It refreshes after an export error, retaining the canonical
receipt on screen. Existing Export buttons provide retry; no approval workflow
or arbitrary native save destination is added. Old Ready timestamps attest the
last check, not a promise that a user cannot later edit/delete the Explorer copy.

Automatic generation completes every selected human copy before queueing. Missing
Zalo still produces all selected real local formats and UNCONFIGURED delivery.
A format failure preserves prior successful formats/snapshot/receipts, marks the
run FAILED and blocks queue/sender fallthrough. Retry uses the frozen report and
canonical receipts instead of capturing/rendering completed formats again.

Local-copy state is independent of sender state; it never proves SENT. Relative
keys/absolute paths are not added to group text, outbound payload, upload filename
or upload metadata. The existing explicit reporting download route still serves
canonical verified bytes under its own authorization checks.

## Backup and operational limits

Core backup continues to preserve canonical FileStore objects and the DB. Derived
human copies are not additional core_file rows and are not separately included by
the current reference-only backup. The [reporting activation follow-up](local-export-relocation.md)
now invalidates copied READY projections and recreates human copies during both
move and restore, before recovery/workers. Existing export retry can rebuild a
failed/missing human copy from its preserved canonical ID/hash, with no source/renderer needed.
Current FileStore.reconcile may list these derived files as orphan keys; reporting
does not delete such files or change core backup/reconcile policy. A hard kill
inside the public copy routine may leave its unregistered .part file; recovery
does not guess/delete unrelated partials. These are derived outputs, not proof
that a canonical object was lost or that a message was sent.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core -q
.\.venv\Scripts\python.exe -m pytest tests/reporting/test_local_exports.py -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run typecheck
npm --prefix frontend run build
node tests/reporting/ui/check.mjs
```

PASS: full suite **272 tests (98 reporting + 174 core), 182.14s**, no skip, one
baseline Starlette/httpx warning. The additional backup test was added after that
full collection; it passed independently (0.89s), then the final local-copy module
passed **11 cases in 6.57s**. Thus all 99 reporting / 174 core cases have passed,
without claiming a single 273-case full run. No production code changed after the
full run began. Frontend typecheck/build, Ruff/check-format and whitespace pass;
baseline Vite chunk warning remains.

Real local tests cover PDF/XLSX/TXT bytes and deterministic safe names, matching
retry, missing-file recreation, conflict/no overwrite, an external destination
race, genuine subprocess death after public copy (exit 47) and startup recovery,
partial auto-format IO failure/resume with one capture and one render per format,
revocation after copy, real v2-to-v3 migration/pin immutability, real backup+verify+
restore+canonical recreation, and no local path in fake-channel text/upload data.
Browser harness PASS **20 cases**, including folder/state display and visible
local-copy failure followed by successful retry without premature download. The
synthetic snapshot screenshot was visually inspected; evidence remains outside
Git under `%TEMP%\cafe-fin-reporting-qa`. Harness stays on dedicated port 1431.

Windows development host / Python 3.12.16 / SQLite 3.53.1. NOT RUN: root production
provider/registry, native Explorer/tray/parent process integration, clean Windows
installer, large-import release gates and live OA/group/send. Adapter/target and
shared services are unchanged. No push, merge or READY tag was made.
