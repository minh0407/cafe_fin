# Authorized shared-summary export download

## Approved shared prerequisites

Root file-scope commit `22ca543106bdcc91e55e11067683f5514fbbada3` was cherry-picked
unchanged as `4bce76f` (exactly four shared files). Root's DateInput disabled-context
fix `3aa94c601dbf878f07b46b0902fc71b0f388c40c` was cherry-picked unchanged as
`9e6d9fc` (exactly three existing shared files). Root already owns the originals
and should skip these local duplicate commits. No shared ACL, schema or dependency
was authored/relaxed by this lane.

## Problem and route

Exports intentionally use stable storage actor `reporting.export` for cross-actor
retry identity. Generic `/files/{file_id}/content` correctly refuses Operators
who do not own that service actor's file, so using it for reporting downloads
blocked Operators even after a successful export.

New explicit route:

`GET /api/v1/reporting/reports/{report_id}/exports/{export_id}/content`

The UI now uses this report/export route after export instead of the raw file URL.
Reports are shared under the existing current `reporting.read` module policy; the
new route grants only the saved summary belonging to that exact saved report.
It accepts no raw file-ID grant, source workbook ID, arbitrary path, new attachment
or private book permission. It does not read a source provider, render a new
report, or weaken generic core file ownership/Admin/provenance checks.

## Verification boundary

1. Open an explicit readonly snapshot; revalidate the captured principal with
   current `reporting.read`, verify the saved report snapshot SHA/state, and query
   the export ID together with that report ID.
2. Use public FileStore metadata on the same connection. Compare saved file ID,
   SHA and size, `reports` category, and the exact supported format/media type.
   Missing/mismatched saved storage is 409; an unmatched export/report is 404.
3. Only then use trusted `FileStore.read`. Copy into an anonymous temporary file
   under the selected data root, hashing/counting the actual copied bytes in
   bounded 64 KiB chunks. Both FileStore's original verification and the outgoing
   byte hash finish before constructing HTTP 200. No file-sized RAM buffer or
   database transaction is held over file IO.
4. Reopen a fresh readonly snapshot and repeat principal + report/export/storage
   reference checks with the same captured principal. A disabled/demoted/version-
   changed account is denied; it is not silently re-resolved into a new identity.
5. Return only frozen verified bytes, a fixed summary filename, media type,
   Content-Length and X-Content-SHA256. Core middleware retains no-store/nosniff.
   Response completion/disconnect/error closes the temporary handle. Original
   source handles close before final authorization; source edits after that do
   not alter the frozen outgoing bytes. A change after final authorization or an
   already-started response is not claimed to interrupt an active download.

No migration, DTO or export identity change. Reporting v2 still appends after
unchanged v1. The route adds no persistent file row; cross-actor retry keeps one
FileStore object even when failure occurs before the reporting export receipt.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting/test_export_downloads.py tests/reporting/test_review_recovery.py tests/core/test_read_scopes.py -q
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run typecheck
npm --prefix frontend run build
node tests/reporting/ui/check.mjs
```

Focused PASS: **26 cases, 16.01s**, including ten new download regressions. Real
local HTTP/auth/SQLite/FileStore bytes prove Operator A/B sharing + generic 403,
one stored file after cross-actor receipt retry, real PDF/XLSX/TXT hashes,
wrong-report export/private workbook IDs denied without file read, real disable
and demotion during byte hashing with closed handles and no success headers,
missing/corrupt bytes rejected with 409, mutation of outgoing bytes after the
FileStore verification rejected, and metadata changes caught by fresh recheck.

Frontend typecheck/build and scoped Ruff/format/whitespace checks PASS. Browser
harness PASS **18 cases**, adding a real browser download event/filename and the
explicit reporting URL with no generic file request. The harness uses its existing
dedicated port 1431, not root's 1420 or records' 1421; no production origin/CSP,
desktop config or shared test configuration was modified. Root's latest shared
DateInput fix is applied; its 13 shared browser cases were run by root, while
this lane verifies actual consumer flows through the 18-case harness.

Full-suite PASS: **262 tests (88 reporting + 174 core), 165.82s**, no skips.
Existing Starlette/httpx and Vite chunk-size warnings remain.
Windows/Python 3.12.16/SQLite 3.53.1 development
host; all fixtures synthetic. No Zalo transport or real target configuration was
changed and no live send was attempted. Production providers/registry, native
parent/tray, clean Windows installer and live OA/group acceptance remain NOT RUN
in this lane. No push, merge or READY tag was made.
