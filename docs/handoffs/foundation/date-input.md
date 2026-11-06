# Shared DateInput — controlled draft contract

`frontend/src/shared/DateInput.tsx` exports `DateInput`, `DateInputProps`,
`dateInputRule` and `isDateInputValueValid`. No feature page has adopted it yet.

## Value contract and the stale-date fix

The control uses a controlled AntD text Input plus an explicitly Vietnamese AntD
calendar. It does not retain a separate last-valid value in place of user text.

- A complete valid date is displayed as `DD/MM/YYYY`; its value is `YYYY-MM-DD`.
- Empty/undefined is empty. Deliberate clear emits `''`, including keyboard erase.
- Incomplete or invalid text immediately becomes the controlled parent/Form value
  **as that exact draft text**. For example, typing `31/02/2026` replaces the
  parent's previous `2026-11-06` with `31/02/2026`; it does not retain the old ISO,
  roll into March, reset on blur, or turn the mistake into an optional empty date.
- An invalid incoming ISO such as `2026-02-31` remains visible and marked invalid;
  the component does not silently normalize or discard it.
- `onChange?: (value: string) => void` therefore emits valid ISO, `''`, **or an
  invalid/partial draft string**. This intentionally replaces the earlier
  proposed ISO-only callback contract before adoption/freeze.
- The parent must retain the received string. Do not filter invalid drafts out in
  an onChange handler, because that would recreate the stale-date bug.

Strict Day.js customParseFormat validates dates without JavaScript Date rollover,
UTC conversion, or timezone offsets. The display/calendar locale does not depend
on browser locale or an app-level ConfigProvider.

## Required Form integration

Use the exported rule for **every** Form.Item using this control, including
optional dates. `required` alone only checks presence and is insufficient.

```tsx
import { DateInput, dateInputRule } from "../shared/DateInput";

<Form.Item
  name="occurred_on"
  label="Ngày nghiệp vụ"
  rules={[{ required: true, message: "Nhập ngày." }, dateInputRule]}
>
  <DateInput aria-label="Ngày nghiệp vụ" />
</Form.Item>

<Form.Item name="due_on" label="Hạn thanh toán" rules={[dateInputRule]}>
  <DateInput aria-label="Hạn thanh toán" />
</Form.Item>
```

The strict rule permits `undefined`/`''` for an optional date, rejects every
nonempty non-ISO/invalid draft, and lets required validation be added separately.
It validates only that field and does not globally block unrelated forms/jobs.
A form with an invalid draft shows the error and never reaches onFinish/API save.

For a non-Form submit handler, call `isDateInputValueValid(value)` before building
or sending the payload and display a field error when false. The API must also
continue validating ISO dates. A raw invalid draft must never be interpreted as
an empty optional date or replaced with the prior saved value.

## Other public props

Supports `value?: string`, `onChange?: (value: string) => void`, id, name, ARIA
attributes, disabled, placeholder, size, status, style/class, focus/blur callbacks,
autofocus and allowClear. Ref forwarding now uses AntD `InputRef` for Form focus.
Calendar opening/navigation does not mutate the date; choosing a day emits its
ISO string. Calendar/clear buttons are non-submit buttons and respect disabled.

Disabled behavior uses the public pinned AntD
`ConfigProvider.useConfig().componentDisabled` and the standard precedence
`props.disabled ?? componentDisabled`. Thus `Form disabled` locks the input and
calendar together even without an explicit DateInput prop. Disabling closes an
already open popup, blocks pending calendar selection/text changes and clear,
and does not emit or mutate the field. Re-enabling starts with the popup closed.
An explicit `disabled={false}` consistently overrides disabled context, as in
AntD's built-in Input; the calendar header also receives that resolved context.
Callbacks retained by a hidden Popover consult the latest disabled ref, so a
queued click from its previously open day cell cannot mutate a disabled Form.
This changes no DateInput value/rule API.

No app/main, registry, feature code, package files or real-api browser tests were
modified. Lanes must adopt the rule/submit guard together with the component.

## Dependencies and license

Uses existing AntD Input/Calendar/Popover and Day.js `1.11.23` (MIT), already
installed and pinned directly by root. Locale/customParseFormat ship in that
package. No package, resolution, network resource or conversion service is added.

## Validation

Focused browser tests: `frontend/tests/date-input.spec.ts`. The real component is
mounted through Vite without ConfigProvider. Tests cover DD/MM ambiguity, leap
and impossible dates, controlled invalid drafts, explicit calendar locale, clear,
keyboard Tab, disabled, invalid incoming ISO, three locale/timezone contexts and
calendar selection/navigation.

Required and optional Form regressions start with a valid ISO, type an impossible
date and press Save. Tests capture actual HTTP request JSON: invalid submissions
produce no request; correction sends the new ISO, not the old one. A genuinely
cleared optional value submits `''`; typing invalid text afterwards cannot submit
another empty value.

- `npx playwright test tests/date-input.spec.ts --workers=1`: **13 PASS**,
  Chromium, including the actual Form/HTTP-payload regressions and keyboard
  month/year calendar navigation. The two disabled-context regressions toggle a
  real Form while its calendar is open, exercise a queued former-popup click,
  verify no changes while disabled and re-enable, and verify explicit false
  overrides the Form for both text and calendar header navigation.
- `npm run typecheck`: **PASS**.
- Independent read-only review found no new blocker in the controlled-draft model.

Only this focused suite was run. Feature adoption and a full application
regression suite are outside this handoff.
