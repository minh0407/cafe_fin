# Text/date filter query plan and retained failure

The real one-million-row Chromium harness on backend 9a52f02 reached auth/API,
then the exact CODE text filter exceeded its 60,000 ms HTTP deadline before the
feature mounted. The first 200-row page took 6,126.7 ms and page 5,000 took
6,915.8 ms; both returned total=1,000,000. Source SHA/size/mtime stayed unchanged.
The failure is retained at the synthetic clone's
`ui-attempt-002-code-filter-timeout` directory. Failed elapsed time beyond the
configured deadline was not captured. This is shared-host observed evidence,
not a quiet-machine measurement or a successful million-row UI result.

Remaining cell filters now select entry IDs through the same book/column/value
subquery used by numeric filters. The actual text/date eq/gte/lte count/page
plans use accounting_cells_text rather than a row-correlated cell lookup. The
original condition expression is retained for contains and empty; literal LIKE
escaping, null/missing behavior, sorting and core published visibility are
unchanged. There is no DDL, index hint, inner join or global predicate change.

Targeted tests: 7 PASS in 3.05s, covering text/date plans, %, _, slash, Unicode
and quote literals, empty/present-null/physically missing cells, unfiltered old
rows, numeric/text/date intersections, book boundaries, whole-page totals,
deleted rows, sort semantics and real pending→PUBLISHED visibility. These tests
do not replace the actual failed CODE-filter scenario. Its subsequent result is
reported separately in ui.md, with the original failure preserved.
