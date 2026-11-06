# Read bridge revision 3 — summary display names

Root-owned metadata extension after read bridge v2. The shared contract constant
is `core.contracts.CONTRACT_VERSION = 3`. There is no database migration, new
entity/service, dependency, REST namespace change or numeric/financial change.

## Optional fields

| DTO | Added display metadata |
|---|---|
| `InventoryLineDTO` | `product_name`, `warehouse_name` |
| `InventoryMovementSummaryDTO` | `product_name`, `warehouse_name` |
| `BookSummaryDTO` | `book_name` |

Every new field defaults to `None`. When present it is a strict string of 1–256
Unicode characters with at least one non-whitespace character. No coercion,
trimming, markup execution, lookups or numeric interpretation occurs. Names may
contain Unicode, punctuation and markup-like text as literal data. The rendering
consumer must escape them for its HTML/XML/UI output; a DTO string is not trusted
markup.

These fields mean only the inventory product name, warehouse name or accounting
book name. Producers must populate them from those entity names in the same read
snapshot as their summaries. They must not copy customer names, bank/account
details, contact records, private descriptions, arbitrary notes or other sensitive
fields into these labels. Schema validation cannot establish their source; the
producer owns this restriction. No such producer or rendering change is part of
this shared patch.

## Identity, quantities and compatibility

- Group identity remains `(warehouse_id, product_id)` or `book_id`. Names are
  display metadata and are not unique keys. Equal names cannot merge scopes;
  different/missing names cannot change a scope or its exact quantities.
- Movement reconciliation, component signs, aggregate precision, coverage,
  period/cutoff and money mapping/meaning/subset checks are unchanged. The
  breakdown payload version remains `1`; only the shared read-bridge revision is
  `3`. There is no new hold/QC/approval workflow.
- A v3 reader accepts old v2 inputs with missing names through the `None`
  defaults. This is **not bidirectional wire compatibility**: old v2 decoders use
  `extra='forbid'` and reject the new fields, including fields serialized as null.
  Coordinate producer/consumer versions before sending v3 data.
- Saved old snapshots, hashes and exported bytes are never rewritten/enriched or
  re-rendered by this change. Verify old stored payloads/hashes in their original
  representation; do not replace them with a v3 model dump containing new null
  defaults. Missing legacy names remain unavailable rather than guessed from live
  entity names. New reports may use names only after owner adoption.

## Validation and adoption

`tests/core/test_summary_display_labels.py` covers old inputs/default None, strict
type/empty/length bounds, Unicode, immutable JSON round trips, literal text without
evaluation, ID-based movement scopes and exact amount/money checks with labels.
Existing read-bridge v2/numeric contract tests remain regression coverage.

Validation:

- New label tests + `tests/core/test_read_bridge_v2.py` + the existing aggregate
  contract and Decimal/overflow tests: **86 PASS**, 0.45 seconds.
- `ruff check backend/cafe_fin/core/contracts.py tests/core/test_summary_display_labels.py`:
  **PASS**.
- `git diff --check` for the four owned files: **PASS**.

This patch deliberately does not edit producer modules, reporting consumers or
their existing v2 tests. Root will review the patch and provide its approved
commit to records/accounting/reporting for narrowly scoped label population and
escaped display. No full backend suite or report export was run for this DTO-only
change; those consumer/integration checks belong to adoption.
