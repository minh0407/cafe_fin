# Accounting CSV benchmark results — 2026-11-06–07

**All timing tables use a shared, nonexclusive host.** Root/other chats ran local backend/browser tests during reported 500k/1m windows; CPU and I/O were not pinned. Observed durations and latency include that interference. The parent's heavy-work slot controls only this chat, not the whole machine. Plans to avoid heavy work in this chat do not establish a quiet host. Correctness/count/hash checks remain valid; no quiet-host, fastest-case or native-UI performance claim is made for any baseline, historical or later scenario below.

<!-- FINAL-FREEZE -->
## Explicit business-key scenario: 3aa8c47

**All three full-pass runs completed PASS; the sequential command process exited 0 and every Runtime closed.** Artifact timestamps span approximately 01:27–02:19 on 07 November, Asia/Bangkok (UTC+7). Before the parent was told to release source freeze, all 34 archived backend Python files plus the archived runner were rehashed unchanged, checkout sources matched after CRLF normalization, the tracked runner's raw hash matched, and each result retained empty source-change lists and unchanged original-file SHA. The final verification timestamp is in `snapshot-provenance.json`.

Correctness PASS is separate from responsiveness: the measured **1m broad whole-dataset filter/page maximum was 63.593 s** (p95 7.286 s); the foreground update maximum was 13.398 s. These direct service timings include shared-host interference and the explicit-key workload. They are not a native-UI pass or isolated evidence of a particular query change's causal cost. The selected-CODE UI result belongs to its separate versioned UI evidence and must not replace this broad-filter observation.

At benchmark exit the parent scheduled a separate P2 fix for empty filters over historically absent cells and approved readbridge v3 metadata from root commit `206a7e30ce702d8064084c90296aed3634ef28b7`. Neither delta was applied during these measurements. The benchmark uses amount `gte 0`, not `op=empty`; these measurements stay attached to 3aa8c47 and must not be relabelled as timings of a later hash. Targeted post-benchmark semantic tests are a separate gate; metadata/widget-only changes do not retroactively require or establish a new million-row measurement.

Backend and runner freeze: `3aa8c47e4a0301abc64dae1d4fc90a2258b9eed4`. Scenario is `explicit_business_key`, primary business_key_columns=[code]; the foreground probe book retains no explicit business key. Source fixture rows/cells/invalid amounts/exact duplicate pairs match the baseline generator, but schema and code version differ, so timing differences cannot be attributed to a filter rewrite alone. These runs use a new immutable backend archive and fresh roots, sequentially, with full second pass enabled. The unchanged tracked runner loads backend from the archive via PYTHONPATH. The shared host is nonexclusive: root/other chats run local backend/browser workloads. CPU and I/O are not pinned; this parent chat heavy slot does not isolate the whole machine. Durations include observed host interference, not quiet or fastest-case performance. Frontend/docs WIP can make Git dirty, but backend/runner start/end SHA maps must remain unchanged.

Local evidence base: `C:\Users\NC\AppData\Local\Temp\cafe-fin-explicit-3aa8c47-92aa49edf3ef46168e526ca0d2b17847`. Hardware and snapshot provenance are in `hardware-freeze.json` and `snapshot-provenance.json`; per-size `result.json` and `receipt-counts.json` are authoritative. Backend archive SHA-256: `7a6ce9d9b6943519881d168acb5b86a4fec9571a7799bb17d964f68e5bafa98e`.

Machine: Intel(R) Core(TM) i5-14400F, 10 cores/16 logical processors; 34,138,931,200 RAM bytes; Microsoft Windows 11 Pro 10.0.26200; KINGSTON SNV3S1000G NVMe SSD; C: NTFS, 329,615,015,936 free bytes at inventory. Runtime package/SQLite/clock versions are preserved in each JSON.

Byte limits in this freeze: 256 KiB UTF-8 content per source/edited row; each processing chunk is capped by both 4 MiB serialized budget and 500 rows. Formula evaluation shares 100,000 charged operations across a row; its cancellation callback checks the worker lease/stop immediately on stop and throttles durable lease checks to one per 50 ms between callbacks. This is not a hard cancellation-latency guarantee during blocking work. This CSV fixture uses eight short columns and no executable formulas, so it establishes workload performance within those caps, not formula-budget stress coverage. Source-owner authorization uses a real local admin fixture.

| Run | Status |
| --- | --- |
| 50k | PASS |
| 500k | PASS |
| 1m | PASS |

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Actual data rows | 50,000 | 500,000 | 1,000,000 |
| Actual data cells (8 columns) | 400,000 | 4,000,000 | 8,000,000 |
| Invalid amount rows (0.1%) | 50 | 500 | 1000 |
| Extra exact duplicate records / duplicate-group records | 50 / 100 | 500 / 1,000 | 1,000 / 2,000 |
| First published rows | 49,950 | 499,500 | 999,000 |
| Final published / lineage / distinct targets | 50,000 / 50,000 / 50,000 | 500,000 / 500,000 / 500,000 | 1,000,000 / 1,000,000 / 1,000,000 |
| Published attempts | 2 | 2 | 2 |
| Exact final income VND | 17500249.50 | 299997495.00 | 599994990.00 |
| Whole run seconds | 68.13 | 1010.86 | 2041.55 |
| Source SHA unchanged / backend+runner hashes unchanged | PASS / PASS | PASS / PASS | PASS / PASS |

### Measured phase times — shared host

Seconds are measured, not projections. Confirmation phases include their count/lineage/Decimal-total reconciliations and actual foreground probe load. Worker interval sums overlap enclosing phases and must not be added a second time.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| CSV generation | 0.18 | 1.80 | 3.92 |
| Store original | 0.03 | 0.16 | 0.36 |
| First durable parse checkpoint | 0.10 | 0.22 | 0.40 |
| Graceful stop/reopen/resume | 0.20 | 0.22 | 0.24 |
| Resumed parse | 3.27 | 32.04 | 78.99 |
| First validation + duplicate analysis | 26.60 | 369.57 | 773.16 |
| First confirm/publish/reconcile | 32.22 | 516.52 | 981.20 |
| Patch invalid rows | 0.09 | 0.85 | 1.86 |
| Second incremental validation + duplicate analysis | 1.53 | 26.19 | 60.14 |
| Second confirm/publish/reconcile | 1.38 | 25.10 | 58.68 |
| CSV export route/worker + read verification | 0.81 | 17.30 | 38.30 |
| Final source/count/summary reconciliation | 0.99 | 14.23 | 28.81 |

### Process memory and disk — shared host

All memory roles (API/service/parser/worker) share one process. GetProcessMemoryInfo sampling is 100 ms; the OS cumulative peak includes Argon password hashing during bootstrap/restart. Short memory/disk spikes may be missed. Units below are decimal MB/GB; raw bytes are in JSON. Native UI/WebView2/Tauri process memory and interactions are **NOT RUN**.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Operational shared RSS peak | 107.69 MB | 116.31 MB | 120.42 MB |
| All-phase sampled RSS peak | 135.81 MB | 150.69 MB | 153.29 MB |
| OS cumulative peak working set | 153.85 MB | 153.52 MB | 153.30 MB |
| All-phase private bytes peak | 132.15 MB | 132.59 MB | 135.00 MB |
| Final DB bytes | 0.333 GB | 3.361 GB | 6.732 GB |
| Final staged table pages (excluding separate indexes) | 34.26 MB | 342.66 MB | 685.34 MB |
| Peak observed WAL | 84.81 MB | 1657.46 MB | 4458.50 MB |
| Peak observed temporary file bytes | 4.94 MB | 49.47 MB | 98.94 MB |
| Final app-data root bytes | 0.343 GB | 3.460 GB | 6.930 GB |
| Peak observed app-data root bytes | 0.413 GB | 5.004 GB | 11.082 GB |
| Separate generated fixture bytes | 4.94 MB | 49.47 MB | 98.94 MB |

### Whole-dataset filter/page and foreground latency — shared host

Count / p95 seconds / maximum seconds. These are real status reads, whole-dataset amount filter/page reads, and versioned foreground updates on a separate synthetic book while background work runs. Their p95 mixes pending/hidden and published states, not a steady-state fully published dataset measurement. They do not establish native UI responsiveness.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Job status | 512 / 0.042 / 0.146 | 4,905 / 0.084 / 0.882 | 9,351 / 0.079 / 0.965 |
| Whole-dataset filter/page | 29 / 0.543 / 0.580 | 250 / 9.679 / 22.478 | 472 / 7.286 / 63.593 |
| Versioned update | 29 / 0.233 / 0.351 | 250 / 1.684 / 5.594 | 472 / 1.305 / 13.398 |

### Chunk intervals and recovery — shared host

Measured sum / actual receipt count / mean interval ms, inclusive of computation/query/writer overhead from previous durable chunk through the next chunk. They are not pure writer transaction durations. Chunk max/p95 were **NOT MEASURED**.

| Worker phase | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Parse | 3.19s / 100 / 31.89ms | 31.74s / 1,000 / 31.74ms | 78.36s / 2,000 / 39.18ms |
| Normalize | 12.22s / 101 / 121.02ms | 184.43s / 1,001 / 184.24ms | 403.52s / 2,002 / 201.56ms |
| Duplicate analysis | 13.76s / 101 / 136.22ms | 176.89s / 1,001 / 176.71ms | 349.43s / 2,002 / 174.54ms |
| Selection snapshot | 5.53s / 101 / 54.80ms | 57.43s / 1,000 / 57.43ms | 115.51s / 2,000 / 57.76ms |
| Pending commit | 25.26s / 101 / 250.05ms | 431.87s / 1,000 / 431.87ms | 819.42s / 2,000 / 409.71ms |

Each completed run retains the first 500-row durable parse receipt across a real graceful worker stop, Runtime close/reopen, reauthentication and resume. This is **not a hard-kill/power-loss probe**. The full second pass patches only invalid rows and revalidates/imports the remainder; unique lineage/count/sum/hash/export assertions must all pass. No O(1) CSV/XLSX resume claim is made.

Source hashes for completed runs:
- 50k: `9c87f97d31804643f11d02d93598dd5a227c5fb55eff047c390f67e1aa224a8f`; export 50,000 rows × 8 columns, 4,942,132 bytes.
- 500k: `90e6fe02415772dc67373ae510df7497e605dc4b3b8a01c01da98dd88d8df454`; export 500,000 rows × 8 columns, 49,470,456 bytes.
- 1m: `3ea60b4f631c0bdfe531faa9c96b3f8505a514f610e17b47ec09a5b94e4f019f`; export 1,000,000 rows × 8 columns, 98,940,806 bytes.

Near-limit XLSX and native UI/native-memory gates are assigned to the parent after CSV benchmarks finish. No production-ready or universal-speed claim follows from these workload measurements.
<!-- END-FINAL-FREEZE -->

## Released preparation provenance: 3aa8c47

During this explicit-code 500k run, the parent reported that root frontend/core tests were running on the shared host and might overlap 1m as well. The observation is retained with its report time in `snapshot-provenance.json.host_load_notes`. The 500k whole-dataset amount filter/page sampled p95 9.679 s and max 22.478 s, and peak observed WAL reached 1.657 GB. These are actual measurements with concurrent host load, a broad matching predicate and this explicit-key schema; they do not isolate a causal index-regression or unloaded speed. The pipeline continued without code changes or reruns.

The 1m app-data tree peaked at 11.082 GB while the final retained tree was 6.930 GB; observed WAL peaked at 4.459 GB. This includes only files visible under that app-data root. Separate generated fixture bytes are listed above; SQLite/OS temporary files outside the root were **NOT MEASURED**. The phase-specific free-space estimates and 30 GiB benchmark guard are not universal limits on WAL growth pinned by long reads or concurrent host writes. Actual free C: bytes before 50k/500k/1m were 329,739,665,408 / 329,434,722,304 / 325,848,403,968 respectively.

Current backend/runner freeze is `3aa8c47e4a0301abc64dae1d4fc90a2258b9eed4` (parent-reported full tests 479 PASS). The parent explicitly released CSV after its UI processes closed. Fresh sequential 50k/500k/1m runs now use `--business-key-columns code`, full repair, confirmation, export and restart assertions. This release coordinates this chat only and does not isolate the shared host. Actual completed results are listed above; no uncompleted size is extrapolated.

Preparation root: `C:\Users\NC\AppData\Local\Temp\cafe-fin-explicit-3aa8c47-92aa49edf3ef46168e526ca0d2b17847`. Archive `backend-runner-freeze.zip` SHA-256: `7a6ce9d9b6943519881d168acb5b86a4fec9571a7799bb17d964f68e5bafa98e`. All **34 backend Python sources plus the tracked runner** matched this archive after CRLF-to-LF normalization before release. Raw archive and checkout-runner hashes are saved in `snapshot-provenance.json`. All three roots/outputs were absent at preparation and are created only as each released run starts. Free C: bytes at preparation were 329,615,015,936 (329.62 GB); the sequential command set enforces the same conservative 30 GiB/hash/fresh-root/exit guards before each size.

3aa8 adds the separately tested text/date filter rewrite after the parent's actual 9a UI CODE-filter timeout. Its committed [text/date filter plan tests](../../../tests/accounting/test_text_filter_index.py) capture both count/page statements, assert the `accounting_cells_text` plan, preserve book/deleted/published semantics and leave core visibility correlation intact. Plan-test evidence is distinct from the actual CSV timings above and does not relabel old CSV/9a UI observations. Report labels remain **whole-dataset filter/page** on a shared nonexclusive host. Parser-module SHA matches the archived 8b parser, so this CSV scenario neither changes nor reruns the separately versioned parser-only XLSX measurement merely because of DateInput changes.

## Superseded 9a52f02 CSV preparation — NEVER RUN

The former CSV preparation used `9a52f023e96cf6d7a06e4f0fdda6efabf60fc4d7` and is now `SUPERSEDED_NOT_RUN` for CSV only. **No Runtime or CSV benchmark ever started from that preparation**. Its former `.ps1` now refuses execution and is retained as original command text alongside the immutable archive. The parent's separate 9a UI measurement did run and its selective CODE-text filter timed out beyond 60 seconds; that failure and its measured pages remain versioned in the UI evidence and are not deleted or renamed as 3aa8 results.

Preparation root: `C:\Users\NC\AppData\Local\Temp\cafe-fin-explicit-9a52f02-f6ae995f9c174e4a9cf76f9b53aa253a`. Archive `backend-runner-freeze.zip` SHA-256: `be399a2f3f5596bc614dc79e4c5aa58d5f4be642a2cdd941c061559dbe903cd3`. All **34 backend Python files and the tracked runner** match the archive after CRLF-to-LF normalization. Raw archived hashes and checkout-runner hash are in `snapshot-provenance.json`. The three fresh run roots/outputs did not exist; `prepared-sequential-commands.ps1` passed syntax parsing only and was not executed. Preparation observed 329,682,378,752 free bytes (329.68 GB); source/runner hashes and a conservative 30 GiB headroom floor are checked again before each run. This is not a disk reservation against other chats' writes.

9a52 contains a separately committed numeric-filter rewrite. Its committed [numeric filter tests](../../../tests/accounting/test_numeric_filter_index.py) capture actual count/page SQL and use EXPLAIN QUERY PLAN to assert `accounting_cells_number` for integer/decimal/money/formula numeric operators, book scoping and removal of the numeric cell row-correlation; core published-visibility checks remain. The parent reports full tests 472 PASS. That plan evidence applies to **9a52's tested queries only**: no 9a52 CSV timing exists yet, and it must not be attached retroactively to 033/45bc observations. Report operation labels remain **whole-dataset filter/page**. Legacy raw runner JSON metadata may contain the older word “indexed”; that label alone is not query-plan evidence.

## Superseded 8b70f1f preparation — NEVER RUN

The immutable backend/runner freeze was `8b70f1ffbee4a30ceaa5a3c8458fd78f84c8d08a`; a frontend-only DateInput cherry-pick did not change it. It is now `SUPERSEDED_NOT_RUN`, replaced by 9a52: **no Runtime or benchmark process ever started from this 8b preparation**. Its former `.ps1` now refuses execution; the original command text and immutable archive are retained only as provenance, not acceptance evidence.

Preparation root: `C:\Users\NC\AppData\Local\Temp\cafe-fin-explicit-8b70f1f-961736beb7df4f9e8a412362e3bcaf25`. `backend-runner-freeze.zip` has SHA-256 `c52f200e2267d21d848906426477c5374fb7096e6627d2e7939108a5aaab78e3`. All **34 backend Python files plus the tracked runner** match the archived freeze after CRLF-to-LF normalization; raw archived-file and checkout-runner hashes are in `snapshot-provenance.json`. The archive includes the runner for byte provenance while future execution uses the unchanged worktree runner and PYTHONPATH pointing to archived backend.

At preparation the command text passed syntax parsing without execution and specified fresh 50k/500k/1m roots/outputs with `--business-key-columns code`, exit/hash/headroom guards. All three roots/outputs were absent. Observed C: free bytes then were 329,918,947,328 (329.92 GB). No data, timing or acceptance result is inferred; do not execute this superseded command set.

<!-- HISTORICAL-033E900 -->
## Completed baseline: 033e900 (no explicit business key)

The baseline artifact window spans approximately 23:37 on 06 November to 00:19 on 07 November, Asia/Bangkok (UTC+7). The 1m result was written at `2026-11-06T17:19:18Z`; durations below use the monotonic clock, independently of the midnight rollover.

All three benchmark processes exited with code 0 and Runtime closed. Afterward, all 33 archived backend source hashes and the benchmark runner's pre-change hash were verified again unchanged. This was recorded in `snapshot-provenance.json` before the parent released freeze033. The large-run measurements below use **no explicit business key**; they do not cover the subsequently requested compatibility/index changes.

After release, only the runner's CLI was extended for the next scenario: `--business-key-columns code` (one or more whitelisted stable IDs, no repetitions). JSON records `scenario.name='explicit_business_key'` and the ID list; the default is `no_business_key` with unchanged original book semantics. Only the primary book gets a copied key list; the foreground probe book keeps its original semantics. The eight-column fixture, 0.1% invalid rows and exact duplicate pairs are unchanged. No new 50k/500k/1m acceptance measurement is claimed for the changed runner/backend until the next committed freeze.

Lightweight runner verification after release: Ruff and py_compile PASS; unknown/repeated IDs rejected with argparse exit 2; 2,000-row explicit-key smoke PASS against archived033 (`Temp\cafe-fin-benchmark-4i2hhgon\data-result.json`), with persisted primary `['code']` and unchanged probe/global semantics; 2-row default smoke PASS (`Temp\cafe-fin-benchmark-i85uj9v_\data-result.json`), with no business-key schema change. These are CLI smoke checks, not performance evidence for the parent's compatibility fixes. No benchmark process remained running after them.

Backend freeze: `033e900fbceda1a04cb722b183b038365990a87a` (backend code d08f7cd). All three baseline sizes completed before freeze release. A later compatibility/index update and an explicit business-key scenario are pending; these figures must remain tied to 033, rather than relabelled as measurements of later code. These runs use a new immutable backend archive and fresh roots, sequentially, with full second pass enabled. The unchanged tracked runner loads backend from the archive via PYTHONPATH. The parent reserved this chat's heavy-work slot, but root/other chats ran local backend/browser tests during 500k/1m on the same shared host. CPU/I/O were not pinned, and measured times include concurrent load. Frontend/docs WIP can make Git dirty, but backend/runner start/end SHA maps must remain unchanged.

Local evidence base: `C:\Users\NC\AppData\Local\Temp\cafe-fin-final-033e900-683b8f62fae848e1a7aa50259e323a6f`. Hardware and snapshot provenance are in `hardware-freeze.json` and `snapshot-provenance.json`; per-size `result.json` and `receipt-counts.json` are authoritative. Backend archive SHA-256: `14838fb1ce229a4ef6cdd0249b72cda4bdaf8ff0e39ab9ee21747ac8ec7f1d40`.

Machine: Intel(R) Core(TM) i5-14400F, 10 cores/16 logical processors; 34,138,931,200 RAM bytes; Microsoft Windows 11 Pro 10.0.26200; KINGSTON SNV3S1000G NVMe SSD; C: NTFS, 346,696,683,520 free bytes at inventory. Runtime package/SQLite/clock versions are preserved in each JSON.

Byte limits in this freeze: 256 KiB UTF-8 content per source/edited row; each processing chunk is capped by both 4 MiB serialized budget and 500 rows. Formula evaluation shares 100,000 charged operations across a row; its cancellation callback checks the stop flag on invocation and throttles durable lease checks to one per 50 ms. This is not a hard 50 ms latency guarantee during blocking work. This CSV fixture uses eight short columns and no executable formulas, so it establishes workload performance within those caps, not formula-budget stress coverage. Source-owner authorization uses a real local admin fixture.

| Run | Status |
| --- | --- |
| 50k | PASS |
| 500k | PASS |
| 1m | PASS |

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Actual data rows | 50,000 | 500,000 | 1,000,000 |
| Actual data cells (8 columns) | 400,000 | 4,000,000 | 8,000,000 |
| Invalid amount rows (0.1%) | 50 | 500 | 1000 |
| Extra exact duplicate records / duplicate-group records | 50 / 100 | 500 / 1,000 | 1,000 / 2,000 |
| First published rows | 49,950 | 499,500 | 999,000 |
| Final published / lineage / distinct targets | 50,000 / 50,000 / 50,000 | 500,000 / 500,000 / 500,000 | 1,000,000 / 1,000,000 / 1,000,000 |
| Published attempts | 2 | 2 | 2 |
| Exact final income VND | 17500249.50 | 299997495.00 | 599994990.00 |
| Whole run seconds | 62.31 | 902.59 | 1502.86 |
| Source SHA unchanged / backend+runner hashes unchanged | PASS / PASS | PASS / PASS | PASS / PASS |

### Baseline phase times — shared-host observations

Seconds are measured, not projections. Confirmation phases include their count/lineage/Decimal-total reconciliations and actual foreground probe load. Worker interval sums overlap enclosing phases and must not be added a second time.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| CSV generation | 0.18 | 1.91 | 3.93 |
| Store original | 0.03 | 0.22 | 0.33 |
| First durable parse checkpoint | 0.12 | 0.29 | 0.40 |
| Graceful stop/reopen/resume | 0.22 | 0.27 | 0.23 |
| Resumed parse | 3.91 | 44.02 | 72.62 |
| First validation + duplicate analysis | 17.59 | 207.11 | 360.49 |
| First confirm/publish/reconcile | 34.53 | 611.02 | 1005.17 |
| Patch invalid rows | 0.14 | 0.89 | 1.60 |
| Second incremental validation + duplicate analysis | 1.83 | 9.85 | 14.91 |
| Second confirm/publish/reconcile | 1.18 | 11.42 | 19.10 |
| CSV export route/worker + read verification | 0.98 | 8.96 | 13.31 |
| Final source/count/summary reconciliation | 0.73 | 4.90 | 8.15 |

### Process memory and disk — shared-host run

All memory roles (API/service/parser/worker) share one process. GetProcessMemoryInfo sampling is 100 ms; the OS cumulative peak includes Argon password hashing during bootstrap/restart. Short memory/disk spikes may be missed. Units below are decimal MB/GB; raw bytes are in JSON. Native UI/WebView2/Tauri process memory and interactions are **NOT RUN**.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Operational shared RSS peak | 103.17 MB | 107.09 MB | 109.36 MB |
| All-phase sampled RSS peak | 153.53 MB | 150.79 MB | 153.27 MB |
| OS cumulative peak working set | 153.53 MB | 153.76 MB | 153.28 MB |
| All-phase private bytes peak | 135.39 MB | 135.29 MB | 134.77 MB |
| Final DB bytes | 0.299 GB | 3.011 GB | 6.018 GB |
| Final staged table pages (excluding separate indexes) | 29.39 MB | 293.77 MB | 587.38 MB |
| Peak observed WAL | 31.68 MB | 114.84 MB | 193.10 MB |
| Peak observed temporary file bytes | 4.46 MB | 49.47 MB | 98.94 MB |
| Final app-data root bytes | 0.309 GB | 3.110 GB | 6.215 GB |
| Peak observed app-data root bytes | 0.334 GB | 3.160 GB | 6.313 GB |
| Separate generated fixture bytes | 4.94 MB | 49.47 MB | 98.94 MB |

### Foreground latency — shared-host observations

Count / p95 seconds / maximum seconds. These are real status reads, whole-dataset amount filter/page reads, and versioned foreground updates on a separate synthetic book while background work runs. They mix periods with pending/hidden rows and periods after publication, so their p95 is not a steady-state fully published dataset benchmark. They do not establish native UI responsiveness.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Job status | 450 / 0.058 / 0.228 | 5,207 / 0.156 / 1.379 | 8,829 / 0.104 / 0.908 |
| Amount filter/page | 27 / 0.528 / 0.551 | 264 / 1.055 / 7.525 | 446 / 1.517 / 11.455 |
| Versioned update | 27 / 0.329 / 0.482 | 264 / 0.753 / 1.121 | 446 / 0.808 / 1.633 |

### Chunk intervals and recovery — shared-host observations

Measured sum / actual receipt count / mean interval ms, inclusive of computation/query/writer overhead from previous durable chunk through the next chunk. They are not pure writer transaction durations. Chunk max/p95 were **NOT MEASURED**.

| Worker phase | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Parse | 3.81s / 100 / 38.14ms | 43.62s / 1,000 / 43.62ms | 72.02s / 2,000 / 36.01ms |
| Normalize | 12.19s / 101 / 120.69ms | 158.97s / 1,001 / 158.81ms | 260.76s / 2,002 / 130.25ms |
| Duplicate analysis | 4.51s / 101 / 44.69ms | 47.85s / 1,001 / 47.80ms | 98.80s / 2,002 / 49.35ms |
| Selection snapshot | 6.65s / 101 / 65.88ms | 68.34s / 1,000 / 68.34ms | 118.48s / 2,000 / 59.24ms |
| Pending commit | 26.94s / 101 / 266.71ms | 538.71s / 1,000 / 538.71ms | 879.48s / 2,000 / 439.74ms |

Each completed run retains the first 500-row durable parse receipt across a real graceful worker stop, Runtime close/reopen, reauthentication and resume. This is **not a hard-kill/power-loss probe**. The full second pass patches only invalid rows and revalidates/imports the remainder; unique lineage/count/sum/hash/export assertions must all pass. No O(1) CSV/XLSX resume claim is made.

Source hashes for completed runs:
- 50k: `9c87f97d31804643f11d02d93598dd5a227c5fb55eff047c390f67e1aa224a8f`; export 50,000 rows × 8 columns, 4,942,132 bytes.
- 500k: `90e6fe02415772dc67373ae510df7497e605dc4b3b8a01c01da98dd88d8df454`; export 500,000 rows × 8 columns, 49,470,456 bytes.
- 1m: `3ea60b4f631c0bdfe531faa9c96b3f8505a514f610e17b47ec09a5b94e4f019f`; export 1,000,000 rows × 8 columns, 98,940,806 bytes.

Near-limit XLSX and native UI/native-memory gates are assigned to the parent after CSV benchmarks finish. No production-ready or universal-speed claim follows from these workload measurements.
<!-- END-HISTORICAL-033E900 -->

<!-- HISTORICAL-EB4B007 -->
## Superseded intermediate freeze: eb4b007

Backend freeze: `eb4b007c1c2ff4b2450a6fd665dd3fa04d48af45`. Its 50k run passed. The parent then required approved core owner-scope helper `22ca543`, superseding this freeze; its 500k run was intentionally interrupted and its 1m run was not started. This section is historical evidence, **not final acceptance of the later helper-enabled backend**. These runs use an immutable backend archive and fresh roots with full second pass enabled. The unchanged tracked runner loads backend from the archive via PYTHONPATH. This chat's slot did not make the shared host exclusive; root/other-chat backend/browser activity and unpinned CPU/I/O limit timing interpretation as stated above. Frontend/docs WIP can make Git dirty, but backend/runner start/end SHA maps must remain unchanged.

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

### Historical phase times — shared-host observations

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

### Process memory and disk — shared-host run

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

### Foreground latency — shared-host observations

Count / p95 seconds / maximum seconds. These are real status reads, whole-dataset amount filter/page reads, and versioned foreground updates on a separate synthetic book while background work runs. They do not establish native UI responsiveness.

| Metric | 50k | 500k | 1m |
| --- | ---: | ---: | ---: |
| Job status | 499 / 0.316 / 0.721 | — | — |
| Amount filter/page | 29 / 0.596 / 0.665 | — | — |
| Versioned update | 29 / 0.402 / 0.955 | — | — |

### Chunk intervals and recovery — shared-host observations

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
<!-- END-HISTORICAL-EB4B007 -->

## Historical ancestor freeze 45bc4165

The following historical 50k/500k runs **PASS** on ancestor backend `45bc4165f836fcdfe99007232078b630b422cf86`. Later versioned baseline measurements and the prepared scenario status are listed above. These ancestor figures are retained as history and must not be relabelled as measurements of the later code.

## Source and machine

The actual backend was loaded through PYTHONPATH from a `git archive` of the frozen commit, isolated in user Temp. The unchanged frozen runner stayed in the worktree so its Git provenance checks worked. All 33 archived backend Python sources match the checkout after CRLF-to-LF normalization; the archive preserves Git LF bytes and the Windows checkout uses CRLF for accounting files. Both result JSONs have unchanged source hash maps (`files_changed_during_run=[]`). The runner's generic conservative `immutable_release_evidence=false` flag is not a statement that the external archived snapshot was changed: `snapshot-provenance.json` and archive SHA establish this particular frozen source. These are backend workload results, not release/installer acceptance.

Hardware was queried using Get-CimInstance, Get-PhysicalDisk and Get-Volume: Intel Core i5-14400F, 10 cores/16 logical processors; 34,138,931,200 bytes observed RAM; Windows 11 Pro 64-bit 10.0.26200; KINGSTON SNV3S1000G **NVMe SSD**, 1,000,204,886,016 bytes; C: NTFS, about 352.27 GB free before runs. The host was shared and nonexclusive: root/other chats ran local backend/browser tests during reported 500k/1m windows; CPU/I/O were not pinned. These ancestor runs were sequential within this chat only, not isolated from the rest of the machine.

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

## Historical timings on a shared nonexclusive host

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
| Whole-dataset amount filter/page on import book | 25 / 0.942 / 0.963 | 255 / 0.956 / 7.608 |
| Versioned update on separate probe book | 25 / 0.304 / 0.306 | 255 / 0.761 / 1.264 |

The measured 500k foreground filter maximum was 7.61 seconds under load. These timings do not establish native UI responsiveness or a no-stall guarantee.

## Recovery and remaining gates

Both runs stop the actual worker immediately after the first durable 500-row parse receipt, close Runtime, reopen the same local data root, authenticate again and resume the same recoverable job. Parsing then reconciles to the exact source count, without duplicate source identity. This is a controlled **graceful checkpoint/restart probe**, not a power-loss or hard-process-kill test. Read/parse resume may reread and skip source records; no O(1) seek claim is made.

Each first confirmation imports only valid rows, keeps invalid rows staged, then patch/revalidate/second-confirm imports the remainder without duplicate lineage. Pending checkpoint progress is explicitly distinct from publication. Final export/count/hash/Decimal-total assertions pass.

No 1m run was made on ancestor45bc; the later final-freeze measurements are listed above. Near-limit XLSX is assigned to the parent after CSV benchmarks finish. Native UI/WebView2/Tauri memory and interaction tests are **NOT RUN** here. Hard-kill/power-loss/disk-full/crash-window coverage and Windows installer acceptance are separate gates. No production-ready or full Excel compatibility claim follows from these CSV runs.
