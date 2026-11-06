# API, IPC and synthetic workbook proof

Baseline/worktree/branch are in `01-core.md`. This remains a candidate, not READY.

## HTTP and IPC v1

`core.api.create_app(runtime, session_token, port, origin)` binds no socket itself.
The sidecar entrypoint owns a `127.0.0.1:0` socket and passes the allocated port.
Every HTTP request requires exact Host and an app-session header; business routes
also require an opaque memory-only local-user bearer token. Only the selected
allowlisted Tauri/dev origin passes CORS. No LAN listener, OAuth, cookies,
localStorage secret, shell command or arbitrary path endpoint is introduced.
Command bodies are bounded to 2 MiB before a handler may mutate.

`backend/cafe_fin/__main__.py` reads one UTF-8 JSON line from stdin, bounded to
64 KiB: `protocol_version=1`, `session_token`, absolute native-selected
`data_root`, explicit `initialize`, `allowed_origin`. The boot token is validated
before creating data. stdout returns only a ready/error JSON handshake, without
the token or filesystem paths. Port/health startup is managed by Tauri, deadline
20 seconds. stdin shutdown JSON or pipe EOF closes jobs/writer/DB and releases
the data-root lock. Console-enabled sidecar preserves pipes; Tauri launches it
with CREATE_NO_WINDOW. Graceful-shutdown failure has a sanitized stable code.

Health checks the actual SQLite connection and runner liveness/error state.
No `navigator.onLine` gate is used. Request IDs are server UUIDs. Validation
errors exclude input values, secrets and exception text. Rotating logs record
only stable failure codes and request IDs, not bodies/tokens/documents.

`core/http_types.py` and exported `openapi-v1.json` describe actual HTTP response
schemas, error envelopes and AppSession/LocalUser security. Regenerate using
`.venv\Scripts\python.exe scripts/export_openapi.py`; it uses only a temporary
synthetic root. The spec is a candidate contract for coordinator review.

## Module registration

Coordinator-owned `backend/cafe_fin/registry.py` is the only default backend
manifest registration point. Core orders dependencies and applies namespaced,
checksummed migrations. A registered router automatically needs `<module>.read`
for reads and `<module>.write` for mutations; its mutation must also pass an
`AuthService.authorize` callback into the writer transaction.

`core/example.py` is a synthetic scratch-note module demonstrating registration,
migration, route permissions, audit, request replay and optimistic version
conflict. It is Admin-only by default and is not stock/accounting/contracts.
Lanes deliver their own `module.py` manifest; coordinator adds it to the registry.
Frontend registration remains the typed list in `frontend/src/app/registry.tsx`.

## Two technical proofs

`/spikes/grid` reads a real generated XLSX through openpyxl 3.1.5 (MIT), with
defusedxml 0.7.1 (PSF) and et-xmlfile 2.0.0 (MIT). Original bytes enter FileStore
unchanged with a stable SHA-256. The 10,000-row, five-column synthetic workbook
contains Unicode, Excel dates, leading-zero text codes, an exact large amount
stored as text, and formulas. Reader is read-only, `data_only=False`, external
links disabled; it never evaluates formula caches or VBA and never resaves the
source. Pages contain at most 500 rows. UI editing is explicitly a draft.

The proof reader caps ZIP entries/uncompressed size and source bytes and only
supports this known synthetic sheet/schema. Later pages may rescan worksheet
XML. It is not the accounting production reader, formula engine, staging system
or 500k/1m benchmark. It has no general upload endpoint.

The opaque macro test is an XLSX ZIP with a harmless, non-executable
`vbaProject.bin` marker and external-link member: it proves byte preservation
and ignored archive members, not executable VBA fidelity or a real macro project.

`/spikes/documents` exports DOCX and PDF independently from the same frozen
synthetic snapshot. Files/receipts are durable; repeating the export request key
returns the original IDs/hashes, without relying on newly rendered ZIP/PDF
timestamps. Authenticated downloads expose only file IDs. Error in one format
does not remove the other. These are capability proofs, not legal templates or
contract numbering/domain workflows.

## Actual validation

- Commit `5b3fb4c29131f7b72727d876dc053c894abe7454`: exported to a clean Git archive
  under `%TEMP%\cafe-fin-core-5b3fb4c-97f214c18134477b9793a81ca9e3f3fb\source`;
  fresh `uv sync --locked`; tracked core suite **57 PASS / 11.57s**. This fixes the
  earlier incremental snapshot's untracked storage dependency.
- API/IPC/workbook scoped suite **5 PASS / 9.49s** in the working tree before this
  increment: real loopback processes, raw UTF-8 Unicode root, second instance
  refusal/restart, absent root not recreated, invalid boot token creates nothing,
  CORS/Host/session/user guards, payload limits, module CRUD/version/audit,
  workbook values/coordinates/paging, opaque-source preservation, actual PDF/DOCX
  downloads and hashes. Starlette emits one httpx TestClient deprecation warning.
- PDF rendering and prior frozen executable proof are recorded separately in
  `storage-render.md` and `sidecar-build.md`. Current native execution/installer
  is blocked by Windows Application Control; no clean-Windows claim is made.
