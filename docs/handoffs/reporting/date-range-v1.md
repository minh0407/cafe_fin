# Inclusive business-date integration follow-up

Coordinator decision 06/11/2026: every date-only reporting/records/accounting
`from_on` / `through_on` includes both endpoints:
`from_on <= business_date <= through_on`. One day is `from_on == through_on`.
UTC event predicates remain `[Vietnam midnight(from_on), Vietnam midnight(through_on + 1 day))`.

Reporting's previous candidate already permitted equal dates and generated the
next-midnight UTC endpoint, but did not persist an explicit date-semantics marker.
This follow-up makes the common meaning explicit across capture, output and
scheduling, and prevents mixed/legacy source ranges from being guessed.

## Contract and compatibility

- Reporting snapshot JSON is now `schema_version=2`. `period.date_range_contract`
  is `inclusive_business_dates_v1`; `period.timestamp_range_contract` is
  `half_open_utc`. This is reporting's JSON schema version, not a change to
  foundation's `core.contracts.CONTRACT_VERSION=2`.
- `Period.business_dates()` returns the two included dates unchanged;
  `Period.utc_bounds()` uses the public Vietnam time helper for the corresponding
  half-open UTC window. Equal dates are accepted; reversed dates are rejected.
- Both AtomicSources and BridgeSources pass the same first/last dates to inventory
  and accounting providers. Neither adapter adds a day to a date-only argument.
  Source period/cutoff echoes must match exactly; an exclusive-end echo is rejected.
- UI defaults both inputs to the same VN day. Labels/help specify the final date
  is included. Detail and all new PDF/XLSX/TXT/message labels say **đến hết**.
- Catch-up uses the included `through_on` itself for the configured `send_at`,
  never shifts that date forward one day, and still queues saved snapshots only.

No DB migration, root registry/API/dependency change or tag change is included.
The existing immutable JSON and payload columns carry the additive markers.
The OS adapter approved in root `13222da` was already cherry-picked as `84abda4`;
it has not been cherry-picked a second time or edited by this follow-up.

## Legacy handling

Existing snapshot JSON/hash and exported files are never rewritten or upgraded
by inspecting their date values/UTC bounds. A missing/unknown marker remains
explicitly unclassified in the local detail/preview text, even if the stored UTC
bounds happen to look like a modern inclusive period.

Catch-up skips unmarked snapshots, and manual enqueue requires a new explicit
inclusive snapshot. The user can create an ordinary adjusted version with a
reason under the existing report flow; no approval/second-user step is added.
New outbound payloads pin the marker. A legacy queued payload without it fails
preflight with `REPORT_PERIOD_CONTRACT_REQUIRED`, before token refresh or any WAN
call. Payload contents are not changed. UNKNOWN delivery reconciliation semantics
remain unchanged. Existing file export receipts continue returning the old file;
a newly requested export of a legacy snapshot labels its period as unclassified.

## Tests and evidence

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
npm --prefix frontend run build
node frontend/node_modules/vite/bin/vite.js --config tests/reporting/ui/vite.config.mjs
node tests/reporting/ui/check.mjs
```

- PASS **53 reporting tests / 18.42s** (8 new calendar/legacy cases), with one
  unchanged Starlette/httpx TestClient deprecation warning. Core source is not
  changed; the previous combined 168-test evidence remains in README.
- Boundary fixture uses a real SQLite table and two independently implemented
  public connection-bound helpers: inventory filters UTC instants `>=start,<end`;
  accounting filters business dates `>=first,<=last`.
- Single day 01/11/2026 includes UTC `31/10 17:00` and `01/11 16:59:59.999999`,
  excludes the instant just before start and exactly `01/11 17:00` (02/11 VN).
  Included totals are 5.000 kg / 50.05 VND; 31/10–01/11 gives 6.000 kg / 60.06 VND;
  02/11 alone gives 4.000 kg / 40.04 VND. Provider arguments are asserted unchanged.
- Equal-date validation, wrong provider end echo, same-date forwarding through
  both adapters, 18:00 VN scheduler boundary, legacy snapshot/hash preservation,
  legacy catch-up skip and legacy send preflight are covered.
- PASS **10 synthetic browser cases**, now including same-day default inputs,
  inclusive end label and disabled legacy enqueue. Typecheck/build, Ruff and
  diff checks PASS; baseline Vite large-chunk warning is retained.
- New synthetic exports in `%TEMP%\cafe-fin-reporting-date-qa`; both PDF pages
  rendered with bundled Poppler and visually inspected. No PII or generated media
  is committed. Snapshot SHA:
  `9ae2f48f4d5fb4269adec3d7a74f22ed5dec2720ca6890bd2106c50381f0d4a5`.

| Export | SHA-256 |
| --- | --- |
| PDF | `3fa27ec31d5f1202217d7012db340995a0a3a7c9a32101dcc7724c1e95a4c6fb` |
| XLSX | `868704ad72041858e4d7de011e9944031bdcef28f25b177921cb5a9cc1096634` |
| TXT | `134abb568e1f3c8c3c391c358eeb8b280dbdf09b5d3e139210f5f2d1eb71ef44` |

NOT RUN here: integrated real records/accounting providers after the accounting
lane's matching fix, native lifecycle/release gates, or live Zalo. Root should
rerun real single-day/multi-day integration on the coordinated inclusive API
contract before pushing. No live send, push, merge or READY tag was performed.
