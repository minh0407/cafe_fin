# Contracts shared DateInput adoption

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin`; branch `codex/cafe-fin-contracts`. Uses the approved foundation DateInput change `6098a1111432995ed5b6be96fd0650af382a15e2`, applied by root as `c2b8873`. This lane changes only contracts feature code, its browser spec and this handoff. Backend, shared source, dependency manifests and lockfiles are unchanged by this increment.

`Field` now renders shared controlled `DateInput` for ngày lập, hạn thanh toán and each payment installment date. Valid input displays `DD/MM/YYYY` and enters the draft as ISO `YYYY-MM-DD`. Invalid or partial text goes directly into the controlled draft without retaining an older ISO date. Only an intentional empty optional date uses the existing empty-to-null conversion. The field shows a linked inline error for invalid dates and blank required dates. Schedule dates are explicitly required; the top-level contract date remains required.

The field passes `ConfigProvider.useConfig().componentDisabled` explicitly to DateInput. This freezes both text and the shared calendar button/Popover during pending commands, including uncertain-save retry. A native disabled fieldset is not used as the sole protection for calendar controls.

The non-Form workspace explicitly calls `contractDateIssues()` before constructing or sending save, preview and current-contract export commands. It checks required `occurred_on`, optional nullable `payment.due_on`, required `payment.schedule[].due_on`, and optional nullable `lines[].source.occurred_on`. Invalid copied source metadata produces a field-specific global error; it cannot be sent merely because that source date is read-only. The TypeScript source date type now permits null, matching the existing backend schema. No wire schema changed.

Validation switches to the editor and lists each date issue without changing the raw draft. Current export runs this validation before its existing selected/dirty guard; it does not rely on the button's disabled state. Historical format retry and downloads remain operations on their immutable version. They transmit no current draft dates and acquire no new current-draft validation gate. No contract date filters existed, so none were added. Date-only API values are never converted through timezone offsets or JavaScript Date rollover.

## Final verification

- PASS `node frontend/node_modules/@playwright/test/cli.js test --config tests/contracts/playwright.config.ts`: **3 browser tests / 27.8 s**, one Chromium worker at 1600×1050.
- The existing full real Runtime/API/source/file/security flow passes in **19.3 s**. It retains all picker paging/search/duplicate-ID/403/404/race assertions and attachment original-byte/hash/filename checks. Calendar buttons are asserted disabled during uncertain create retry. The installment is entered as `20/11/2026`; the actual exported backend snapshot is asserted to contain `2026-11-20`.
- The controlled-draft date regression passes in **4.4 s**. Starting from valid saved ISO dates, impossible required/optional dates, partial text and blank required dates produce **zero save/preview requests**, retain exactly the raw text and expose `aria-invalid`. Correction sends new ISO dates rather than the prior ISO. Clearing the optional due date sends null; typing an impossible date after that clear cannot silently send another null. Choosing a day from the integrated calendar changes the controlled display without sending a command, then save sends its ISO value. Required installment dates receive the same invalid/partial/empty and corrected-ISO checks.
- The current-export guard regression passes in **2.5 s**. It loads pristine persisted data with each required, optional, installment or copied-source date malformed. Export is enabled because the draft is pristine, yet clicking it produces **zero export requests** and a field-specific error. Genuine null optional payment/source dates remain valid and can export. These two focused regressions use explicit HTTP fixtures for deterministically malformed persisted data; they do not replace the full real API flow above.
- PASS `cd frontend; npm run typecheck` after adoption and the initial focused regression corrections.
- PASS final `cd frontend; npm run build`, including TypeScript checking after all product changes. Existing unchanged foundation shell chunk warning remains: 932.79 kB / gzip 305.06 kB. Coordinator registry integration is still separate; the browser harness loads this feature directly.
- PASS scoped staged `git diff --check` before commit. No additional backend suite was run because backend code is unchanged. Root owns the independent shared DateInput test suite.

The first raw-draft test iteration used exact label matching against a required label containing its visual asterisk; the locator was corrected and the final complete suite passes. There is no remaining test failure or date API interface gap.

## Visual evidence and limits

The regenerated ignored screenshot was opened and inspected:

`C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin\tests\contracts\test-results\browser-real-contracts-UI--0029d-ies-sources-and-attachments\desktop-editor.png`

It shows the new `DD/MM/YYYY` date text with clear/calendar controls fitting the existing desktop editor. No screenshots or operational data are committed. Native installation and clean Windows release checks remain outside this frontend adoption. The legacy untracked `.vite` cache was left untouched; its previously rejected cleanup was not retried.

## Shared disabled-context follow-up and dedicated harness port

Approved shared fix `3aa94c601dbf878f07b46b0902fc71b0f388c40c` was cherry-picked
locally as `47689a4`, exactly its three shared/test/foundation-handoff files. It
inherits public disabled context, closes an open calendar and fences stale
callbacks. No additional shared/component edits were made by the lane.

The contracts-only browser harness now uses fixed port **1422** consistently for
Vite strictPort, Playwright baseURL/readiness, HTTP-fixture CORS and the real test
API's bound origin. `reuseExistingServer` remains false. There is no arbitrary
environment-origin override. Production desktop/dev port 1420, CSP, origin
allowlist, core source and API semantics are unchanged.

The production create_app bootstrap only permits Tauri and dev1420, so the first
1422 attempt failed with BOOT_PROTOCOL_INVALID before its real Runtime flow could
start (the two HTTP-fixture date regressions passed). The test-only Python helper
now temporarily adds exactly `http://127.0.0.1:1422` to the exported allowlist with
`unittest.mock.patch.object` solely during create_app construction, restoring the
production value immediately afterwards and before serving. Actual ScopeGuard,
authentication, request handling and CORS enforcement are not mocked: the real
flow asserts that origin1423 receives403 without an allow-origin header, whereas
the bound origin1422 receives200 and its exact allow-origin header. This fixture
allowance is not production bootstrap-origin acceptance evidence and ships only
under tests/contracts.

Latest verification after the approved shared fix:

```powershell
node frontend/node_modules/@playwright/test/cli.js test --config tests/contracts/playwright.config.ts
# PASS: 3 tests /26.0s; real Runtime flow17.4s, raw-date guard4.7s, export guard2.2s.
npm --prefix frontend run typecheck
npm --prefix frontend run build
# PASS; existing932.79kB/gzip305.06kB shell chunk warning remains.
.\.venv\Scripts\python.exe -m ruff check tests/contracts/browser-server.py
.\.venv\Scripts\python.exe -m ruff format --check tests/contracts/browser-server.py
git diff --check
# PASS.
```

The lane did not rerun root's reserved-port shared13-case suite or unchanged
backend suite. The appropriate contracts consumer flows above were rerun with
the exact approved shared fix. Only tests/contracts and this handoff change in
the dedicated-port increment; no feature was added.
