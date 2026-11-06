# Reporting integration requests (development baseline e668355)

No shared/core/registry/dependency changes were authored by this lane; only the
exact coordinator-approved cherry-picks below are included.

Update: coordinator approved root commit `57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a`,
cherry-picked exactly as `64ae735`. The only shared-file changes on this branch
are those authorized commits: `57a2ed2` -> `64ae735`, and OS adapter
`13222da` -> `84abda4`. Items 2 and 3 below are resolved at DTO level and
covered by a real-v2 typed consumer test; concrete providers remain integration work.

1. **Bind public providers**: register `reporting.module.module_manifest(source=...)` and
   frontend `reportingFeature`. `source.capture(first,last,book_ids,cutoff)` returns a
   reporting `SourceBundle` containing frozen core InventorySummaryDTO/BookSummaryDTO.
   `source_factory(runtime)` is also accepted, so coordinator can bind after Runtime
   services exist. `AtomicSources(runtime.reader, records_public_helper,
   accounting_public_helper)` explicitly BEGINs a read-only SQLite transaction and
   returns `consistency='atomic_read_snapshot'`. Convenience BridgeSources is cutoff-only and
   explicitly warns; it is not evidence of cross-provider snapshot isolation.
2. **Inventory detail missing in frozen DTO**: production input/output, transfers,
   adjustments and hold subset cannot be reconstructed from received/issued totals.
   Current reports retain those totals, show missing production/hold as unavailable,
   and never infer zeros. Request an additive, versioned public DTO extension with
   separate quantities by warehouse/product, source identity/version and coverage.
   Provide safe display names separately from arbitrary notes/PII. Tests must prove
   production is not counted twice and hold is not added to closing stock.

   Proposed additive `InventorySummaryDTO.breakdown_version: Literal[1] | None`
   and `movement_breakdown: tuple[InventoryMovementSummaryDTO,...] | None`:
   each frozen line has warehouse_id/product_id and exact aggregate kg strings
   `purchased_kg`, `sold_kg`, `production_input_kg`, `production_output_kg`,
   `transfer_in_kg`, `transfer_out_kg`, `adjustment_in_kg`, `adjustment_out_kg`.
   Received = purchased + production_output + transfer_in + adjustment_in;
   issued = sold + production_input + transfer_out + adjustment_out;
   closing = opening + received - issued. All components nonnegative;
   unsupported/missing source meaning => entire breakdown null plus coverage flag,
   never zeros. Require one line per existing warehouse/product scope and matching
   period/cutoff. Do not add QC/approval/hold workflow; report hold remains unavailable
   unless an independently recorded quantity really exists. Keep original fields
   additive-compatible and version the shared contract explicitly.
   Suggested tests: buy 10, production consumes 4/outputs 3 in another product,
   transfer 2 between warehouses, adjustment +/-1; purchases remain 10, not 15;
   each ledger event belongs to exactly one category, transfer net cancels across
   warehouses, and per-scope reconciliation equals ledger closing including backdates.
3. **Accounting semantics**: coordinator has approved an additive typed `meaning`
   field, now applied from that approved SHA. No meaning is inferred from `key`, including
   income/expense/deposit/offset. Null meaning remains local with a warning and
   never enters the shareable summary. Books remain separate; no cross-book/CRM money sum.
   Provider owns PUBLISHED visibility and deduplication of source transaction IDs.
4. **OS secret store — adapter resolved; registry binding pending**: coordinator
   supplied `core.secrets.WindowsCredentialStore` in approved commit `13222da`,
   applied as `84abda4`. One reporting test calls the genuine Windows adapter
   through Admin authorization, rotates fake tokens as one pair, checks redaction
   and cleans only the exact random data-root key. The core's 15 adapter tests pass.
   Reporting exports a minimal injected SecretStore protocol. Default is unavailable,
   so credential writes fail explicitly and sender stays UNCONFIGURED until root
   injects the foundation-owned Windows Credential Manager adapter scoped by data-root UUID/OA,
   durable atomic token-pair replacement and no secrets in DB/receipts/audit/logs.
   Do not bind a plaintext-file adapter. Rotating-refresh timeout requires reauth,
   not blind reuse of a one-time refresh token.
5. **Runtime heartbeat**: manifest supplies startup catch-up and a finite dispatch
   job; reporting UI requests one tick/minute while mounted. For tray/background
   operation, coordinator must bind `service.tick()` to a lifecycle-owned local timer,
   stop it before writer/root shutdown and enforce single-instance. No new runner
   or Codex automation is installed by this lane. Sleep/off/closed app cannot send;
   catch-up queues saved immutable snapshots only, never historical balances made
   from today's data.

Acceptance after coordinator integration: real records/accounting providers,
pending/publish/resume/next-attempt visibility, coherent read capture during edits,
Vietnamese export/Windows runtime, and separately authorized live GMF account test.
Synthetic providers/transport tests do not satisfy those gates.
