# Numeric filter query plan

Numeric eq/gte/lte now select entry IDs from accounting_cells with explicit book,
column and scaled-integer predicates. EXPLAIN QUERY PLAN for the actual count and
page SQL uses the existing accounting_cells_number index, with no row-correlated
cell lookup. Core published visibility remains on accounting_entries and retains
its existing predicate. There is no DDL, index hint or durability/audit change.

Tests cover integer/decimal/money/formula, all three operators, exact values above
2**53, multiple conditions, book isolation, date/text conditions, deleted rows,
whole-dataset page totals and real pending→PUBLISHED visibility. Missing newly
added nullable cells keep their previous filter behavior: entries remain in an
unfiltered page but missing cells do not match numeric/null/empty cell filters.
eq null matches a present null cell. Empty gte/lte returns FILTER_INVALID400
instead of constructing an invalid SQLAlchemy comparison. Sort is unchanged;
no inner join can drop older rows that lack a later nullable column.

Targeted suite: 7 PASS in 2.90s. The earlier independent root audit on 1,000
synthetic rows observed 27,716 SQLite VM steps for the old correlated filter and
99 for the proposed ID subquery with the same result. Those fixture-specific
counts are not a throughput or native UI promise. Versioned bulk results use
whole-dataset filter/page wording; older 033 measurements are not relabelled as
measurements of this new query. The shared host has concurrent work from other
chats and CPU/I/O are not pinned.
