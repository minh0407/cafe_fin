# Docker local browser preview — 07/11/2026

Preview lane worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-docker-preview\cafe_fin`.
Branch: `codex/cafe-fin-docker-preview-20261107`; reviewed parent
`f4a6167846625989bd24dbc4b3bad6036f6311a8`. Coordinator owns integration/push.

This is an optional local testing surface around the real SQLite runtime and
registered business modules. It is not the Windows installer/release gate.
There are no schema migrations or copied CRM data in this change.

## Run

From the repository root with Docker Desktop's Linux engine running:

```powershell
docker compose -f compose.preview.yaml build
docker compose -f compose.preview.yaml up -d
docker compose -f compose.preview.yaml ps
```

Open **http://127.0.0.1:1420**. Use exactly that address; `localhost` is rejected.
Create your own local Admin on the initial page; no default account/password is
provided. No Google login is involved. The named volume
`cafe-fin-local-preview_preview-data` persists users, DB, uploads and exports
across container replacement. No host files, old CRM or credentials are mounted.
Use synthetic data for testing. Close the UI and stop normally with:

```powershell
docker compose -f compose.preview.yaml down
```

This keeps the data volume. Do not add `--volumes` unless intentionally deleting
all preview data. If port 1420 is occupied, stop the other preview first; the
canonical host/origin is deliberately fixed, not remapped through a public proxy.

## Boundaries

- One nonroot container (uid/gid 10001), read-only image, bounded `/tmp`, named
  data volume, dropped capabilities and `no-new-privileges`. Docker initializes
  the empty volume from the image-owned `/data` directory.
- Compose publishes only `127.0.0.1:1420:1420`; the internal Docker network has
  no WAN egress. The container listener needs `0.0.0.0` inside that network.
- The adapter rejects other/duplicate Host or Origin headers before dispatch.
  Bootstrap is a narrow POST with `X-Preview-Bootstrap: 1`, exact same-origin
  Fetch Metadata when present, no query, no CORS/preflight allowance. All HTTP
  responses receive no-store/nosniff; static files are only `/` and `/assets/*`.
  There is no raw data-root/path API.
- A cryptographically random application session token is created per process,
  exchanged only via that bootstrap and retained in process/frontend memory.
  It is absent from image/env/URLs/disk/browser storage/logging. API operations
  still need the original session header and local-user bearer authentication.
  A reload reconnects; the Windows-only restart action remains unsupported.
- `create_app`, its ScopeGuard/allowed origins/auth, native entrypoint and actual
  lifespan remain unchanged. The outer dispatcher delegates API and lifespan;
  runtime start, recovery, module workers and close are real.
- Initialization happens only when the marker is absent and the data directory
  is truly empty. Existing marked data is opened normally. Unmarked nonempty,
  incomplete or held/restoration data fails closed; it is never replaced by an
  empty DB. Preview bootstrap does not claim native maintenance capabilities.
- Browser preview is explicitly compiled with
  `VITE_CAFE_FIN_BROWSER_PREVIEW=1`. Normal frontend builds continue using Tauri
  IPC. No Tauri internals are faked. Native folder picking, restarting, opening
  folders and backup/move/restore reject with a Vietnamese limitation message.
- Windows Credential Manager is unavailable on Linux. Telegram remains
  UNCONFIGURED, with no plaintext fallback and no preview sending. Local report
  generation/download, uploads, accounting grid/import and contract APIs remain
  the real business implementations. The banner makes these limits visible.

## Build and source hygiene

The multi-stage build uses official Node 24 and Python 3.12.16 bookworm-slim
images plus Astral uv 0.11.19, all pinned by verified registry manifest digest.
Verification used `docker buildx imagetools inspect` on 07/11/2026. `npm ci` and
`uv sync --frozen --no-dev --no-editable` consume the existing lockfiles without
dependency upgrades. The Python wheel carries the existing Noto fonts/licenses;
the image also includes generated notices from installed locked frontend tools.
Linux wheel license audit is still a separate distribution/release concern.

`.dockerignore` denies by default and admits only backend code/assets, minimal
frontend build inputs, lock/manifests and preview script. Git, environment files,
runtime, databases, workbooks, local logs, dev environments, build outputs and
private documentation never enter the Docker build context.

## Validation at lane handoff

PASS:

- `python -m pytest tests/preview -q`: 12 cases with real SQLite/ASGI lifespans;
  host/origin/cross-site/bootstrap rejection, two auth layers, own Admin setup,
  reopen and capability rotation, no capability on data-volume disk, upload and
  download, actual DOCX/PDF generation, static traversal/native route rejection,
  unavailable Linux credential adapter (simulated on Windows), UNCONFIGURED
  connection check, rejected secret save and zero Telegram transport calls.
- `python -m ruff check scripts/preview.py tests/preview`.
- Targeted regression command `python -m pytest tests/preview
  tests/core/test_api_sidecar.py tests/core/test_api_recovery.py
  tests/core/test_secrets.py -q`: 43 PASS, including the 12 preview cases.
- `docker compose -f compose.preview.yaml config --quiet`.
- `npm ci`, normal `npm run build`, and
  `$env:VITE_CAFE_FIN_BROWSER_PREVIEW='1'; npm run build` in frontend.
- Playwright frontend adapter probe: valid bootstrap, four malformed boot
  rejections, nine unsupported native commands, no browser storage/Tauri shim,
  preview banner, first Admin page and session header to real API client.
- `git diff --check`.

The reusable equivalent frontend probe is `tests/preview/browser_bridge.mjs`.
Its syntax check passed; the persisted file was not rerun while Docker took over
port 1420. To rerun it, stop Docker preview, start Vite in `frontend` with
`VITE_CAFE_FIN_BROWSER_PREVIEW=1`, then run
`node tests/preview/browser_bridge.mjs` from the root. It uses synthetic intercepted
bootstrap/health responses and does not establish Docker/backend correctness.

Environment for these lane checks: Windows PowerShell, existing Python 3.12
development environment from the foundation recovery worktree, locked frontend
dependencies installed in this isolated worktree. The FastAPI TestClient emits
an upstream httpx deprecation warning; no dependency changed to suppress it.

NOT RUN by this lane: Docker build/start, real Linux credential/runtime probe,
Docker browser business smoke, native Windows release/installer smoke and large
import benchmarks. Coordinator runs the actual container after Docker Desktop
starts and records machine/build/runtime evidence. Existing backend Windows CI
is separate evidence from preview tests, not proof of Linux behavior. No
production-ready claim is made.

Interface impact: only a separate `/preview/bootstrap` transport and explicitly
flagged frontend bridge. Existing `/api/v1` contracts and native defaults remain.
