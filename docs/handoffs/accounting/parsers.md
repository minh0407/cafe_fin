# Source parser handoff

Scope: `backend/cafe_fin/accounting/parsers.py` and `tests/accounting/test_parsers.py`.
No shared-file, migration, dependency, commit or push changes in this subtask.

## Public API and projection

`manifest(path, filename, *, check_cancelled=None)` takes a **trusted internal FileStore path**, never a client
path. Supported extensions: CSV, XLSX, XLSM. Workbook sheets return stable OOXML
sheetId strings, name, epoch (`1900` or `1904`), sheet visibility, actual maximum
stored row/column coordinates, stored-row count and merged-range count. The scan
does not trust cached worksheet `<dimension>` metadata. CSV dimensions remain
unknown until a job parses it; defaults are included in the manifest.

`iter_rows(path, filename, profile, *, temp_dir=None, check_cancelled=None)` yields `SourceRow` dataclasses:

The optional keyword-only `temp_dir` is a trusted internal directory supplied by
the worker (`app-data/imports`), never a client profile path. TemporaryDirectory
owns spool cleanup. Combined values plus formula text are limited to 256 KiB UTF-8
per row in addition to the 32,767-character cell cap; oversized rows return
`ROW_LIMIT`, without truncating or staging that row. `metadata.numeric_cells`
retains raw OOXML numeric tokens for exact Decimal conversion without coercing
numeric-looking text.

The trusted `check_cancelled` callback runs at entry/completion and at intervals
of at most 1,024 XML events or CSV records/physical lines, including structural
manifest/preflight scans, shared-string spooling and skipped/hidden rows.
`JobInterrupted` propagates unchanged and context managers close streams, the
temporary index and its directory. Neither callback nor spool path is accepted
from profile keys. This is cooperative cancellation, not a promise about a
blocked filesystem call or a whole application's shutdown latency.

- `sheet_id`, `sheet_name`, `source_row`: original record coordinates. CSV source row
  is the logical CSV record number, including a header, rather than physical line
  number when a quoted cell contains a newline.
- `values`: a dictionary keyed by source column letters. Numeric XML tokens remain
  **exact source strings**, including exponent/trailing zeros. Text is not cast to
  numbers. Booleans are bool; empty numeric cells are `None`; text blanks are `""`.
- `formulas`: original `formula_text` prefixed with `=`, exact `cached_value`,
  `calculation_status`, `formula_type`, `shared_index`. No formula is evaluated.
  Status is `external_reference`, `cache_only`, or `missing_cache`; caches are never
  marked recalculated/authoritative. Shared-formula followers can have
  `formula_text=None` with a shared index. Formula translation/recalculation is not
  inferred. Missing caches never become zero.
- `metadata`: Excel `epoch`, `date_cells` keyed by letter with exact `excel_serial`
  and epoch, or `iso_date` for OOXML `t=d`; and `error_cells` for OOXML error values.
  Dates remain raw for authoritative validation. Serial 60 is preserved so the
  validator can reject or explicitly handle Excel's fictitious 1900-02-29. Text
  date strings are unchanged; `date_format` belongs to schema validation.
  `numeric_cells` maps source letters to exact native OOXML numeric tokens,
  including exponent notation and numeric date serials. Numeric formula caches
  also appear here with their separate formula provenance; this does not promote
  them to authoritative values. CSV and OOXML text cells have no numeric entry.
  Validation may expand native numeric tokens with Decimal while keeping raw
  strings intact; user text/CSV must still follow the explicit locale profile.

`ParserError` has a stable `.code` and a bounded Vietnamese message without raw
values or internal paths. I/O and disk-full exceptions propagate to the job layer
for its recoverable system-error handling.

## Profile semantics

`sheet_id` selects an OOXML sheet ID (first importable sheet when absent); CSV uses
`csv` (`1` accepted). `header_row` defaults to 1, and `start_row` defaults to
`header_row + 1`; zero means no header. Explicit start overrides that default.
`end_row` is inclusive. `skip_blank` defaults to true. OOXML absent sparse rows
are not synthesized; explicit empty stored rows can be retained with false.
Formula cells are retained even when they lack a cache.

`hidden_rows` is `include` (default) or `exclude`. `merged_cells` is `reject`
(default) or `top_left`; the latter keeps only the anchor coordinate, drops any
stored non-anchor cells, and does not propagate/fill anchor values.

CSV uses **the explicit default profile UTF-8 with optional BOM and comma**.
No encoding or delimiter is sniffed or silently changed. The manifest exposes
these defaults for the mapping screen; users can set `encoding` and a one-character
`delimiter`. Strict decode failure gives `CSV_ENCODING_REQUIRED`. CSV quoting,
embedded newlines and leading zeros are preserved. Formula-like CSV strings remain
text. No locale-specific number/date inference occurs here.

## Limits and resources

Constants are centralized in the parser. ZIP limits apply to all entries before
reading workbook parts: total uncompressed size <= 4 GiB, <= 20,000 entries, and
each entry's expansion ratio <= 1000. Duplicate/traversal ZIP names and encrypted
ZIP entries are rejected. ZIP entries are never extracted to source directories.

Supported worksheet operational range is <= 256 columns and <= 1,048,576 Excel
rows. Cell/string/attribute text is <= 32,767 characters; CSV record text is bounded
by `256 * (32767 + 3)` characters. XML depth <= 64, attributes per element <= 64,
cell/shared-string descendant nodes <= 4096, stored-row descendant nodes <= 16,384,
cells per stored row <= 256. Active-row aggregate text also uses the bounded CSV
record limit. Metadata parts <= 8 MiB, cell styles <= 65,536, importable sheets <=
1024, merged ranges per sheet <= 65,536. These are operational limits, so unsupported
oversized richly formatted sources must be simplified or split for import.

Used XML is parsed with defusedxml and a bounded TreeBuilder; DTD declarations,
entities and external XML resolution are rejected. Rows/shared strings/extensions
are detached while streaming. Shared strings are indexed in a temporary SQLite
database on disk with a 2 MiB SQLite page cache. This database is an isolated,
disposable parser index, **not** an application domain writer; it never accesses
the application DB. Temporary disk capacity must be included in job resource
checks. Closing/exhausting the iterator closes ZIP handles, SQLite and temporary
files. Callers that stop early should explicitly close the iterator.

Macro binary, external-link files and unrelated archive parts remain inert. The
parser does not execute macros, follow workbook external relationships, invoke
Office/COM, open URLs or save the source. Only original FileStore bytes are the
original; the parser projection is not a fidelity-preserving workbook export.

Manifest scans all importable sheets; row iteration first rescans the selected
sheet for structural/merge checks, then parses its values. This deliberately
costs additional sequential I/O and avoids relying on false dimensions or
discovering rejected merges only after yielding rows. Restart/resume requires
re-reading and skipping by source identity or using completed staging; no O(1)
ZIP byte-offset resume is promised.

## Verification

PASS: `.venv/Scripts/python.exe -m pytest tests/accounting/test_parsers.py -q`:
24 passed in 4.56 seconds on the current worktree runtime. Cases cover Vietnamese
CSV/BOM/quote/newline/leading zeros, explicit UTF-16/semicolon, raw precision above
2**53, 1900/1904 date serials, formula cache/missing cache/external status, shared
formula followers, actual openpyxl-produced workbook, inert XLSM bytes/hash,
hidden/blank/range/merged policies, malicious XML/ZIP, and limits. A 20,000-row
tracemalloc regression consumes rows without retention and checks peak traced
allocation under 8 MiB; this is a regression guard, not a process-RSS benchmark.

PASS: parser plus parser-specific row/temp/cancellation hardening checks:
41 passed, 10 application cases deselected in 9.68 s at the cancellation increment;
Ruff/format/diff checks passed. Application-wide test and CSV import evidence
belongs to the lane's separate integration/benchmark handoffs.

PASS: **XLSX-MAX-001**, actual maximum worksheet parser run on 2026-11-07 local
time: 1,048,575 data rows + header, 8 columns / 8,388,600 cells. Actual manifest
110.705 s; full parse plus preflight/hash/metadata checks 249.945 s; near-tail
re-read/skip 221.849 s, first remaining row after 221.727 s. Full and 1,000-row tail
hashes matched, original SHA remained unchanged and relevant source hashes stayed
fixed. Sampled parse RSS was 42.609 MiB and recovery RSS 43.523 MiB; cumulative OS
lifetime peak across the workload was 45.043 MiB. Results were observed on a
shared, unpinned host with uncontrolled OS cache; they are not timing guarantees.

See [versioned XLSX method/results](xlsx-benchmark-method.md) for exact commands,
hardware/package/source hashes, retained artifacts and limitations. This was
parser-only with inline strings and an empty temporary string index. Full XLSX
application staging/validation/publication, populated shared-string spool,
API/worker/UI responsiveness and actual process restart were not measured by it.
