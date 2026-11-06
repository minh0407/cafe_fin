# Contracts frontend handoff

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin`, branch `codex/cafe-fin-contracts`. Frontend started from foundation baseline `e668355`; browser verification used frozen backend `8d3a516a062e19186131e3a7b58350ed9f051d7e`.

The feature manifest is `frontend/src/features/contracts/index.ts`, named export `contractsModule` (also default). Its interface matches `FeatureModule`; `/contracts` renders `ContractsPage`. Coordinator must replace the placeholder contracts entry in the shared app registry. No shared source, dependency manifest or lockfile was changed. The scoped `tests/contracts/package.json` only marks the browser harness as ESM; it adds no dependencies.

Implemented a Vietnamese desktop list and controlled editor for manual purchase/sale contracts, party details, representatives/authorization, contacts, bank accounts, many goods/weighing rows, all delivery/quality/packaging/deadline/responsibility/additional terms, all payment methods, receiving account, deposits, recorded payment and installment schedules. Tax mode remains an explicit user choice. All money/kg remain strings; only backend preview calculates totals. Decimal grouping is display-only string manipulation.

The editor supports optional typed party/weighing source bridges. Party replacement shows existing/source information before applying. Weighing source lines are selected explicitly; editable contract values and original source snapshot stay separate. Re-selecting the same weighing line is blocked in the UI to avoid counting it twice. An unavailable bridge leaves manual entry usable. Source lookup currently uses UUID input, rather than a records search picker; no records write API is called.

Save uses optimistic versions. An uncertain network/body/upload result holds the exact serialized request/key and freezes editing until the same command is retried; a lost committed-create response was exercised against the real backend. Session generations remount all draft/history/pending state, callbacks check their owner, and downloads check the owner before creating a local link. Unauthenticated rendering produces a sign-in message without starting repeat unauthorized requests.

Preview shows backend-calculated totals and safe text. Export keeps DOCX/PDF status/error/download actions independent. Missing/failed formats can be retried from the same snapshot. Old snapshots render read-only from their stored document, totals and template metadata. History and attachments have server pagination. Optional signed/scan attachments retain original bytes through the shared upload/download API, with user-recorded signature wording. The UI also exposes versioned template edits to permitted admins and soft delete/restore with preserved exports.

## Verification

- PASS `cd frontend; npm ci --ignore-scripts --no-audit --no-fund` (existing locked dependencies only).
- PASS `cd frontend; npm run typecheck` after final product changes.
- PASS `cd frontend; npm run build` after final product changes. Existing shell bundle warning remains: 932.79 kB, gzip 305.06 kB, over Vite's 500 kB warning threshold. Registry wiring is intentionally left to the coordinator; TypeScript checked this feature and the browser harness exercised its real Vite-transformed code.
- PASS `.venv/Scripts/ruff.exe check tests/contracts/browser-server.py`; its import order/format were corrected.
- PASS `node frontend/node_modules/@playwright/test/cli.js test --config tests/contracts/playwright.config.ts`: **1 real Chromium flow, 14.6 s** (test body 13.1 s), viewport 1600×1050. Harness creates a fresh temporary Runtime with the real module manifest, HTTP/session/auth/files/database/renderers. Only synthetic read-bridge data and a controlled PDF renderer failure are test seams.

The browser flow covers manual purchase and sale; keyboard Tab from number to date; exact request/key retry after the real create committed but its response was lost; locked native/AntD controls during uncertainty; preview with unspecified tax; DOCX/PDF export/download; source replacement confirmation, selected weighing and editable kg override without changing the source; source revision plus contract edits followed by old snapshot/hash retrieval; actual PDF-byte attachment; mixed payment/installment/exclusive tax; independent PDF failure keeping DOCX usable; PDF retry with exactly one immutable version; logout clearing private draft/output. No JavaScript page errors occurred.

Earlier harness iterations identified an unsupported TXT attachment fixture and AntD's non-pointer combobox input. The final fixture uploads an actual generated PDF, and Select interactions click the visible wrapper. Both were harness repairs; the final full flow passes. No app permission or approval workflow was added.

## Visual evidence

Synthetic browser screenshots are local ignored outputs, not committed. Full absolute directory:

`C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin\tests\contracts\test-results\browser-real-contracts-UI--0029d-ies-sources-and-attachments\`

- `desktop-editor.png`: desktop list, action bar, template/type, identity/date/place and both parties.
- `desktop-preview.png`: backend totals, unspecified-tax notice and full Vietnamese contract text.
- `desktop-independent-files.png`: sale history, separate successful DOCX/failed PDF, recover action, tax/payment totals and immutable document.

All three were inspected as images. Text and controls fit the desktop columns; Vietnamese text wraps without clipping. History/table controls remain readable, and independent format errors are visible. Full-page captures start at scroll top to avoid a sticky-actionbar screenshot artifact. This is browser UI evidence, not native installer or DOCX/PDF page-layout certification; the backend lane owns document artifact QA.

## Remaining integration and limitations

Coordinator registry wiring, native desktop smoke and clean Windows installation are NOT RUN in this frontend subtask. Template edit and soft delete/restore UI compile and use the verified API, but are not separately exercised in this one browser flow. Source refresh never silently replaces an edited weighing line: remove the old line/link and explicitly select the desired source version. The UI has no direct records search/list dependency and no money/stock side effects.

Vite cache was moved to ignored `frontend/node_modules/.vite/contracts`. An earlier run left an untracked repo-root `.vite` cache. Cleanup was NOT RUN: automatic approval review rejected a native PowerShell `Remove-Item -LiteralPath $contractsCache -Recurse -Force` command after path containment validation, with message **`blocked by policy`**. No deletion occurred, no bypass was attempted, and this cache is not staged or committed.
