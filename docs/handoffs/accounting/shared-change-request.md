# Accounting integration request

Baseline: cafe-fin-foundation-ready-v1 / e668355c227322994902f7e2e38ed7ffb19ff647.
Only module-owned files change. No new dependency or lockfile changes requested.

The shared `ApiError` currently drops `error.details`. Cell error issues and
`FILE_ALREADY_UPLOADED` batch ID live in that field. Add an optional `public
details: Record<string, unknown> = {}` constructor parameter after `fields`,
and pass `envelope?.error?.details ?? {}` at the non-OK construction site.
The lane UI consumes it structurally; core fields/request ID behavior stays
unchanged. Test error envelope details and session fencing together.

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
namespace migration `accounting:1`, four resumable jobs `accounting.parse`,
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
This mode accepts the capture cutoff for that pinned transaction. Frozen DTO v1
is unchanged; monetary rows still apply the shared published visibility predicate.

Integration validation: run `.venv/Scripts/python -m pytest tests/accounting
tests/core -q`, frontend typecheck/build, then wire and run the lane real-backend
UI harness. Native Windows clean-client/installer acceptance remains release gate.

## Core actor scope findings (integration gate)

On frozen foundation, another Operator can read an Admin accounting job through
generic `GET /api/v1/jobs/{id}` despite accounting batch routes returning 403.
Generic file metadata/content similarly permits reading another actor's original.
Tests in `tests/accounting/test_public_api.py` conditionally XFAIL only while
these endpoints return 200; after the coordinator patch they assert 403 and PASS.

Requested shared policy/patch: in core.api `job_status`, after existing module/read
permission checks require `job.actor == principal.id or principal.role == 'admin'`
for non-foundation module jobs. In `file_metadata` and `file_content`, before
return/open, resolve the file creation actor (core_file CREATE audit, same file ID)
and require owner/Admin or an explicit module-granted shared-file scope. Do not
infer authority from a UUID or an unrelated `files.read` permission. Keep export
and reporting service reads usable via explicit trusted read bridges. Add core
regressions for actor changes, revoked roles, missing owner/audit (deny), original
download, and exact hash; rerun the accounting scope regressions after wiring.

No module monkeypatch or replacement shared route is included.

The baseline pytest `testpaths` includes only `tests/core`. Coordinator should
expand it to `tests` (or explicitly list every integrated lane in CI); otherwise
an unqualified pytest run omits the accounting crash/import/API regressions.
This is a shared root tool-config change, not an added dependency.

Before accepting the lane, apply/review the patch and rerun the three conditional
scope regressions until they PASS (not XFAIL). A lane code/benchmark commit is not
permission to leave shared actor scope unresolved in the integrated application.
