# Accounting final handoff

Branch `codex/cafe-fin-accounting-20261106`; worktree
`C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`.
No push, merge or READY tag. Coordinator owns registry integration and release.

## Final deltas after the integrated 3aa8c47 baseline

| Owned commit | Result |
|---|---|
| ae495d7 | P2 empty filter includes missing historical cells; no backfill |
| 8312023 | v3 book_name comes from the totals read snapshot |
| e0359c1 | SchemaEditor freezes exact uncertain commands and fences actor/epoch callbacks |

Apply the final harness/evidence commit too; its ID is in the final chat handoff.
Full owned/shared chronology is in [integration-order.md](integration-order.md).
Approved shared v3 original206a7e30 is copied locally as6052d13; coordinator must
not apply both. Other approved shared copies are also listed separately there.

## Verification

| Scope | Actual result |
|---|---|
| Accounting + core, post-P2/v3 | 552 PASS, 128.53s; no skip/xfail/failure |
| Independent root blank/sort repro | 6 PASS on the explicitly selected patched backend |
| Shared DateInput consumer | 13/13 PASS |
| Standard accounting helper/mock browser | 17/17 PASS, latest24.5s |
| Schema command regressions | 11/11 PASS21.9s, including real POST/PATCH lost-ACK replay |
| Normal real API/clipboard1000 | PASS21.7s, total23.7s |
| Strict frontend/harness TypeScript + build | PASS; baseline bundle warning remains |
| Actual persisted-million-row Chromium | PASS1.8min; at most200 cached/UI rows at checkpoints,19 DOM rows |

The real SchemaEditor replay leaves one book for POST and one added schema
revision for PATCH, with the exact same body/key/path/method/version. Generation
or editor-epoch changes suppress stale callbacks and retire the old actor UI.
Two explicit direction-value Inputs and collapsed advanced JSON stay within the
same component. No backend schema/import math change accompanies that UI fix.

## Versioned volume evidence

All three CSV runs used immutable archive3aa8c47, eight columns, explicit
business_key_columns=[code], real workers/WAL/foreground requests, graceful parse
checkpoint restart and full partial-import→repair→second-confirm→export.

| Data rows | Full correctness result | End-to-end seconds |
|---:|---|---:|
| 50,000 | PASS | 68.13 |
| 500,000 | PASS | 1010.86 |
| 1,000,000 | PASS | 2041.55 |

Each final published/lineage/target count matches. The 1m result has two attempts
and599,994,990.00VND; original bytes and all archived/backend/runner hashes were
unchanged at process exit. P2/v3 deltas follow that archive and are not relabelled
as measured source. Their narrow tests are separate; no extra million-row run.

Actual worksheet-limit XLSX parser:1,048,575 data rows plus header,8,388,600 cells,
PASS610.913s; full/tail/source hashes match. Tail-first-row reread latency is
221.727s. This is a generated inline-string parser-only test, not a populated
shared-string-spool or end-to-end XLSX import-job benchmark.

See [benchmark-results.md](benchmark-results.md),
[xlsx-benchmark-method.md](xlsx-benchmark-method.md) and [ui.md](ui.md) for exact
paths, raw bytes, hashes, phase/memory figures and retained failures.

## Material limits and remaining coordinator gates

This is a shared host with other chats' backend/browser/core tests and unpinned
CPU/I/O. CSV1m broad whole-dataset filter/page p95=7.286s, max=63.593s; peak WAL
4.459GB and measured app-data root peak11.082GB. Correctness PASS is not a
responsiveness/native acceptance claim. OS/SQLite temp outside app-data was not
measured. Standalone UI probes were around6–7s; UI memory is sampled/checkpointed,
Vite/Chromium with eager module preload, not native/release/lifetime maxima.

One earlier normalflow export UI attempt showed COMPLETED without a download
action; its raw status response was not captured. A later normalflow passed and
captured two COMPLETED responses with valid file IDs. The suggested two-reader
race remains an inference, preserved in ui.md, not a confirmed or repaired bug.

Native WebView2, clean-Windows installer and integrated registry build/release
remain coordinator gates. Apply shared-integration.patch while preserving every
other lane; production CSP/origins/dev1420 remain unchanged. Test-only accounting
harnesses use exact loopback1424 and refuse existing listeners.
