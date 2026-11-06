# P2: export status uses one authorized read snapshot

The earlier export UI observation is now independently confirmed. Root's real
worker proof paused FileStore.put, read the old export row, then completed the
worker before the second-reader jobs.status call. HTTP200 returned
COMPLETED/file_id=null; the next request returned the UUID and download200.
Evidence is retained outside Git at
`C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-export-status-proof-b872563469d94ec59481fa4e29a4af9a`.

Approved core seam `2fb38e323520697d745b7aab7ddde5e327755265` was copied unchanged
as `ad19e16` (only the three approved core/test/handoff files). Coordinator owns
the original and must not apply both copies.

The accounting route now opens one runtime.reader, explicitly BEGINs, freshly
authorizes accounting.read, checks the export row and owner, then calls the
public jobs.status(job_id, connection=conn). The core formatter/response shape
and ownership policy remain unchanged. It does not reorder independent reads,
copy core formatting, modify finalization or change UI polling. A request sees
RUNNING/null before publication or COMPLETED/UUID after it, from one snapshot.

The deterministic regression uses a real worker and FileStore barrier. It
requires the borrowed connection and live transaction, waits for real worker
completion, and still observes RUNNING/null from the old snapshot; a fresh poll
returns COMPLETED/UUID and the actual download matches FileStore's SHA. Other
cases cover owner/Admin reads, other-operator and unauthenticated denial,
revocation after middleware authentication but before the route snapshot, and
unknown/other-namespace job404 without a job lookup or status DTO leak. The new
test is self-contained and does not import a colliding test_public_api module.

Validation on2026-11-07:

- New race/auth regressions: **4 PASS in4.15s**.
- Core seam/auth/job API plus full accounting public API: **33 PASS in18.69s**.
- Existing focused export subset: **6 PASS in6.58s**, including derived CSV/XLSX,
  hidden pending data, whole issue exports and stale issue-export refusal.
- New regression plus core connection tests under `--import-mode=importlib`:
  **12 PASS in5.03s**.
- Existing real browser/API/export/clipboard1000 flow on1424: **PASS25.9s**,
  total27.8s, including visible download action and exact exported data.
- Scoped Ruff and Git whitespace checks: **PASS**. Existing Starlette/httpx and
  Node color-environment warnings remain. No migration/dependency/UI change.

Commands:

```powershell
.venv/Scripts/python.exe -m pytest tests/accounting/test_export_status_snapshot.py tests/core/test_job_status_connection.py -q -p no:cacheprovider --import-mode=importlib
.venv/Scripts/python.exe -m pytest tests/core/test_job_status_connection.py tests/core/test_auth_jobs.py tests/core/test_review_auth_jobs_edges.py tests/core/test_api_job_boundaries.py tests/accounting/test_public_api.py -q -p no:cacheprovider
node frontend/node_modules/@playwright/test/cli.js test --config=tests/accounting/ui/real.config.ts
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/accounting/module.py tests/accounting/test_export_status_snapshot.py
```

The prior552 full-lane/core result and all volume measurements retain their
original versions. No full integrated suite, native installer or volume rerun is
claimed for this narrow delta; coordinator runs its integrated checks and old
proof. Browser/sidecar exited and accounting test port1424 is free.
