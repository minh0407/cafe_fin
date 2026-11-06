# Accounting adoption of read bridge v3

Approved shared commit `206a7e30ce702d8064084c90296aed3634ef28b7` was
cherry-picked unchanged as `6052d13`, after every CSV process exited and its
source/runner hash checks completed. Only the four approved shared files were
included. The coordinator owns the original; do not apply both copies.

Accounting summary captures book.name from the same connection and transaction
as the book schema, data revision and totals. Both mapped and unmapped summaries
include optional book_name. The public provider uses that captured field without
opening another reader or looking up a live name later. Names are display data;
book_id remains identity. Missing/non-string/empty/whitespace-only/over256-character
legacy names produce None. Valid Unicode, whitespace and markup-like text are
preserved literally, without coercion or trimming; the consumer must escape them.
No notes, customer/bank details or other descriptions are used as a fallback.

Totals, metric meanings, signed amounts, currency coverage, visibility and
date/cutoff behavior are unchanged. This is live v3 metadata only: saved reports,
old snapshot hashes and exported bytes are not rewritten. Old v2 consumers must
be upgraded together with the shared contract; v2's strict decoder is not assumed
to accept new serialized fields.

The frozen CSV measurements remain archive3aa8c47. This post-benchmark metadata
delta does not change import/parser/formula/export processing and is not relabelled
as a new million-row measurement. No volume rerun is required for the label.

Validation: focused name/snapshot tests **5 PASS in 2.12s**; existing public API,
meaning and shared-label tests **79 PASS in 17.43s**; final accounting/core suite
**552 PASS in 128.53s**, no skip/xfail/failure. Ruff and Git whitespace checks PASS.
One existing Starlette/httpx deprecation warning remains. Name snapshot tests
forbid new readers and caller close/commit/rollback, retain one book lookup, and
check old name/10.25 against a concurrent rename/write before a fresh31.00 read.
