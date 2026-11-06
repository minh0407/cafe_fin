# Accounting CSV benchmark results — 2026-11-06

<!-- FINAL-FREEZE -->
## Superseded intermediate freeze: eb4b007

Backend freeze: `eb4b007c1c2ff4b2450a6fd665dd3fa04d48af45`. Its 50k run passed. The parent then required approved core owner-scope helper `22ca543`, superseding this freeze; its 500k run was intentionally interrupted and its 1m run was not started. This section is historical evidence, **not final acceptance of the later helper-enabled backend**. These runs use an immutable backend archive and fresh roots with full second pass enabled. The unchanged tracked runner loads backend from the archive via PYTHONPATH. Parent planned no CPU-heavy tests or other benchmarks during these runs; the host is not CPU-pinned. Frontend/docs WIP can make Git dirty, but backend/runner start/end SHA maps must remain unchanged.

Local evidence base: `C:\Users\NC\AppData\Local\Temp\cafe-fin-final-eb4b007-bb13c12730844961be453d5481f98d38`. Hardware and snapshot provenance are in `hardware-freeze.json` and `snapshot-provenance.json`; per-size `result.json` and `receipt-counts.json` are authoritative. Backend archive SHA-256: `690373b0fd4295984e3207a21631c1afa15e4902afcf97f98330a27869050089`.

Machine: Intel(R) Core(TM) i5-14400F, 10 cores/16 logical processors; 34,138,931,200 RAM bytes; Microsoft Windows 11 Pro 10.0.26200; KINGSTON SNV3S1000G NVMe SSD; C: NTFS, 348,053,364,736 free bytes at inventory. Runtime package/SQLite/clock versions are preserved in each JSON.

Byte limits in this freeze: 256 KiB UTF-8 content per source/edited row; each processing chunk is capped by both 4 MiB serialized budget and 500 rows. Formula evaluation shares 100,000 charged operations across a row; its cancellation callback checks the worker lease/stop immediately on stop and at most every 50 ms during ongoing work. This CSV fixture uses eight short columns and no executable formulas, so it establishes workload performance within those caps, not formula-budget stress coverage. Source-owner authorization uses a real local admin fixture.

| Run | Status |
| --- | --- |
| 50k | PASS |
| 500k | INTERRUPTED_FOR_APPROVED_CORE_UPDATE |
| 1m | NOT RUN |

The 500k partial artifact is explicitly `INTERRUPTED_FOR_APPROVED_CORE_UPDATE`, neither PASS nor FAIL. Only its own Python child PID 40212 was verified by result JSON and Windows command line and terminated at the parent's request. Last observed durable validation checkpoint was 423,500 normalized rows (`last=csv:481148`); 1,000 parse receipts and the partial normalization receipts remain in the preserved data root. This external process termination was not graceful, and the intermediate run is not used to claim completed 500k performance.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Actual data rows | 50,000 | — | — |
| Actual data cells (8 columns) | 400,000 | — | — |
| Invalid amount rows (0.1%) | 50 | — | — |
| Extra exact duplicate records / duplicate-group records | 50 / 100 | — | — |
| First published rows | 49,950 | — | — |
| Final published / lineage / distinct targets | 50,000 / 50,000 / 50,000 | — | — |
| Published attempts | 2 | — | — |
| Exact final income VND | 17500249.50 | — | — |
| Whole run seconds | 84.25 | — | — |
| Source SHA unchanged / backend+runner hashes unchanged | PASS / PASS | — | — |

### Final phase times

Seconds are measured, not projections. Confirmation phases include their count/lineage/Decimal-total reconciliations and actual foreground probe load. Worker interval sums overlap enclosing phases and must not be added a second time.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| CSV generation | 0.22 | — | — |
| Store original | 0.04 | — | — |
| First durable parse checkpoint | 0.22 | — | — |
| Graceful stop/reopen/resume | 0.26 | — | — |
| Resumed parse | 3.24 | — | — |
| First validation + duplicate analysis | 16.21 | — | — |
| First confirm/publish/reconcile | 59.14 | — | — |
| Patch invalid rows | 0.12 | — | — |
| Second incremental validation + duplicate analysis | 1.08 | — | — |
| Second confirm/publish/reconcile | 1.32 | — | — |
| CSV export route/worker + read verification | 1.26 | — | — |
| Final source/count/summary reconciliation | 0.66 | — | — |

### Final memory and disk

All memory roles (API/service/parser/worker) share one process. GetProcessMemoryInfo sampling is 100 ms; the OS cumulative peak includes Argon password hashing during bootstrap/restart. Short memory/disk spikes may be missed. Units below are decimal MB/GB; raw bytes are in JSON. Native UI/WebView2/Tauri process memory and interactions are **NOT RUN**.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Operational shared RSS peak | 102.94 MB | — | — |
| All-phase sampled RSS peak | 151.03 MB | — | — |
| OS cumulative peak working set | 153.89 MB | — | — |
| All-phase private bytes peak | 132.67 MB | — | — |
| Final DB bytes | 0.299 GB | — | — |
| Final staged table pages (excluding separate indexes) | 29.39 MB | — | — |
| Peak observed WAL | 30.73 MB | — | — |
| Peak observed temporary file bytes | 4.94 MB | — | — |
| Final app-data root bytes | 0.309 GB | — | — |
| Peak observed app-data root bytes | 0.321 GB | — | — |
| Separate generated fixture bytes | 4.94 MB | — | — |

### Final foreground latency

Count / p95 seconds / maximum seconds. These are real status reads, whole-dataset indexed amount filter/page reads, and versioned foreground updates on a separate synthetic book while background work runs. They do not establish native UI responsiveness.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Job status | 499 / 0.316 / 0.721 | — | — |
| Amount filter/page | 29 / 0.596 / 0.665 | — | — |
| Versioned update | 29 / 0.402 / 0.955 | — | — |

### Final chunk intervals and recovery

Measured sum / actual receipt count / mean interval ms, inclusive of computation/query/writer overhead from previous durable chunk through the next chunk. They are not pure writer transaction durations. Chunk max/p95 were **NOT MEASURED**.

| Worker phase | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Parse | 3.35s / 100 / 33.49ms | — | — |
| Normalize | 11.39s / 101 / 112.81ms | — | — |
| Duplicate analysis | 4.79s / 101 / 47.38ms | — | — |
| Selection snapshot | 6.14s / 101 / 60.79ms | — | — |
| Pending commit | 52.39s / 101 / 518.75ms | — | — |

Each completed run retains the first 500-row durable parse receipt across a real graceful worker stop, Runtime close/reopen, reauthentication and resume. This is **not a hard-kill/power-loss probe**. The full second pass patches only invalid rows and revalidates/imports the remainder; unique lineage/count/sum/hash/export assertions must all pass. No O(1) CSV/XLSX resume claim is made.

Source hashes for completed runs:
- 50k: `9c87f97d31804643f11d02d93598dd5a227c5fb55eff047c390f67e1aa224a8f`; export 50,000 rows × 8 columns, 4,942,132 bytes.

Near-limit XLSX and native UI/native-memory gates are assigned to the parent after CSV benchmarks finish. No production-ready or universal-speed claim follows from these workload measurements.
<!-- END-FINAL-FREEZE -->

## Historical ancestor freeze 45bc4165

The following historical 50k/500k runs **PASS** on ancestor backend `45bc4165f836fcdfe99007232078b630b422cf86`. Final acceptance measurements on the later hardened freeze are listed above. These ancestor figures are retained as history and must not be relabelled as measurements of the later code.

## Source and machine

The actual backend was loaded through PYTHONPATH from a `git archive` of the frozen commit, isolated in user Temp. The unchanged frozen runner stayed in the worktree so its Git provenance checks worked. All 33 archived backend Python sources match the checkout after CRLF-to-LF normalization; the archive preserves Git LF bytes and the Windows checkout uses CRLF for accounting files. Both result JSONs have unchanged source hash maps (`files_changed_during_run=[]`). The runner's generic conservative `immutable_release_evidence=false` flag is not a statement that the external archived snapshot was changed: `snapshot-provenance.json` and archive SHA establish this particular frozen source. These are backend workload results, not release/installer acceptance.

Hardware was queried using Get-CimInstance, Get-PhysicalDisk and Get-Volume: Intel Core i5-14400F, 10 cores/16 logical processors; 34,138,931,200 bytes observed RAM; Windows 11 Pro 64-bit 10.0.26200; KINGSTON SNV3S1000G **NVMe SSD**, 1,000,204,886,016 bytes; C: NTFS, about 352.27 GB free before runs. Other lane development work could run on the same host; it was not an isolated or CPU-pinned benchmark. The two benchmarks ran sequentially without overlap.

Runtime: Python 3.12.16 AMD64, SQLite 3.53.1, SQLAlchemy 2.1.8, openpyxl 3.1.5, FastAPI 0.162.0. Time uses monotonic QueryPerformanceCounter through `time.perf_counter` (reported resolution 100 ns). Actual worker chunks and API page/patch limits are **500 rows**. Native UI/cache settings are NOT RUN. Schema/mapping, SQLite WAL, serialized writer, actual Runtime/JobRunner, immutable FileStore and export handlers are real.

Local evidence root (outside Git): `C:\Users\NC\AppData\Local\Temp\cafe-fin-frozen-20261106-08e3fd55aff541d8b0e8741442448e8c`. It contains `hardware-freeze.json`, `snapshot-provenance.json`, `backend-freeze.zip`, archived sources, `50k/result.json`, `500k/result.json`, receipt-count aggregates, synthetic sources and app-data roots. Archive SHA-256: `820710b74c2d3e33cb6ebd0a8a0c89f5b5f2dde8d0c4db6e7153159f04d0619b`. No generated DB, source CSV or raw-data log is committed.

## Dataset and correctness

Eight columns: zero-prefixed text code, ISO business day, exact money (scale 2), exact quantity (scale 3), choice, Vietnamese text with commas/occasional literal formula prefix, currency and warehouse text. The generator streams and uses integer cents/milliunits. Every 1000th row has an invalid amount. Rows 2,1002,2002,... exactly duplicate the preceding valid row. Warnings are explicitly kept; no business unique key is invented. One header record is additional to reported data rows/cells.

| Check | 50k | 500k |
| --- | ---: | ---: |
| Actual data rows | 50,000 | 500,000 |
| Actual data cells | 400,000 | 4,000,000 |
| Invalid amount rows (0.1%) | 50 | 500 |
| Extra exact duplicate rows (0.1%) | 50 | 500 |
| Rows in duplicate pairs (overlapping warning flag) | 100 | 1,000 |
| First published valid rows | 49,950 | 499,500 |
| Final published rows | 50,000 | 500,000 |
| Final lineage records / distinct targets | 50,000 / 50,000 | 500,000 / 500,000 |
| Published attempts | 2 | 2 |
| Final exact income, VND | 17,500,249.50 | 299,997,495.00 |
| Export data rows × columns | 50,000 × 8 | 500,000 × 8 |
| Original SHA unchanged | PASS | PASS |

Source SHA-256: 50k `9c87f97d31804643f11d02d93598dd5a227c5fb55eff047c390f67e1aa224a8f`; 500k `90e6fe02415772dc67373ae510df7497e605dc4b3b8a01c01da98dd88d8df454`. Exact source bytes: 4,942,090 and 49,469,982 respectively. No cache or float decides money totals.

## Timings

Seconds below are enclosing phases. They include their own status polling, foreground probe load and, for confirmation phases, count/lineage/exact-summary reconciliation. Worker-only chunk interval sums below overlap these phases and must not be added to the total again.

| Phase | 50k seconds | 500k seconds |
| --- | ---: | ---: |
| Stream-generate CSV | 0.20 | 2.10 |
| Store immutable original | 0.04 | 0.21 |
| First durable parse checkpoint | 0.11 | 0.29 |
| Graceful close/reopen/authenticated resume | 0.22 | 0.28 |
| Resumed parse | 3.26 | 33.62 |
| First validation + duplicate analysis | 15.58 | 207.89 |
| Keep duplicate warnings | 0.23 | 1.64 |
| First confirmation/publication/reconciliation | 31.74 | 590.83 |
| Patch invalid rows | 0.10 | 0.92 |
| Second incremental validation + duplicate analysis | 1.33 | 9.92 |
| Second confirmation/publication/reconciliation | 1.99 | 12.01 |
| Actual CSV export route/worker + verification | 1.17 | 9.19 |
| Final source/count/summary reconciliation | 0.89 | 5.70 |
| **Whole run, including bootstrap/mapping** | **57.19** | **874.93** |

Mean chunk intervals use measured worker phase sums divided by actual durable receipt counts, including parsing/computation/query/writer overhead between committed chunks. They are not pure SQLite transaction durations. Parse sums include both sides of the restart. Validation/snapshot/pending sums include both import passes.

| Worker phase | 50k count / mean ms | 500k count / mean ms |
| --- | ---: | ---: |
| Parse | 100 / 31.83 | 1,000 / 33.29 |
| Normalize | 101 / 107.50 | 1,001 / 161.77 |
| Duplicate analysis | 101 / 45.24 | 1,001 / 44.72 |
| Immutable selection snapshot | 101 / 58.05 | 1,000 / 69.72 |
| Pending commit | 101 / 246.54 | 1,000 / 516.83 |

Two seal receipts occur in each run. Chunk max/p95 were not recorded and are **NOT MEASURED**; neither is inferred from these means. Worker normalization sums were 10.86/161.93 s, duplicate-analysis sums 4.57/44.76 s and pending-commit sums 24.90/516.83 s for 50k/500k.

## Memory, disk and foreground latency

MB/GB here use decimal units (10^6/10^9 bytes); JSON preserves exact bytes. API/service/parser/worker run in the **same process**. Memory cannot be attributed separately to those roles. Windows GetProcessMemoryInfo is sampled every 100 ms; short spikes can be missed. OS PeakWorkingSetSize is cumulative for the process, including password-hashing bootstrap/restart.

| Resource | 50k | 500k |
| --- | ---: | ---: |
| Operational sampled shared RSS peak | 103.78 MB | 106.12 MB |
| All-phase sampled RSS peak, including bootstrap/restart | 150.81 MB | 150.52 MB |
| OS cumulative peak working set | 154.64 MB | 153.87 MB |
| All-phase private-bytes peak | 135.44 MB | 134.81 MB |
| Final DB file | 298.98 MB | 3,010.97 MB |
| Final staged table pages, excluding its separately named indexes | 29.39 MB | 293.77 MB |
| Observed peak WAL | 46.43 MB | 116.12 MB |
| Observed peak export temporary file bytes | 4.93 MB | 49.47 MB |
| Final app-data root, including source/export | 308.86 MB | 3,109.91 MB |
| Observed peak app-data root file bytes | 350.03 MB | 3,171.64 MB |

The original generated fixture is a separate sibling of app data; its 4.94/49.47 MB must be added when budgeting the benchmark directory. File byte lengths are not filesystem allocated-block measurements. Final DB/source ratio is roughly 60× for this eight-column workload because staging, immutable manifests, entries, typed cells and indexes coexist.

Disk guards are phase-specific: parse checks at least max(256 MiB, source bytes × 12) for staging; commit's BUILDING-snapshot path checks additional headroom max(512 MiB, selected rows × (2048 + width × 768)), which is 8 KiB/row at eight columns (about 4.096 GB for 500k and 8.192 GB for 1m before accounting for existing files). This distinguishes the parse-only forecast from the later pending/index budget. Neither a single measured ratio nor these guards guarantee every row width, ZIP/string distribution or disk-failure case; runtime errors/checkpoints remain necessary.

| Foreground operation | 50k samples / p95 / max seconds | 500k samples / p95 / max seconds |
| --- | ---: | ---: |
| Durable job status | 404 / 0.055 / 0.187 | 5,020 / 0.159 / 0.655 |
| Indexed amount filter/page on import book | 25 / 0.942 / 0.963 | 255 / 0.956 / 7.608 |
| Versioned update on separate probe book | 25 / 0.304 / 0.306 | 255 / 0.761 / 1.264 |

The measured 500k foreground filter maximum was 7.61 seconds under load. These timings do not establish native UI responsiveness or a no-stall guarantee.

## Recovery and remaining gates

Both runs stop the actual worker immediately after the first durable 500-row parse receipt, close Runtime, reopen the same local data root, authenticate again and resume the same recoverable job. Parsing then reconciles to the exact source count, without duplicate source identity. This is a controlled **graceful checkpoint/restart probe**, not a power-loss or hard-process-kill test. Read/parse resume may reread and skip source records; no O(1) seek claim is made.

Each first confirmation imports only valid rows, keeps invalid rows staged, then patch/revalidate/second-confirm imports the remainder without duplicate lineage. Pending checkpoint progress is explicitly distinct from publication. Final export/count/hash/Decimal-total assertions pass.

No 1m run was made on ancestor45bc; the later final-freeze measurements are listed above. Near-limit XLSX is assigned to the parent after CSV benchmarks finish. Native UI/WebView2/Tauri memory and interaction tests are **NOT RUN** here. Hard-kill/power-loss/disk-full/crash-window coverage and Windows installer acceptance are separate gates. No production-ready or full Excel compatibility claim follows from these CSV runs.
