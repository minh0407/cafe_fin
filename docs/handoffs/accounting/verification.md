# Verification and versioned measurements

Frozen baseline is foundation-ready-v1/e668355. Approved shared commits were
cherry-picked unchanged: root57a2ed26 ->0da9c87 (read bridge v2), root22ca5431
->59d94da (file/job scopes), root48858654 ->1be5a0f (ApiError.details).
The coordinator already owns those originals; do not apply the copies twice.

PASS: `.venv/Scripts/python.exe -m pytest tests/accounting tests/core -q`:
**552 passed**, no SKIP/XFAIL/FAIL,128.53s on 2026-11-07, including the independent
P2 blank-filter correction and read-bridge v3 book names. Current backend producer
commit is `831202301cb96ffdb6537bf9eb760b4e69f81ba2`.
The completed CSV volume archive remains `3aa8c47e4a0301abc64dae1d4fc90a2258b9eed4`;
post-benchmark deltas are tested and versioned separately, not relabelled.
One existing Starlette/httpx deprecation
warning remains. Ruff PASS; scoped Git whitespace check PASS.

The full run includes real file-backed WAL databases, real worker/foreground
writes, the independent review repros, shared helper authorization on source
reference ingress/replay, missing/ambiguous file provenance and UUID aliases,
published visibility, immutable source/formula provenance, partial repair/import,
chunk receipts/checkpoints, actual os._exit subprocess crashes and restart/resume,
schema locks during retained attempts, additive upgrade/checksum rejection,
same-day/inclusive periods, v2 null-vs-known meanings, exact Decimal totals,
row/chunk budgets and cooperative XML/SST/CSV cancellation.

The latest run also covers nullable additions with historical null fields,
keep/confirm and final live business-key rechecks, create/update/restore against
equivalent historical values, rejection of nonblank conflicting values, locked
duplicate-rule changes, bounded exact-pair result groups, unused pre-data schemas,
display-revision grouping and real accounting migration 1→2 preservation of
rows, original bytes/hash, audit and the applied migration-1 checksum.
Numeric filter regressions additionally verify exact scaled values above 2**53,
all numeric kinds/operators, actual count/page EXPLAIN plans, missing/null cells,
multiple filters, book/deletion boundaries and pending-to-published visibility.
Text/date regressions verify their actual count/page index plans, literal LIKE
escaping, null/missing cells, numeric intersections, sort preservation and real
pending visibility. The earlier real-million-row CODE-filter timeout on 9a52
remains failed evidence; see text-filter.md and ui.md for the subsequent retry.
The later blank-filter tests include missing historical cells with null/empty
ones while excluding zero, without a backfill. The independent root repro's
six HTTP/sort cases pass against the explicitly selected patched backend.
Read-bridge v3 tests preserve literal names, reject invalid legacy labels to
None and verify concurrent name/totals changes under one caller-owned snapshot.

Parser cancellation now receives the trusted JobContext callback through both
manifest and iterator scans, including skipped/hidden rows and shared strings.
All handles/cache directories close on cancellation. An incomplete parse cannot
be validated or confirmed merely by saving a mapping: the durable parse job must
be COMPLETED. Explicitly changing the selected range starts a new complete parse.

Frontend evidence is separate in ui.md: strict typecheck, bounded grid/actor/cache
tests, real local HTTP/auth/files/jobs flow and explicit1000-row raw clipboard
staging without loading a1000-row React array or auto-publishing. The original
source bytes were compared against FileStore download. The real persisted-million
row Chromium case now PASSes with at most 200 cached/UI rows at measured
checkpoints and at most 19 DOM rows. Its sampled heap/RSS, 6–7s observed API
probes, prior failures and Vite/shared-host limits are recorded in ui.md.
The actual worksheet-limit XLSX parser run also PASSed: 1,048,575 data rows,
8,388,600 cells and exact full/tail/source hashes, with reread latency reported.
See xlsx-benchmark-method.md for its parser-only/inline-string scope; it is not
an end-to-end XLSX job or populated shared-string-spool performance claim.

Native installer, clean Windows and WebView2 acceptance: NOT RUN by this lane.
No code increment or browser test is called production-ready.
