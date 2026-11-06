# Contracts lane handoff

Development implementation on reviewed foundation; this is not native Windows
release acceptance. No push, merge, PR or READY tag was created by this lane.

Independent-review patch: [review-fixes.md](review-fixes.md) documents cross-actor
storage receipt recovery, canonical UUID handling, the appended v2 migration and
the latest validation. The original candidate evidence below remains historical.

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin`
- Branch: `codex/cafe-fin-contracts`
- Baseline: `cafe-fin-foundation-ready-v1`
- Peeled baseline SHA: `e668355c227322994902f7e2e38ed7ffb19ff647`
- Target repository: `https://github.com/minh0407/cafe_fin.git`

## Delivered behavior

Both purchase and sale contracts accept entirely manual embedded company/party
profiles and one or many goods/weighing lines. Typed records lookups are optional;
there is no records dependency or approval/QC/finance gate. Company, counterparty,
contacts, representatives, banks, optional weighing numbers, quantity, price,
quality, delivery, packaging, responsibilities and free text remain editable in
the contract snapshot. Source edits never write back to records.

Tax modes distinguish unspecified, explicit none, inclusive and exclusive. No
missing tax is replaced with zero. Core kg/money parsers enforce 0.001 kg and
0.01 VND, canonical strings, nonnegative valid inputs and int64 limits. Numeric
draft totals and goods lines persist as scaled SQLite integers alongside the
canonical draft/snapshot JSON. Line amounts round half up first; contract tax
rounds once afterwards. Vietnamese amount words read that exact rounded total,
including fractional VND. Details and tests are in [rendering.md](rendering.md).

Cash, bank, mixed and other payment methods export their actual input, receiving
account, deadline, optional schedule, deposit terms and separately labeled
user-recorded paid amount. These are document terms, not cash/accounting effects.

Saving uses the core idempotency receipt and expected_version. Editing and soft
delete/restore retain core audit before/after. Export creates an immutable
module-owned snapshot containing data, totals, template version/hash and final
literal DocumentSnapshot, with exporter/time metadata on the version. Replays
of the same request key recover the same export sequence; another payload under
that key conflicts. Later template, party, weighing or draft changes do not
change old snapshots or downloaded bytes. Historical exports remain available
after draft soft deletion.

`snapshot_sha256` is the SHA-256 of canonical JSON for the full snapshot returned
by the version API (sorted keys, UTF-8, compact separators). Preview and export
use that same meaning, including after Admin template revisions. Core DOCX/PDF
embedded identifiers separately identify their shared DocumentSnapshot content.

Requested DOCX and PDF have separate states/files/hashes. DOCX uses core's DOCX
method without initializing PDF fonts; missing/corrupt PDF font setup only fails
PDF. Successfully rendered bytes are staged durably in a module BLOB before
FileStore.put, then cleared after the linked file/audit transaction succeeds.
Thus a restart between independent storage and domain transactions retries the
exact bytes, even though DOCX/PDF encoders can include timestamps. Rendering and
streaming happen outside the writer transaction. Each output is bounded to 32 MiB.

A failed format can be retried or supplemented on the same snapshot. Previously
saved artifacts are verified on retry and before download headers. Missing or
corrupt historic bytes are reported; the lane never regenerates or replaces them
silently. Restoring identical bytes makes the same file ID/hash available again.

Optional attachments reference core documents by file ID, preserve hash,
uploader/time/note and optional export-version reference. Allowed file names and
basic signatures are PDF/DOCX/PNG/JPEG/TIFF, up to 20 MiB. User-recorded signed
status returns `signature_verification=not_performed`; no signature recognition,
review queue or mandatory attachment exists. Content is not executed.

No operation imports or writes records stock/cash/receivable/accounting services
or tables. Standalone tests prove no records/accounting tables are created and
source DTOs remain unchanged; test bridge stock/receivable callbacks fail if
called. Only contracts and core audit/idempotency/file metadata are affected.

## Public integration

- Backend: `backend/cafe_fin/contracts/module.py::module_manifest(records=None)`
- Frontend: `frontend/src/features/contracts/index.ts::contractsModule`
- Migration: `backend/cafe_fin/contracts/migrations/v001.py`, namespace
  `contracts`, version 1, schema_checksum registration. Tables:
  `contracts_drafts`, `contracts_lines`, `contracts_templates`,
  `contracts_versions`, `contracts_outputs`, `contracts_attachments`.
  Checksum: `8bd034cc4b168aed91411c3e4fd8e280dff72f872455adb1e8b8c8ae9d0fa3d5`.
- Original templates: `backend/cafe_fin/contracts/templates/purchase.json` and
  `sale.json`; Admin updates append DB template versions without changing source.
- Bridge: frozen `core.contracts.RecordsReadBridge.lookup_party/get_weighing`;
  PartyInput/WeightLineInput/SourceReference use core fields. Line selection pins
  weighing UUID/version/index and original source snapshot. Same source/index
  twice in one contract is rejected, including across source versions.

API prefix `/api/v1/contracts`:

| Method and path | Behavior |
| --- | --- |
| GET/POST root; GET/PATCH/DELETE `/{id}`; POST `/{id}/restore` | Paged/search/sort/kind-filter drafts; save/version/soft-delete/restore |
| GET `/templates`; PATCH `/templates/{id}` | Current catalog, Admin-only versioned template edit |
| GET `/sources/parties/{id}`, `/sources/weighings/{id}` | Optional typed read bridge; absent provider reports manual-entry alternative |
| POST `/preview` | Exact validated document content/totals/template descriptor |
| POST `/{id}/exports` | Pin expected draft version; requested formats independently |
| GET `/{id}/versions`, `/{id}/versions/{version_id}` | Paged immutable export history and file states |
| POST `/{id}/versions/{version_id}/files` | Retry/add formats on the pinned snapshot |
| GET `/{id}/versions/{version_id}/files/{format}` | Verified original bytes and SHA-256 header |
| GET/POST `/{id}/attachments`; GET `/{id}/history` | Optional documents and paged draft audit |

Command bodies carry request_key; edits/delete/restore/initial export additionally
carry expected_version. Module responses have explicit OpenAPI schemas for data,
totals, preview, templates, versions and attachments; errors/auth/paging follow
core conventions. Operators use existing contracts.read/write; template edits
add contracts.templates under Admin's existing wildcard.

Coordinator-owned wiring and exact packaging diff are in
[shared-change-request.md](shared-change-request.md). No central registry,
dependency manifest, lockfile, core migration or other lane was modified.

## Validation

Repository venv was created with locked dependencies using existing build tools:

```powershell
& 'C:\Users\NC\AppData\Local\Temp\cafe-fin-foundation-tools\uv\bin\uv.exe' sync --locked --python 'C:\Users\NC\AppData\Local\Temp\cafe-fin-foundation-tools\python\cpython-3.12.16-windows-x86_64-none\python.exe'
.\.venv\Scripts\python.exe -m pytest tests/core tests/contracts -q
# PASS: 180 tests in 48.04s (86 foundation + 56 domain + 38 API).
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/contracts tests/contracts
# PASS.
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/contracts tests/contracts/*.py
# PASS: 10 files already formatted.
.\.venv\Scripts\python.exe -m compileall -q backend/cafe_fin/contracts
# PASS.
```

Machine/runtime: Windows developer host, Python 3.12.16, SQLite 3.53.1. There is
one existing Starlette TestClient/httpx deprecation warning. Tests use synthetic
data and independent temp DB/files, real local auth/HTTP/SQLite/FileStore and both
actual document encoders. Fault cases include render/font, storage and database
failure after FileStore.put, restart, concurrent same-key calls, optimistic
conflicts, wrong request payload, and missing/corrupt historical downloads.

PDF visual: synthetic purchase 2 pages and long sale 5 pages, all seven raster
pages inspected. Vietnamese, long names/addresses, 24 goods lines, long clauses,
payment schedules and literal HTML-looking text are readable, without clipping
or overlap. Proof hashes/commands and limitations: [rendering.md](rendering.md).
Fixtures/logs remain outside Git at
`C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-render-proof`.

Frontend/browser: PASS TypeScript, production shell build and one complete real
Chromium business flow (14.6s). The shell registry intentionally still has its
placeholder; the lane-owned harness imports and runs the actual feature with
the real API. Evidence, exact commands and screenshots: [frontend.md](frontend.md).
The final four API cases additionally prove preview/export/canonical snapshot
hash equality for both built-in and revised templates; they do not alter rendered
business text or frontend behavior from the browser-verified snapshot.

## Release limits and provenance

- DOCX raster/layout: **NOT RUN successfully**. Bundled render_docx.py was
  attempted but bundled LibreOffice soffice is absent. No installed desktop
  Office/LibreOffice or online conversion was substituted. XML/text checks do
  not prove DOCX layout, opening or printing.
- Native Tauri GUI/installer/clean-Windows/offline physical acceptance: **NOT
  RUN** here. Browser harness uses the actual React feature and local API with
  a synthetic boot session; it does not prove native lifecycle/WebView2/install.
- Native sidecar after module wiring: **NOT RUN**, coordinator/packaging must
  include both JSON templates, build the frozen binary and smoke purchase/sale.
- PDF goods use numbered prose because core supports one table only after all
  paragraphs. Long text flows across pages. The long fixture's two signature
  blocks land on consecutive pages; no keep-together/block controls exist yet.
- The bridge pins source line index within a version. Persistent cross-version
  line IDs are not in the frozen core DTO; source refresh must be reviewed.
- No old CRM source/templates/data/DB were read or copied. Domain text, arithmetic
  and adapter code are original. No new dependency was added. Existing
  python-docx/ReportLab/lxml/Pillow and Noto Sans licenses/notices come from core;
  the foundation's unresolved native lxml/iconv distribution gate still applies.
  PDF embeds the bundled Noto font; DOCX references Noto Sans and can substitute
  fonts in a viewer. Templates are user-editable and have no legal-validation
  claim.
- Working tree has one generated untracked `.vite/` cache outside the allowlist.
  It is excluded from all commits. Its removal was rejected by automatic approval
  review (`blocked by policy`); no alternative deletion was attempted.

Commit order and final working-tree status are supplied in the chat handoff so
the last documentation commit does not need to contain its own hash.
