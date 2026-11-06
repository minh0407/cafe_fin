# Accounting integration request

Baseline: cafe-fin-foundation-ready-v1 / e668355c227322994902f7e2e38ed7ffb19ff647.
Lane commits only modify owned files; the explicitly approved root commits below
were cherry-picked unchanged. No dependency or lockfile changes are requested.

Resolved shared changes (do not apply them again):

- Root57a2ed26 (local cherry0da9c87): read bridge v2 and explicit metric meanings.
- Root22ca5431 (local cherry59d94da): generic file/job owner/Admin scope and public
  `FileStore.require_owner_or_admin`. Accounting source ingress uses that helper
  after fresh auth on the same writer connection, including receipt replays.
- Root48858654 (local cherry1be5a0f): structured ApiError.details for cell issues
  and FILE_ALREADY_UPLOADED batch IDs, retaining session-generation fencing.

Coordinator-owned wiring:

```diff
--- backend/cafe_fin/registry.py
+++ backend/cafe_fin/registry.py
+from cafe_fin.accounting.module import module_manifest as accounting_manifest
 # add accounting_manifest() to the existing ModuleRegistry tuple, preserving others
```

```diff
--- frontend/src/app/registry.tsx
+++ frontend/src/app/registry.tsx
+import { accountingFeature } from '../features/accounting';
 # replace only the accounting Pending module entry with accountingFeature
```

Accounting exports its ModuleManifest via `accounting.module.module_manifest()`:
namespace migrations `accounting:1..2`, four resumable jobs `accounting.parse`,
`accounting.validate`, `accounting.commit`, `accounting.export`, on_startup outbox
dispatch, and router under `/api/v1/accounting`.

Permissions follow frozen core roles: `accounting.read/write` for book data,
imports and derived exports. `accounting.configure` for creating/changing schema
and `accounting.restore` for restoring saved rows require Admin (`*`) on baseline.
No implicit elevation of Operator jobs. Further per-action Operator permissions
would need an explicit core role-policy change, not a module bypass.

Read bridge: `AccountingReadProvider(runtime, principal).book_summary` implements
the frozen core DTO/Protocol; reporting must freeze the returned DTO/file and
retain revisions for historical output. It must not import accounting SQL tables.
`through_on` includes the final day (same-day periods are valid); business dates are Asia/Ho_Chi_Minh. UTC timestamp windows stay half-open. The provider
rejects old cutoffs rather than label a live query historical.

For consistent cross-module capture import the provider from
`cafe_fin.accounting.public`. Its optional `connection=conn` parameter binds every
query and permission check to a read-only SQLAlchemy Connection supplied by the
caller. Reporting owns `with runtime.reader() as conn: conn.exec_driver_sql('BEGIN')`,
the first read that pins SQLite's snapshot, cutoff, all source providers, and
transaction closure. Accounting does not open/close/commit a bound connection.
This mode accepts the capture cutoff for that pinned transaction. DTO v2 preserves
base fields and adds explicit meanings; v1 decoders with extra=forbid must be
updated alongside producers. Monetary rows use the common published predicate.

Integration validation: run `.venv/Scripts/python -m pytest tests/accounting
tests/core -q`, frontend typecheck/build, then wire and run the lane real-backend
UI harness. Native Windows clean-client/installer acceptance remains release gate.

## Resolved scope findings and remaining wiring

The original foundation exposed other actors' file/job reads. Approved22ca5431
fixes those routes and fail-closes missing/ambiguous provenance even for Admin.
The accounting input-reference bypass is separately fixed; generic GET fixes
alone would not close it. Scope tests now assert403 directly: no conditional
XFAIL remains. No monkeypatch or replacement shared route is included.

The baseline pytest `testpaths` includes only `tests/core`. Coordinator should
expand it to `tests` (or explicitly list every integrated lane in CI); otherwise
an unqualified pytest run omits the accounting crash/import/API regressions.
This is a shared root tool-config change, not an added dependency.

The refreshed `shared-integration.patch` contains only backend/frontend registry
wiring and pytest discovery. `git apply --check` passes in this lane's checkout;
merge those additive entries with other lane manifests rather than replace them.
