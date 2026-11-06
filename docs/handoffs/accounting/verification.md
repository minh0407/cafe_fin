# Verification before final bulk measurements

Frozen baseline is foundation-ready-v1/e668355. Approved shared commits were
cherry-picked unchanged: root57a2ed26 ->0da9c87 (read bridge v2), root22ca5431
->59d94da (file/job scopes), root48858654 ->1be5a0f (ApiError.details).
The coordinator already owns those originals; do not apply the copies twice.

PASS: `.venv/Scripts/python.exe -m pytest tests/accounting tests/core -q`:
**465 passed**, no SKIP/XFAIL/FAIL,126.60s on 2026-11-07 after the nullable-schema
compatibility and bounded duplicate-query changes. One existing Starlette/httpx deprecation
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

Parser cancellation now receives the trusted JobContext callback through both
manifest and iterator scans, including skipped/hidden rows and shared strings.
All handles/cache directories close on cancellation. An incomplete parse cannot
be validated or confirmed merely by saving a mapping: the durable parse job must
be COMPLETED. Explicitly changing the selected range starts a new complete parse.

Frontend evidence is separate in ui.md: strict typecheck, bounded grid/actor/cache
tests, real local HTTP/auth/files/jobs flow and explicit1000-row raw clipboard
staging without loading a1000-row React array or auto-publishing. The original
source bytes were compared against FileStore download. The final million-row UI
and near-limit XLSX measurements remain separate opt-in gates until actually run.

Native installer, clean Windows and WebView2 acceptance: NOT RUN by this lane.
No code increment or browser test is called production-ready.
