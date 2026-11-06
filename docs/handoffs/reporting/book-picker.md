# Public paged book picker and snapshot-name UI

Reporting no longer asks users to type book UUIDs for preview or daily settings.
The module-owned BookPicker uses only public accounting metadata endpoints:

- `GET /accounting/books?page=<n>&page_size=50`, one user-selected page at a time;
- `GET /accounting/books/{id}` for selected IDs not found in the current page.

Only id/name are retained from book DTOs; columns, semantics and other fields are
not held by the picker. There is no private ORM import or financial row query,
all-books fetch, invented server search or free-text UUID entry. A page response
is checked for the page contract, at most 50 items and unique valid IDs/names.
Selected-ID lookup uses up to four workers per selection batch (max 100 selected);
obsolete batches stop issuing more requests and ignore their in-flight results.
Cached labels are pruned to selected IDs plus the current 50 rows, at most 150.
Select virtualization is disabled for this bounded set to expose real accessible
options rather than hidden virtual proxy options.

Names remain visible when changing pages. Saved selections outside the page get
names through the public detail route. Failed/unavailable lookups retain their
IDs with an explicit unavailable-name warning; they are never silently cleared
or relabeled from a different ID. Users may remove selections or retry loading.
If accounting is absent/unavailable, the UI says so and an empty book selection
still permits inventory-only preview. Names are React text, not HTML.

Preview and settings still send **arrays of IDs** under the existing book_ids /
daily_book_ids keys and max100 validation. No label is sent as a book ID or saved
as snapshot metadata. Settings mapping no longer joins/splits comma text. Busy
mutations disable the picker; saved config/authority/version/target pins remain.
Stale page/detail callbacks check request generation, selected IDs and session
generation. Reporting's actor-generation remount and API session abort discard
old caches/forms/responses. Labels are memory-only, never localStorage.

The detail preview also renders optional v3 snapshot product/warehouse/book names
as literal text, with its existing source-ID fallback for old snapshots. It never
uses this live picker cache to enrich saved report names. Backend summary
rendering/freezing evidence is in read-bridge-v3-consumer.md.

## Validation

PASS frontend typecheck/build. Existing Vite chunk warning remains. Browser
coverage uses the actual feature/components and stubbed public HTTP responses:

- Main harness: 21 internal assertion groups, including v3 snapshot literal names,
  existing date/report/export/local-copy/sender/Admin/actor regressions and
  choosing daily books by name while posting IDs.
- Picker harness: 10 internal assertion groups, covering bounded page_size50/no
  search, cross-page name/ID retention, escaped label, preview ID array, saved-ID
  lookup, ignored delayed response after removal, settings ID array, actor switch
  with stale page response, accounting unavailable with empty preview, and a
  restored off-page name retained across page changes.

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend run build
.\frontend\node_modules\.bin\playwright.cmd test --config tests/reporting/ui/playwright.config.ts
```

The CI wrapper has one Playwright test driving both internal harnesses; these
counts are not 31 separate Playwright test cases. Main settings/snapshot images
were visually inspected with name controls and literal `<b>&` fields, outside Git
in the wrapper's temp evidence directory. Root's production accounting/provider
integration, private-book permission policy and actual data are NOT claimed by
these public-API fixtures. No migration/API/model/dependency change or real send.
