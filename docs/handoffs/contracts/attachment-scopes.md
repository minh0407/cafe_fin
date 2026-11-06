# Attachment ingress and authorized contract downloads

This lane patch follows `773592334c2c00a65e274fc23bfab78ad5d04e8a` and the approved
shared security patch `22ca543106bdcc91e55e11067683f5514fbbada3`. The latter was
cherry-picked locally as `234ae89` (exactly its four approved core/test/handoff
files). Coordinator already owns that shared patch; cherry-pick only the new
contracts patch when the shared change is already integrated. No additional
core/registry/CI edits or migrations are needed.

## Source ownership at attachment ingress

POST `/api/v1/contracts/{contract_id}/attachments` checks the public
`runtime.files.require_owner_or_admin` helper immediately after current
`contracts.write` authorization on the same connection. It checks before reading
source metadata or opening bytes, so another Operator's private file is rejected
403 without exposing its type/content. Own-file and Admin ingress remain allowed.

After bounded type/hash inspection, the same auth plus ownership checks run in
the writer authorizer before saving the domain reference **or replaying its core
idempotency receipt**. A permission/provenance change while inspecting the source
cannot publish a link. A former Admin with a fresh Operator session cannot replay
an earlier privileged command to attach someone else's private file. A file UUID
is never used as a sharing capability.

## Explicit domain sharing route

New additive route:

`GET /api/v1/contracts/{contract_id}/attachments/{attachment_id}/content`

The route validates current contracts.read permission, the existing contract,
the saved attachment belonging to that exact contract and any saved export
version reference. It retrieves core metadata only after the domain reference is
authorized, and compares the immutable attachment hash/name/category/limit.
Trusted FileStore.read verifies the entire file before a response is created.
After reading, a fresh snapshot revalidates current permission and the reference
before HTTP 200 headers. Missing/corrupt bytes return 409 without download/hash
headers; unmatched/unknown contract or attachment references return 404 without
opening a file. Stored hash mismatch or missing file metadata also fail closed.

This reference provides the explicit contract sharing grant. For example, Admin
may deliberately attach an Operator's private document, and another Operator with
contracts.read may download that linked document through this route. Generic
`/files/{file_id}` and `/files/{file_id}/content` remain owner/Admin-only and still
deny that other Operator. The domain route does not make the underlying file
globally shared or permit that reader to attach it elsewhere.

The feature's "Tải tệp gốc" action now uses contract ID plus attachment ID on the
new route, rather than the generic file endpoint. It still uses the shared
authenticated API/blob and session-generation checks. No source search picker,
records interface, document content or template behavior is changed in this patch.

## Verification

Synthetic fixtures use real local accounts, SQLite, FileStore, HTTP and file
bytes. `tests/contracts/test_attachment_scopes.py` has 13 cases covering foreign
documents/workbooks denied before open; own-file attachment; explicit Admin share
and cross-actor read with correct bytes/hash while generic reads deny; wrong and
unknown references; full-file corruption at the last byte; missing bytes; current
actor revocation in the writer and after hashing; demoted-Admin receipt replay;
and the same-connection second ownership check even on an existing receipt.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contracts/test_attachment_scopes.py -q
# PASS: 13 tests in 14.95s.
.\.venv\Scripts\python.exe -m pytest tests/core tests/contracts -q
# PASS: 219 tests in 90.70s (98 core + 121 contracts).
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/contracts tests/contracts
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/contracts tests/contracts/*.py
# PASS; 13 Python files already formatted.
npm --prefix frontend run typecheck
npm --prefix frontend run build
# PASS. Existing 932.79 kB / gzip 305.06 kB shell bundle warning remains.
node frontend/node_modules/@playwright/test/cli.js test --config tests/contracts/playwright.config.ts
# PASS: one real Chromium flow in 21.4s (test body 19.7s).
git diff --check
# PASS.
```

The expanded browser flow clicks "Tải tệp gốc", observes a request to the explicit
contracts attachment route, checks HTTP 200, compares the full downloaded PDF
bytes and SHA-256 header, and receives the expected original filename. The rest
of the purchase/sale/snapshot/PDF-recovery flow still passes. TypeScript/build and
the actual feature harness were rerun; the shared shell registry stays unchanged.

Existing Starlette/httpx and Vite/Playwright color/bundle warnings are not hidden.
Native installer/clean-Windows and DOCX visual release gates are not rerun or
claimed by this authorization patch. The preexisting untracked `.vite/` cache is
untouched and excluded from commits.
