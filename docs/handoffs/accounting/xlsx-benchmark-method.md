# Maximum worksheet XLSX parser benchmark method

Prepared script: `tests/accounting/benchmark_xlsx.py`. **NOT RUN** while the separate
CSV 50k/500k/1m benchmark is active. Compilation and linting do not constitute
performance evidence. Coordinate with the parent before any smoke or full run.

## Scope and fixture

Default `--rows 1048575` creates exactly 1,048,575 data rows plus one header row:
1,048,576 stored rows in data worksheet ID `1`, the Excel worksheet maximum.
`exporting.write_xlsx` adds its separate one-row fidelity notice worksheet; the
script requires exactly these two sheets and explicitly selects data sheet `1`.
The actual manifest scanner must independently verify row/column positions rather
than trust a cached dimension. Data has 8 columns and 8,388,600 data cells.

Streaming fixture generation uses a deterministic generator with leading-zero
codes, dates, integer counts, native numeric money, scale-3 decimal quantities,
choices, high-precision precomputed formula results and Vietnamese text with
quotes/newlines or an inert formula-like prefix. All seven supported schema kind
labels occur; no formula evaluation is benchmarked. The derived writer serializes
precomputed formula results above 15 digits as exact text. Numeric native cells
and styled date serials remain exact XML strings with source metadata on parse.
Canonical data/projection hashes are deterministic; ZIP container timestamps can
differ between runs, so the ZIP SHA identifies one fixture and is compared before
and after that run rather than required to match a different run's ZIP SHA.

Inline text is unique for most rows. This fixture **does not exercise a populated
shared-string spool**; the parser still creates its empty temporary SQLite index.
Do not generalize its memory/disk results to shared-string-heavy workbooks.

## Sequential execution

Run from the assigned checkout with the selected environment, **after CSV work
has finished and after the parent approves the benchmark slot**:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe tests/accounting/benchmark_xlsx.py --root "$env:TEMP\cafe-fin-xlsx-max-unique" --output "$env:TEMP\cafe-fin-xlsx-max-unique-result.json"
```

Use a new path for every run. The script rejects a nonempty root, an existing
result, and roots/results inside the repository. It never deletes previous data.
The default root is a fresh system-temp directory; `--output` defaults to a
sibling result JSON. A small authorized smoke can pass `--rows 2000`; its JSON is
explicitly marked as not the worksheet-limit case. Neither fixture nor results
belong in Git. Keep sufficient free disk for compressed source and parser temp.

## Measured work and reconciliation

Phases separately time streaming generation plus expected hashes, source SHA-256
before, all-sheet actual-dimension manifest, selected-sheet full parsing plus
verification, a second full re-read/skip recovery pass, and source SHA-256 after.
Per-row verification checks stable source identity, 8 cells, native numeric raw
strings, 1900 date metadata and inert high-precision text. Full SHA-256 over the
canonical source-row/value projection must match the independently specified
expected projection accumulated during generation. First/last coordinates,
leading-zero codes, date serials and precision samples are reconciled explicitly.

The parser phase includes its own structural/merged-cell prescan, value parsing,
canonical hashing, metadata checks and progress/page counters. It is not a pure
XML-tokenization throughput measurement. The generator phase includes independent
expected projection hashing. OS cache is uncontrolled and later phases may be
warm. No cold-cache or SSD speed claim should be made from these timings.

Recovery uses a stable source-row checkpoint 1,000 data rows before the end (or
the whole small smoke tail). It calls the parser from the beginning, counts all
visited/skipped/emitted rows, measures time to the first emitted tail row, and
reconciles the exact tail hash. It **does not seek within ZIP in constant time**.
This is a measured parser re-read/skip strategy, not application job persistence
or an actual process crash/restart. Those have separate process-crash tests.

Page size 500 is represented by bounded counters only. At the maximum fixture,
2,098 conceptual pages and 75 data rows on the final page are expected. There is
no API page fetch, UI render or browser cache in this benchmark.

## Resource and provenance evidence

A sampler reads current-process RSS/private bytes via Windows
`GetProcessMemoryInfo` every 100 ms and samples source/temp file sizes. All exporter,
parser, verifier and sampler activity shares this process. Phase peaks are sampled
lower bounds; OS `PeakWorkingSetSize` is a cumulative process-lifetime peak.
The temporary shared-string index is redirected to the synthetic benchmark root
so its disposable disk use can be observed. Resource sampling records failures;
the run cannot report PASS if sampling fails.

JSON records CPU identifier/logical count, Windows physical RAM where available,
physical-disk model/media/bus/size inventory, selected volume and free disk. Disk
inventory does not prove the backing device of a virtual/mounted volume. It also
records Python/package/SQLite versions, timing method, selected profile and parser
limits, source compressed/unpacked ZIP sizes and ratios, source SHA before/after,
Git commit/dirty state, and SHA-256 of script/parser/exporter before/after. Relevant
code changing during the run makes the result FAIL; development output is not
automatically immutable release evidence.

Result JSON is atomically refreshed during execution with bounded progress counts,
phase/resource information and final PASS/FAIL. The script prints only a short
status/row-count/result-path summary; no operational user data is used or logged.
It retains synthetic files for inspection instead of deleting evidence.

Not measured: full AccountingService import, authoritative validation, duplicate
matching, pending/publication, API/worker/UI RSS or responsiveness, shared-string
heavy sources, disk-full failure or actual application restart. The separate CSV
and crash-probe evidence must cover those paths. A parser-only maximum worksheet
result cannot establish full XLSX application import performance.
