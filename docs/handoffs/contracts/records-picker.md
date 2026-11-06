# Records search selectors in contracts

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin`; branch `codex/cafe-fin-contracts`. This frontend increment follows `598cfc6` and was verified with the parent's per-request records factory backend at `3fba826da4e7c7d5d87e278b043599667ce74605`. It supersedes the UUID-input limitation recorded in the earlier frontend handoff.

The source section now searches saved parties and weighings by familiar text. Users enter a name/code or explicitly search an empty string to browse one page. Each request uses shared `api()` with `page`, `page_size=50` and UTF-8 encoded `search`. Search runs on Enter/the search button, not on every keystroke. Pagination fetches one new server page and never concatenates or downloads the full list. The result table scrolls within 320 px, keeping the manual form accessible below it.

Party rows show code/name; weighing rows show code/date/line count. Full UUIDs are neither displayed nor required as input. When two rows on the current page share the same displayed identity, an eight-character suffix distinguishes them; the full ID remains the internal row/selection key. Choosing a row calls the existing contracts typed source bridge with that actual ID. Party details still require the existing old/source confirmation; weighing details still require explicit line selection. List metadata is never copied directly into a contract. There are no source writes or automatic saves.

`RecordSourcePicker.tsx` owns only one page of results. It verifies pagination metadata and the requested 50-row limit before displaying a response. Shared session AbortSignal fencing plus an owner generation and monotonically increasing query sequence prevent a delayed old search, error or finalizer from overwriting newer results or another actor's state. An unmounted selector ignores outstanding work. A source-list 403, 404 or other error produces a local warning with the manual alternative and does not disable contract entry, save or export.

No production records, backend, core, registry, shared frontend or dependency files were modified by this increment. The browser server contains synthetic `/records/parties` and `/records/weighings` fixtures only; both require the authenticated request's `records.read`. They reject page sizes above 50. Explicit authenticated test controls model unavailable records responses and the existing PDF failure seam. No records production code is imported or cherry-picked.

## Verification

- PASS `node frontend/node_modules/@playwright/test/cli.js test --config tests/contracts/playwright.config.ts`: **1 complete real Chromium flow, 21.9 s** (test body 20.4 s), 1600×1050 viewport. This uses a fresh temporary Runtime and real contracts database/auth/files/renderers; source lists/read bridge are synthetic fixtures.
- The flow searches Vietnamese text containing `&`, verifies decoded/encoded query values and `page_size=50`, displays 50 rows on page one and two records on page two, and selects distinct real UUIDs sharing the same name/code/date. It checks typed bridge calls and the IDs actually saved in source references. Cancelling the first party confirmation preserves the manual draft. Selected weighing kg remains editable without changing its source.
- Both 403 and 404 list failures are exercised for both party and weighing selectors. Each failure state is followed by an actual manual save/export. Word and PDF succeed under 403; under 404, the existing controlled PDF failure preserves Word and is retried successfully from the same snapshot. These deliberately create two versions; retry does not create a third. The manual sale has no source references.
- The same flow rejects malformed pagination, holds an old search response while a newer search finishes, and proves the late response cannot replace the latest page. It also holds actor A's source query across login to a second real local operator B, then verifies B starts with an empty draft/query/results. All observed records requests are read-only.
- Existing uncertain-create exact retry, purchase/sale, terms/payment/tax, immutable old snapshot, independent files, and attachment-content download assertions remain. The attachment check still verifies HTTP success, original PDF bytes, SHA-256 response header and original download filename. No browser JavaScript page errors occurred.
- PASS `cd frontend; npm run typecheck` before the final scroll refinement; PASS `cd frontend; npm run build` after that refinement includes TypeScript checking again. The unchanged foundation shell retains its known 932.79 kB / gzip 305.06 kB chunk-size warning. Registry integration remains coordinator-owned; the real Vite browser harness exercises this feature directly.
- PASS `.venv/Scripts/ruff.exe check tests/contracts/browser-server.py`; PASS `git diff --check`.
- Parent-reported aggregate backend verification, unchanged backend `3fba826`: `.venv/Scripts/python.exe -m pytest tests/core tests/contracts -q` **PASS 229 tests / 91.22 s** (98 core + 131 contracts), with one existing Starlette/httpx deprecation warning. This count is the parent's backend run, not a substitute for the browser evidence above.

## Inspected screenshots and limits

The new synthetic screenshots are ignored test outputs in:

`C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin\tests\contracts\test-results\browser-real-contracts-UI--0029d-ies-sources-and-attachments\`

`party-source-picker.png` and `weighing-source-picker.png` were opened and inspected after the final successful run. Both show readable code/name/date, two ambiguous page-two records with suffixes only, explicit row actions, total count and pagination without clipping. `desktop-records-picker.png` supplies the surrounding editor context. Existing editor/preview/independent-file evidence is regenerated by the same full flow.

Native Windows installer testing and root shell/records integration are outside this frontend increment. The test validates source-list behavior through authenticated synthetic list endpoints; the parent's factory tests separately cover fresh principals and lazy production provider binding. The earlier blocked `.vite` cache cleanup was not retried or included in this commit.
