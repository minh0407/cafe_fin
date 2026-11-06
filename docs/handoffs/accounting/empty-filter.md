# P2: blank filters include historical missing cells

After a nullable column was added, old rows rendered blank but were omitted by
the empty filter because they had no physical cell. The independent HTTP repro
confirmed this for text/date/money. This was an existing defect, not an intended
distinction between missing and null values for the blank filter.

Only op=empty changes: an entry matches when no same-book/same-column/same-row
cell has a non-null, nonempty text value. Missing cells, null and empty values
therefore match; stored numeric zero remains populated. Outer book, published
visibility, deletion, other filters and sorting are unchanged. No backfill,
migration, new operator, original-file write or report rewrite is performed.
Equality-to-null retains its separate existing contract for present-null cells.

Post-benchmark validation: focused empty/numeric/text tests **20 PASS in 8.81s**.
The independent root repro also **6 PASS in 6.42s** with the current worktree
pytest configuration/backend path explicitly selected. Its first invocation
auto-selected the archived review checkout's pytest configuration and correctly
reproduced that old source's failure; that invocation is not evidence against
the patched code.

New HTTP tests cover missing/null/empty/populated/zero values, text/date/money,
book boundaries, intersections, whole-page totals, deleted rows, real pending
and published rows, and absence of a backfill. not_empty remains unsupported.

The CSV volume measurements remain tied to immutable archive3aa8c47. This later
blank-filter delta was applied only after all three processes exited and their
hash checks passed. Those CSV scenarios use amount gte0 and do not exercise this
operator; their source hashes are not relabelled as post-fix measurements.
