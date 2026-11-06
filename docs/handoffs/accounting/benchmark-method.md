# Real local accounting benchmark method

`tests/accounting/benchmark.py` is an opt-in runner using real file-backed SQLite WAL, the foundation serialized writer, actual Runtime/JobRunner, AccountingService, immutable FileStore, accounting migrations/handlers and the actual additive CSV export route. It is not a mock benchmark or a pytest test collected by default. No shared production files are changed by the runner. Instrumentation times real committed chunks and pauses the first parse receipt once; it does not replace parser/validation/DB effects.

**Shared host, not an exclusive performance environment.** Root/other chats ran local backend/browser tests during the reported 500k/1m windows. CPU and I/O were not pinned, and those concurrent workloads affect observed durations and latency. The parent's single heavy-work slot coordinates only this chat; it does not isolate the whole machine. Its plan not to run heavy tests in this chat must not be presented as a quiet-host guarantee. Correctness/count/hash assertions remain valid, but these are not quiet, fastest-case or native-UI measurements. Apply this limitation to every historical/baseline/current table linked from this method.

## Reproduce

Run from this worktree with the existing Python 3.12 environment and backend import path. Use a new empty root and a new JSON output outside Git for every run. No generated data is deleted or overwritten automatically.

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
.\.venv\Scripts\python.exe tests/accounting/benchmark.py --rows 50000 --root "$env:TEMP\cafe-fin-bulk-50k\data" --output "$env:TEMP\cafe-fin-bulk-50k\result.json"
.\.venv\Scripts\python.exe tests/accounting/benchmark.py --rows 500000 --root "$env:TEMP\cafe-fin-bulk-500k\data" --output "$env:TEMP\cafe-fin-bulk-500k\result.json"
.\.venv\Scripts\python.exe tests/accounting/benchmark.py --rows 1000000 --root "$env:TEMP\cafe-fin-bulk-1m\data" --output "$env:TEMP\cafe-fin-bulk-1m\result.json"
```

`--root` and `--output` may be omitted for a unique user Temp directory. `--skip-second-pass` explicitly omits fixing/revalidating/confirming invalid rows; it is recorded in JSON and must not be described as full partial-import acceptance. Smaller `--rows` values (2..1,000,000) support smoke/debug runs; they do not replace the three requested bulk sizes.

`--business-key-columns code` selects the explicit-business-key scenario using stable column IDs; one or more whitelisted IDs are accepted and repetitions are rejected. JSON records the scenario name and selected IDs. The default keeps the historical no-explicit-key semantics. The prepared 3aa8c47 scenario uses `code` for all three sizes; the never-executed 8b and 9a CSV preparations are superseded. Its exact duplicate pairs and invalid rows are unchanged. Prepared commands must wait for the parent's CSV-slot release and do not imply host exclusivity.

Collect hardware separately in PowerShell alongside each result, without claiming a disk is an SSD based on its path:

```powershell
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, Size
Get-Volume | Select-Object DriveLetter, FileSystem, Size, SizeRemaining
```

## Deterministic source and assertions

The CSV generator streams one record at a time with eight columns: 12-character zero-prefixed text code, ISO business day, exact VND money, exact scale-3 quantity, product category, Vietnamese text containing commas and occasional formula-like literal text, currency and warehouse label. It uses integer cents/milliunits, not float. Header adds one record; data cells are actual generated rows × 8. Source SHA-256/bytes and expected exact totals are computed and recorded. No raw row values, credentials or database content are logged.

Every 1000th record has an invalid amount (0.1% at the requested bulk sizes). Records 2,1002,2002,... exactly repeat the previous valid record in all eight fields (0.1% extra duplicate records). Thus 0.2% of records participate in duplicate pairs; those counts are distinct and not added to invalid counts. No business unique key is invented. Warnings are explicitly kept as new legitimate records before confirmation.

The runner generates/stores the original; parses it; pauses after the first committed parse chunk; gracefully stops/closes Runtime; reopens/authenticates/resumes the same job; maps stable column IDs; validates/deduplicates; keeps duplicate warnings; confirms valid rows; reconciles visible count, distinct lineage targets and exact Decimal summary; patches invalid records in at most 500-row calls; revalidates/confirms the remainder; reconciles again; exports CSV via the actual module route/worker; streams the derived export to count rows/cells; and re-verifies the unchanged source hash.

Restart evidence is a **controlled graceful worker interruption at a committed receipt**, followed by an actual Runtime restart and checkpoint resume. It does not establish hard process-kill, power-loss, disk-full, stale-worker or every publication crash window behavior; those require separate regression/crash probes. CSV resume can reread and skip source records; no O(1) resume claim is made.

## Measurements and scope on a shared nonexclusive host

- Each user-visible phase uses the monotonic high-resolution `time.perf_counter()` clock. JSON also groups real worker intervals by `parse`, `normalize`, `deduplicate`, manifest, pending-commit and publication-related phases as emitted by the actual handler. An interval starts at job entry or the preceding committed chunk and ends after the next durable chunk; it includes parsing/validation/query/writer overhead belonging to that chunk. The tail includes finalization or controlled interruption overhead. Summed worker phases across retries are clearly separate from enclosing end-to-end phases, which overlap them.
- Windows process RSS/private bytes come from `GetProcessMemoryInfo`, sampled every 100 ms. `os_peak_rss_bytes` is the OS cumulative process high-water mark; per-phase RSS/private peaks are sampled and can miss very short spikes. API/service/parser/worker execute in the **same process**, so their memory is reported as shared, not falsely separated. Native UI/WebView2/browser memory and responsiveness are **NOT RUN**.
- Disk sampling records peak root/directory file bytes, WAL, SHM and temporary files visible under the app-data root. SQLite/OS temporary files outside that tree are NOT MEASURED. Snapshots include real stage-row counts, JSON character counts, SQLite page bytes and stage table page bytes when SQLite dbstat exists. Table sizes exclude separately named indexes; directory/database file totals include them. File byte lengths are not a claim of filesystem allocated blocks. The fixture is a separate sibling of the app-data root and its bytes are recorded independently.
- Actual chunk size comes from `AccountingJobs.CHUNK` (currently 500); query/patch page limit is 500. Status latency is sampled at 100 ms and whole-dataset filter/page plus versioned update on a separate synthetic book run periodically while worker jobs are active. These add measurable load. Full latency samples are summarized by count/min/median/p95/max, not turned into a universal speed guarantee.
- The export route is invoked in-process with a real authenticated user's captured principal. Writer authorization still validates the persisted user. HTTP server startup, login request latency, native app UI and end-user network boundary latency are outside the timing scope. No Internet/cloud services are called.
- Sequential runs within this chat can still overlap root/other-chat backend or browser test load on the shared host. No CPU affinity, I/O isolation or quiet-host baseline was established. Report measured times with this interference limitation; do not replace them with estimated unloaded performance.

Use the report label **whole-dataset filter/page**. A legacy raw JSON method label containing “indexed” is not EXPLAIN evidence. The committed numeric-filter EXPLAIN tests on freeze `9a52f02` assert its tested count/page queries use accounting_cells_number while retaining published visibility; that evidence belongs to 9a52 and must not be retroactively attributed to older `033e900`/`45bc4165` timings. No new-version CSV timing is claimed before execution. The later text/date filter tests on freeze `3aa8c47` similarly capture count/page SQL and assert accounting_cells_text with book/published semantics retained. The actual selective CODE-text UI timeout on 9a remains a failed 9a observation, not a CSV result or evidence for 3aa8. Parser-module hashes remain unchanged from the separate 8b XLSX parser-only measurement; a widget-only change does not justify rerunning that parser measurement.

Every phase updates a local JSON result. Failed assertions/jobs produce FAIL and a safe error code/type; source data and checkpoints remain for diagnosis. A result is PASS only after the configured whole run and all deterministic count/hash/lineage/amount assertions complete. Do not publish estimated throughput as a measurement or claim 500k/1m evidence from a smoke run. Hardware inventory, stdout, JSON and fixture parameters must accompany any reported bulk result.

## Historical development evidence, 2026-11-06 — shared-host timings

Smoke 2,000 rows: PASS, full two-pass import plus restart/resume/export, 4.14 s. Local JSON: `C:\Users\NC\AppData\Local\Temp\cafe-fin-benchmark-yj3vr_u9\data-result.json`. Its initial clock was Windows `time.monotonic()` with lower resolution; use the subsequent high-resolution run for latency figures.

Actual CSV 50,000 rows × 8 columns: PASS, full second pass, 96.70 s total. Local JSON: `C:\Users\NC\AppData\Local\Temp\cafe-fin-benchmark-7pxhe1_f\data-result.json`; app data and generated fixture are in that same parent directory. Invalid=50, exact duplicate extra records=50, duplicate-group records=100. First publication=49,950 rows; second publication reaches 50,000 rows, exactly 50,000 lineage records/distinct targets and two published attempts. Final exact income=17,500,249.50 VND; export has 50,000 data records × 8 columns; original SHA-256 unchanged.

| Phase | Seconds |
| --- | ---: |
| First parse checkpoint | 0.12 |
| Graceful close/reopen/resume probe | 0.23 |
| Resumed parse | 3.03 |
| First validation + duplicate analysis | 27.92 |
| First confirmation/publication | 33.47 |
| Patch 50 invalid records | 0.10 |
| Second validation + duplicate analysis | 28.82 |
| Second confirmation/publication | 1.01 |
| CSV export through route/worker + read verification | 0.97 |

Sampled shared-process working set during import peaked at approximately 103.2 MB, with a cumulative OS high-water mark of 153.7 MB including bootstrap/restart password hashing. Peak observed WAL=31.28 MB; final DB file=296.64 MB, source=4.94 MB and derived CSV=4.94 MB. Foreground filter: 40 samples, p95=0.529 s, max=0.578 s. Foreground versioned update on the separate probe book: 40 samples, p95=0.344 s, max=0.384 s. These observations include the benchmark instrumentation/probe load; UI is NOT RUN.

This was an **uncommitted development run**, based on Git `90ee46ca66af867492b33483afd975c449e9602f`. JSON includes source SHA-256 maps at start/end. `accounting/exporting.py`, `accounting/jobs.py` and `accounting/service.py` changed on disk while the process was running; imported modules remained loaded in-process across Runtime reopen. The result demonstrates the loaded development code, not an immutable release revision. Hardware inventory must be attached by the parent before publishing a hardware-qualified benchmark claim. Python/package/clock/SQLite versions are in the JSON.

That 50k result is historical evidence only. Later frozen 50k/500k/1m runs and
their exact code versions are recorded in [benchmark-results.md](benchmark-results.md).
Use that versioned report for measured throughput and remaining acceptance gates.

