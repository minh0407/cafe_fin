# Maximum worksheet XLSX parser benchmark method

Script: `tests/accounting/benchmark_xlsx.py`. Versioned run **XLSX-MAX-001 passed**
on 2026-11-07 local time after the parent released this chat's heavy-work slot.
The 2,000-row smoke and actual worksheet-limit run executed sequentially. Other
chats shared the host; CPU/I/O were not pinned. Results below are observed for
these exact hashes/workloads, with no quiet-machine or native-UI claim.

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

## XLSX-MAX-001 results — 2026-11-07

Actual run: 2026-11-06 17:34:40–17:44:52 UTC (2026-11-07 00:34:40–00:44:52
Asia/Bangkok). Process exited **0**, status **PASS**, total measured 610.913 s.
Data worksheet `1` had **1,048,576 stored rows = 1 header + 1,048,575 data**,
8 columns and **8,388,600 data cells**. The separate notice worksheet had 1 row.
All rows/cells, full projection hash, native numeric/date metadata, leading-zero
and high-precision endpoints reconciled. Page counters were 2,098 pages at 500
rows, with 75 final-page data rows; no API/UI pagination was measured.

| Phase | Observed seconds | Sampled process RSS peak (MiB) |
|---|---:|---:|
| Streaming generate + expected projection/tail hashes | 28.157 | 40.930 |
| Source SHA-256 before | 0.126 | 41.934 |
| Actual-dimension manifest, both sheets | 110.705 | 41.348 |
| Full parse + preflight + exact verification | 249.945 | 42.609 |
| Near-tail recovery: full re-read/skip | 221.849 | 43.523 |
| Source SHA-256 after | 0.116 | 44.039 |

Windows cumulative process-lifetime RSS peak was 47,230,976 bytes (45.043 MiB),
including hashing buffers. Peak sampled private bytes were 29,810,688. Sampling
was requested every 100 ms and had no recorded errors; samples remain lower
bounds. Empty parser-index/journal disk peak was 8,704 bytes and cleanup returned
it to zero. The compressed source was 52,778,902 bytes; 7 ZIP entries unpacked to
568,549,923 bytes, maximum entry ratio 10.773. This fixture contains no shared
strings, executable formulas, known invalid rows or duplicate extras; text was
at most 41 characters. It does not stress long cells or a populated string spool.

The recovery pass visited 1,048,575 rows, skipped 1,047,575 and emitted exactly
1,000. Its checkpoint was source row 1,047,576; the first emitted tail row arrived
after **221.727 s**. The emitted tail hash matched independently generated expected
data. This measured cost includes another structural prescan and full prefix
replay; it is not a seek or an application process restart measurement.

The preceding smoke passed 2,000 rows / 16,000 cells: generation 0.054 s,
manifest 0.209 s, parse/verify 0.461 s and re-read/skip 0.460 s. It established
harness correctness before the full run, not maximum-size performance by itself.

Environment: Windows 11 build 26200 AMD64; Intel64 Family 6 Model 183 Stepping 1,
16 logical processors; physical RAM visible to Windows 34,138,931,200 bytes
(31.794 GiB). Disk inventory reported KINGSTON SNV3S1000G, SSD/NVMe,
1,000,204,886,016 bytes; selected volume was C:. Python 3.12.16, SQLite 3.53.1,
openpyxl 3.1.5, defusedxml 0.7.1. This inventory does not establish an isolated
disk/device mapping or eliminate contention. OS cache was uncontrolled; other
chats/root could run backend/browser tests, and that interference was not
quantified. Keep these limitations with any quoted timing or RSS number.

Backend freeze was `8b70f1ffbee4a30ceaa5a3c8458fd78f84c8d08a`; actual recorded Git
HEAD was `ef29e460f5406c587c4bfb8e2ba238e796e7075c`, the approved frontend-only
date-input change. Worktree was dirty. Measured runner/parser/exporter hashes
were identical before/after, with `files_changed_during_run=[]`; this is local
development evidence, not a clean release attestation.

SHA-256 evidence:

- Original source before/after: `0bf13e98caeed7241a1d831b6519dd732a9bcabc52c9f4d49bf050147994d607`.
- Full projection actual/expected: `9b7d44bd8d12adcb875fd36183826f6bdabfa7d06984f5919f2286b1356aaa45`.
- Tail actual/expected: `5f915edc3dcba9e1a47d17529fcde3481fbcfe4948dc3679c06a7861b25a2e4f`.
- Full result JSON: `4de6269233ba64f2249768b6020cde125ce43433ec81e1ed0a43d00dc0298c07`.
- Smoke result JSON: `0dce4eb138c8e3adde433b440281d814d96ecf278e8771b100c9b3661fffdd3a`.

Retained local artifacts, outside Git:

- Full JSON: `C:/Users/NC/AppData/Local/Temp/cafe-fin-xlsx-8b70f1f-max-20261107a-result.json`.
- Host/provenance context sidecar: `C:/Users/NC/AppData/Local/Temp/cafe-fin-xlsx-8b70f1f-max-20261107a-context.json`.
- Source: `C:/Users/NC/AppData/Local/Temp/cafe-fin-xlsx-8b70f1f-max-20261107a/synthetic-max-worksheet.xlsx`.
- Smoke JSON: `C:/Users/NC/AppData/Local/Temp/cafe-fin-xlsx-8b70f1f-smoke-20261107a-result.json`.

The raw JSON files were not modified after exit. The separate context sidecar
records the coordinator's shared-host clarification and exact JSON hashes.
