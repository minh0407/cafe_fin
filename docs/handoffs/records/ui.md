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

At the original v1/v2 evidence point, the test-only Vite host bound **127.0.0.1:80**, served actual HTTP at
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

## Read bridge v2 follow-up

Applied against the coordinator-approved core bridge v2 (`1cd2da5` locally),
following `docs/handoffs/foundation/read-bridge-v2.md`. The feature's
`InventorySummary` now types `breakdown_version: 1 | null` and nullable
`movement_breakdown` with eight explicit string components. The canonical UI
table uses those fields directly, grouped into purchase/sale, production,
transfer and adjustment. It scrolls horizontally on narrower windows. The old
HTTP `breakdown` extension is retained in the response type but is not used to
infer this classification.

Null, absent or unsupported classification shows an explicit unknown warning;
the UI does not substitute zeroes or treat unclassified movements as purchases.
The `inventory_movement_classification_unknown` flag is translated for the user.
The `opening_entries_in_adjustments` flag explains that opening entries within
the selected period appear in adjustment increases, rather than purchases.

V2 verification supersedes the earlier feature-build/browser timings above:

- `npm --prefix frontend run typecheck`: PASS.
- `node tests/records/browser/build-feature.mjs`: PASS, 12 modules,
  54.60 kB / 14.05 kB gzip, 190 ms.
- The same real-API browser command: PASS on its first v2 run, 1 test,
  18.4 seconds test / 19.9 seconds total. In addition to the existing desktop
  workflow and retry proof, the test verifies the real summary's v2 version,
  all eight component values for its product/warehouse scope, all eight UI
  component headers and the purchase/sale figures. No domain API mocking.
- Scoped `git diff --check`: PASS.
- The final v2 screenshot at the same ignored proof path was opened and checked.

The runtime-generated unknown-classification and opening-entry flag branches
were reviewed in source; this browser fixture does not manufacture unknown
legacy ledger data. Provider classification/cutoff coverage remains the parent
lane's API tests. Native and registry integration limits above still apply.

## CI harness port recovery

Windows CI run42260894313 passed backend279 and regular UI11, then failed this
feature harness setup because runner IIS/service already owned port80. The
fixture now uses dedicated Vite loopback1421, strictPort=true, HMR=false,
baseURL=http://127.0.0.1:1421, readiness URL=/records-test and
reuseExistingServer=false. It neither stops an existing process nor silently
chooses another port. CAFE_FIN_RECORDS_TEST_PORT optionally overrides the port;
settings.mjs accepts integer digits1..65535 and always builds a127.0.0.1 origin.
The Python child validates the numeric port independently before initialization.

The production factory's startup allowlist remains unchanged. In the isolated
test child only, a narrow unittest.mock.patch supplies the exact fixture origin
while constructing the test app, then restores the production constant by
identity before serving requests. The actual ScopeGuard/CORS/auth and domain
handlers still run; no API response or browser request is mocked/proxied. The
browser test checks the real matching CORS header and a non-fixture origin403.
No app source, production Origin/CSP policy or native acceptance claim changes.

Local port-recovery validation:

```powershell
frontend/node_modules/.bin/playwright.cmd test --config tests/records/browser/playwright.config.mts
# PASS:1 test17.7s /19.7s total, real browser/API/file-backed SQLite WAL.
.venv/Scripts/ruff.exe check tests/records/browser/server.py
# PASS
.venv/Scripts/python.exe -m compileall -q tests/records/browser/server.py
# PASS
git diff --check
# PASS
```

Actual settings imports in independent Node subprocesses reject7 invalid port
inputs and accept1/1421/65535. The browser keeps all v2 classification, stock,
weighing history and retry proofs; it additionally verifies the page's actual
origin. CI recovery is still for root after cherry-pick; this is local evidence.

## Vietnamese business date adoption

Prerequisite: root-approved shared DateInput commit
6098a1111432995ed5b6be96fd0650af382a15e2, applied unchanged as local999b2a6.
The shared five-file cherry-pick includes the direct Day.js1.11.23 pin; the same
version was already installed transitively. The lane did not modify shared code,
package/lockfiles or the approved widget tests after cherry-pick.

Records now uses DateInput for the required weighing/entry occurred_on Form date,
optional list filters, required inventory/movement ranges and required receivable
as-of date. Form integration includes both required and dateInputRule. Non-Form
parents retain invalid/partial draft text, gate enabled/refetch and revalidate in
queryFn before calling api. A clear optional filter removes that filter; a clear
required report date blocks its query. Invalid filter drafts are removed from
the URL while retained visibly in state. Date-only readback uses DD/MM/YYYY
without Date/UTC conversions. occurred_at remains its explicit timestamp Input.

The real browser harness now submits the ambiguous display06/11/2026 and checks
saved/request ISO2026-11-06 and DD/MM detail/copy readback. Before saving, it types
31/02/2026 over a valid date, tries Ctrl+Enter, verifies the raw draft/error and
zero actual POSTs/zero saved weighings, then corrects and saves. It also checks
that invalid dates in optional list filters, inventory, movement and receivable
views retain raw text/aria-invalid and create no new GETs. List reload is disabled;
clearing optional dates and correcting dates issue only valid ISO queries. The
same-day inventory range still includes both receipt and issue (through_on inclusive).

Validation after the feature and harness were frozen:

```powershell
npm --prefix frontend run build
# PASS: typecheck+shell build, existing932.79KB/gzip305.06KB chunk warning.
node tests/records/browser/build-feature.mjs
# PASS: actualfeature28 modules79.58KB/gzip21.59KB,305ms.
frontend/node_modules/.bin/playwright.cmd test --config tests/records/browser/playwright.config.mts
# PASS:1 realbrowser/API/WAL test19.1s /20.6s total on loopback1421.
git diff --check
# PASS
```

The final screenshot was opened and visually checked: both range controls show
06/11/2026, the known closing90.124kg and v2 component table remain correct. A
read-only source review found no missing date guard or stale-date path. The shared
widget's independent11 cases are root's prior evidence, not claimed as rerun by
this lane. Backend tests are not rerun for this UI-only adoption; no backend/API/
migration semantics changed. CI recovery and native acceptance remain root gates.
