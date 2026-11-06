# Actor-scoped source capture

`module_manifest(actor_source_factory=lambda runtime, principal: ReportSource(...))`
is an alternative to `source=` and `source_factory(runtime)=`. Supplying more
than one mode raises ValueError. Existing fixture modes are unchanged.

ReportingService retains the factory, never a principal or actor-bound source.
Each non-replayed preview revalidates its caller before constructing the source,
passes the current request principal into the factory, and revalidates that same
principal in the writer transaction that persists the snapshot. A revoked or
role/version-changed caller cannot persist capture results. Idempotent preview
replay returns its frozen original without another capture/factory invocation.

Root can bind AtomicSources callbacks to public connection-bound
RecordsReadProvider/AccountingReadProvider with that principal, preserving one
read-only SQLite transaction. Do not bind a global Admin or reuse an actor-bound
provider from the first request. Background generation will resolve its own
currently active configured actor through foundation's trusted actor resolver;
this factory creates no session and grants no permission itself.

PASS: 3 focused tests (fresh admin/operator captures, replay, revocation before
factory/during capture, mutually exclusive source modes). No shared files,
migration, dependency, registry, push, merge or live Zalo call changed.
