# Records desktop UI candidate

Foundation: `cafe-fin-foundation-ready-v1`, commit
`e668355c227322994902f7e2e38ed7ffb19ff647`.
Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-records\cafe_fin`.
Branch: `codex/cafe-fin-records-20261106`.

Frontend and browser harness source frozen after the passing run on 06/11/2026.
The parent records agent owns committing these files. No push, merge or READY tag.

## Exports and behavior

`frontend/src/features/records/index.ts` exports named/default `recordsModule`
(`FeatureModule`) and `RecordsPage`. Coordinator replaces the records stub in
`frontend/src/app/registry.tsx`; this lane does not change that shared file.

The feature contains tabs for parties, products, units, warehouse/location,
manual weighings, goods entries, stock balances, stock movements and commercial
balances. Lists use bounded server pagination, search, sort and filters. Safe
display metadata (tab/page/date/type/status) is stored in the hash URL; names,
contact search and credentials remain outside that URL.

Forms support multiple party roles, optional contact/bank/representative data,
deactivation, both weighing modes, multiple goods lines and independent input /
output production lines. Explicit copy from a saved weighing opens a receipt
draft and asks for a warehouse. Saving a weighing does not change stock.

After a committed save, the detail drawer shows the returned code, version and
saved values. It can read immutable version snapshots. Commands expose explicit
post, cancel, soft delete, restore and posting a cancelled entry again; all
validation and authorization remain in the backend. No approval, QR or QC gate.

Quantity/money inputs remain strings. Formatting groups decimal text without
conversion to JavaScript Number. Form mutations whitelist mutable DTO fields,
send positive expected_version for edits, normalize incomplete draft fields to
null and preserve source-mode nulls. A failed save retains its request key for
the same payload; editing the payload obtains a new key. Local session generation
guards prevent stale requests from updating the next actor's UI.

Master reference controls search server-side with at most 50 options per query.
Historical/inactive selected references remain readable. Only master resources
receive the active filter; weighing links do not. Summary views display the
business date range, cutoff in Vietnam time and entered-records-only scope.
Production, transfer, opening and adjustment movement types remain separate
from receipt/issue totals. Commercial balances are explicitly separate from
independent cash accounting and do not claim reconciliation.

## Verification

Run from the records worktree with the foundation's locked dependencies:

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
node tests/records/browser/build-feature.mjs
.venv/Scripts/ruff.exe check tests/records/browser/server.py
frontend/node_modules/.bin/playwright.cmd test --config tests/records/browser/playwright.config.mts
git diff --check
```

- Typecheck: PASS.
- Root shell build: PASS, 932.79 kB JS / 305.06 kB gzip; existing chunk-size
  warning remains. The registry still contains the foundation stub, so this
  result alone does not prove the records feature was bundled.
- Actual feature entry build: PASS, 12 modules, 52.50 kB / 13.50 kB gzip,
  192 ms. The lane-owned build-feature.mjs outputs to a unique Temp
  directory and externalizes existing shared dependencies. No package changes.
- Python harness Ruff and git diff check: PASS.
- Final browser run: PASS, 1 test, 17.1 seconds test / 18.4 seconds total.
  Chromium runs the actual React feature, shared API/session client, real FastAPI
  records router and a fresh file-backed SQLite WAL database. No domain response
  is mocked, intercepted, replaced or proxied.

The test-only Vite host binds **127.0.0.1:80**, serves actual HTTP at
`http://tauri.localhost/records-test` and disables HMR. The backend uses the
existing allowed origin `http://tauri.localhost`; no core allowlist or browser
security setting is changed. Port 80 must be available. The test does not stop
another lane's process or use its port 1420. Python startup uses a test-only
explicit `ModuleRegistry((module_manifest(),))`, not edits to root wiring.

The browser test proves:

1. UI creation of party, warehouse and product, followed by direct-net weighing;
   missing gross/tare remain null, and stock remains empty.
2. Explicit weighing-to-receipt copy, receipt 100.125 kg, issue 10.001 kg and
   displayed/backend closing stock 90.124 kg.
3. Over-issue 1000.000 kg is rejected without creating a third goods entry or
   changing stock; validation remains visible in the editor.
4. Editing the saved weighing creates version 2 while version 1 remains visible
   in history and stock remains 90.124 kg.
5. A saved weighing is selectable from the entry's reference dropdown.
6. Two real duplicate-code POSTs return 409 with the same retained request key.
   Changing the code sends a new key and saves an incomplete draft successfully;
   its blank product/location/quantity are null and it has no stock effect.
7. Ctrl+Enter saves through the real form; no uncaught browser errors occur.

The final synthetic inventory screenshot was opened and visually checked after
waiting for the selected inventory tab, the loading mask to clear and animations
to settle. Ignored local proof:

`frontend/test-results/records/records-desktop-real-API-r-1af5f-history-and-stock-rejection/records-real-api-inventory.png`

## Remaining integration and release checks

- Coordinator registry wiring and full application cross-lane integration are
  separate from this explicit feature host.
- Native Tauri / installer / clean-Windows interaction: NOT RUN in this lane.
  Browser evidence does not replace those release gates.
- Frontend lint: NOT RUN because the frozen foundation has no frontend lint
  command/configuration. No shared lint configuration was added.
- The browser flow covers direct-net weighing and receipt/issue. Full ledger
  concurrency, backdate, delete/restore and production invariants are proved by
  the parent lane's real SQLite/API tests, not by this single browser test.
- Native date-input appearance follows the browser/Windows locale. The values
  submitted and verified are ISO business dates; Vietnam boundary validation is
  performed by the backend.

No production data, workbook, credentials, runtime database or screenshot is
committed. Only source and the synthetic test harness belong to this candidate.
