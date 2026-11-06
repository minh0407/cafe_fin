# Reporting Vietnamese date-input adoption

Approved root commit `6098a1111432995ed5b6be96fd0650af382a15e2` was cherry-picked
unchanged as `f026708` (exactly five shared files). Root already has its original
commit and should skip this local duplicate. Day.js remains the same MIT
`1.11.23` version already present transitively; only root's approved direct pin
and shared component/test/handoff were applied.

## Feature change

Reporting's two native date inputs, `from_on` and `through_on`, now use the public
controlled `DateInput`. The display is DD/MM/YYYY with a Vietnamese calendar,
independently of the Windows/browser locale. Each required Form.Item includes
both its own required message and `dateInputRule`.

Invalid/impossible or incomplete input remains the actual Form draft; it never
retains the prior ISO behind the visible text and never becomes an optional empty
date. The form blocks onFinish/preview API until corrected. Clearing a required
end date is also blocked. After correction the payload contains the new ISO
YYYY-MM-DD values, with unchanged inclusive business-date contract/schema 2 and
Vietnam/UTC half-open timestamp conversion on the backend.

There are no other native date fields in this lane. Export/enqueue works from a
frozen report ID, not a fresh date-form payload. Automatic-generation settings
have no user-supplied period dates: they still use the backend's current Vietnam
business date with immutable run pins and cutoff. No unrelated settings form is
globally blocked by a draft in the manual period form. No non-Form date handler or
optional date field is introduced, so no separate submit guard is needed here.

## Validation

PASS: frontend typecheck/build. Existing Vite chunk-size warning remains.
PASS: **17 synthetic browser cases**, including DD/MM display, calendar opening
without submission/date mutation, impossible start date, partial end date,
cleared required end, no preview POST for each invalid draft, and correction
sending `2026-11-05` through `2026-11-06` rather than stale `2026-11-06` for both.
Existing report/delivery/Admin/daily/timer/actor regressions remain in the harness.
The final 17-case harness passed three consecutive runs after field-scoping fixes.

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
node frontend/node_modules/vite/bin/vite.js --config tests/reporting/ui/vite.config.mjs
node tests/reporting/ui/check.mjs
```

Form-error assertions are scoped to the relevant field, because AntD help-text
leave animations can temporarily retain the previous field's identical message.
Failure diagnostics preserve the original failure even when the Admin panel has
not been mounted. The settings screenshot was visually inspected with both date
values shown DD/MM/YYYY; synthetic screenshots stay outside Git in
`%TEMP%\cafe-fin-reporting-qa`.

Last complete backend/core run remains **240 PASS (78 reporting + 162 core),
158.46s**, one baseline Starlette/httpx warning, no skips. Backend code/schema did
not change in this UI increment, so that long lifecycle suite was not repeated.
The approved shared date suite's 11 cases were run by root; this lane verifies
its actual feature adoption through the 17-case harness instead of claiming a
second shared-suite execution.

No reporting migration/API/DTO change. Production registry/provider/native tray,
installer, real OA/group and authorized live-send acceptance are still NOT RUN in
this lane. No push, merge or READY tag was made.
