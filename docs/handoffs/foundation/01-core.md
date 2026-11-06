# Foundation increment 01 — exact types, registry, serialized writes

Baseline: `cafe-fin-spec-v1` / `5925d43964e99033efe3146ae4d84902dd284df3`.
Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-foundation-build\cafe_fin`.
Branch: `codex/cafe-fin-foundation-20261106-build`.

This is an incremental candidate, not a foundation READY gate. No production domain modules.

## Public surface

- `core.amounts`: Decimal-string money (scale 2), kg (scale 3), int64 checks and exact Python-integer aggregate. Excess precision fails; no rounding or float coercion.
- `core.time`: UTC timestamps and Vietnam day boundaries independent of host timezone.
- `core.modules`: typed manifest, explicit dependency order and namespaced migrations. Register only trusted source modules; no executable disk plugin discovery.
- `Database.migrate`: new SQLite schema, contiguous namespace versions, rejects unregistered/newer or changed migration identities. Migration SQL belongs to each module. Use an explicit `checksum` when freezing production migrations; default fingerprint identifies namespace/version/name, not function source.
- `WriteCoordinator.run(fn)` gives one SQLAlchemy `Connection` in a short `BEGIN IMMEDIATE` transaction. Queue is bounded; commit/rollback is owned by core. `barrier(fn)` serializes maintenance without a write transaction. Do CPU, file parsing, rendering and network work outside `run`.
- `WriteCoordinator.execute(actor, action, request_key, payload, fn)` persists canonical-payload hash and JSON result in the same transaction; replay survives engine restart and conflicting payload returns `IDEMPOTENCY_CONFLICT`.
- `AuditService.record(conn, ...)` writes before/after alongside the mutation; `require_version` enforces expected version. Secrets/passwords must never be placed in audit payloads.

Schema increment: `core_schema_migrations`, `core_requests`, `core_audit`. SQLite WAL, foreign keys, synchronous FULL, busy timeout 10s. Runtime guard requires SQLite >=3.51.3 and rejects withdrawn 3.52.0. This machine's selected runtime is Python 3.12.16 / SQLite 3.53.1; system Python 3.12.10 / SQLite 3.49.1 is intentionally rejected.

## Actual validation (Windows 11 Pro 10.0.26200, 34,138,931,200 bytes RAM)

- PASS: `.venv\Scripts\python.exe -m pytest tests/core/test_foundation.py -vv -s -o faulthandler_timeout=15`: 5 passed, 0.44s. Real SQLite temp databases; 24 concurrent commands, rollback of mutation+audit, idempotency replay after reopen, migration downgrade/change checks, exact scaled boundaries and Vietnam date.
- PASS: scoped `ruff check` and `git diff --check`.
- NOT RUN in this increment: API/local auth, jobs/process crash, storage/backup/restore, renderer/grid and app/installer smoke. They belong to subsequent foundation increments.
- Native prerequisite probe FAIL: installed Visual Studio is incomplete; `vcvarsall.bat`, VC headers/runtime libs and Windows SDK are absent. A standalone Rust hello probe cannot find configured linker. Adding PATH is insufficient. Coordination is repairing the toolchain separately.

## Development

Use Python 3.12 with a supported bundled SQLite, then `uv sync --locked` and `.venv\Scripts\python.exe -m pytest`. Exact direct pins and all transitive hashes are in `pyproject.toml` / `uv.lock`. Python downloaded for this session is under `%TEMP%\cafe-fin-foundation-tools\python\cpython-3.12.16-windows-x86_64-none\python.exe`.

Remaining gates and evidence will be consolidated in this directory before any baseline proposal. This increment does not authorize module lanes to start and creates no tag.
