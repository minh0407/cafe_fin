# Accounting DateInput adoption

Approved shared commit `6098a1111432995ed5b6be96fd0650af382a15e2`
was cherry-picked unchanged as `ef29e46` (the five approved files only).
Approved disabled-context fix `3aa94c601dbf878f07b46b0902fc71b0f388c40c`
was cherry-picked unchanged as `545d75e` (the three approved files only).

Accounting uses the shared control for summary endpoints, the date-filter builder
and new-row DATE fields outside the grid. Valid values display DD/MM/YYYY and
send ISO YYYY-MM-DD. Invalid/partial text stays in parent state and blocks the
relevant request; optional dates become empty only through explicit clearing.
Required new-row dates also require a nonempty valid value. These are non-Form
handlers, using the shared strict validator before requests.

Summary queries and manual refresh, import-preview queries/rendering, filter
builder/application, JSON filters and direct URL filters reject invalid dates.
An invalid range hides stale totals/preview. Whole-book export remains unrelated
to the summary range. Grid date projection, source mapping/parsing, backend date
APIs, inclusive endpoints and Vietnam business-date semantics are unchanged.

Latest validation on 2026-11-07: frontend build/strict typecheck PASS; shared
DateInput browser suite 13/13 PASS (12.3s); full accounting helper/mock browser
suite 17/17 PASS (24.2s), including three feature adoption regressions, all on
test-only port 1424. They verify retained
invalid drafts, no invalid HTTP mutation/query, correction to a new ISO date,
required/optional new-row payloads, explicit clear, same-day endpoints, hidden
stale previews and JSON/URL filter guards. Real API and million-row UI evidence
is reported separately in ui.md. No native WebView2 claim follows from Chromium.

This frontend change does not change the frozen backend import engine or require
an import benchmark rerun. Later numeric-filter changes are a separate backend
commit and measurement scenario.
