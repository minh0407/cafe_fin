# Independent QA recovery fixes

- FileStore export idempotency now uses stable storage owner `reporting.export`
  plus `(report UUID, format)`, while the current requesting principal is still
  reauthorized inside FileStore and reporting receipt writer transactions.
  A failure after file storage but before the reporting receipt followed by a
  different Operator retry returns the original file ID; it does not create a
  second core file. Reporting audit retains the human caller. No core-table
  lookup or v1 migration modification was introduced.
- Text-only send commits verified message_id and terminal SENT in one transaction.
  A transient final-write failure retries persistence of the already verified
  in-memory receipt, never transport. SENT cannot be downgraded by an error path.
  Startup also repairs old SENDING/UNKNOWN text-only rows with a durable verified
  message_id; ambiguous network outcomes without a receipt remain UNKNOWN.
- Positive reconciliation revalidates the original captured principal and expected
  delivery version/state inside the final writer transaction. Unresolved responses
  also revalidate before returning. A callback that disables/demotes the Admin
  cannot finalize using that stale authority.

PASS 20 focused tests (4 new fault/revocation cases plus sender regressions),
including before/after-commit fault injection. All network transport is fake.
Existing orphan files created by older builds without a stable storage receipt
are not guessed or deleted by this change. No migration or shared file changed.
