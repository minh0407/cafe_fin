# Records read bridge v3 — product and warehouse names

Shared prerequisite approved by root:
206a7e30ce702d8064084c90296aed3634ef28b7, cherry-picked unchanged as local7575b28.
It contains exactly the four shared core/contract/test/handoff files, no other
root modules. Root already has that source commit and should take only the lane
delta after it. Foundation tag e668355 remains unchanged.

RecordsReadProvider.inventory_summary now fills product_name and warehouse_name
on both InventoryLineDTO and InventoryMovementSummaryDTO. The public provider,
bind_connection and read method signatures are unchanged; HTTP stock-balances
inherits the same v3 fields. CONTRACT_VERSION is3, breakdown_version remains1.
Unknown movement semantics still produce null classification with their existing
flag; display names do not change that behavior, scopes or exact quantities.

After reading effective ledger rows, the provider builds the unique union of
product/warehouse IDs and selects metadata in batches of at most500 IDs. The
query only takes .name from entities whose kind is products or warehouses; it
does not fall back to notes, descriptions, parties, contacts or bank fields.
The metadata query uses the same explicit connection/SQLite snapshot and cutoff
as the ledger. Name revisions are selected as of cutoff, so a later rename does
not leak into a historical cutoff even on a new read connection.

Label queries are separate from numeric aggregation. No join or active/deleted
filter can remove a historical stock scope. Missing entities/revisions remain
ID-keyed scopes with optional names None. Inactive and soft-deleted masters are
still eligible for their actual historical name. Same names never merge IDs.

SQLite JSON_VALID/JSON_TYPE guards avoid treating legacy object/numeric values
as text and tolerate malformed name snapshots. Pydantic TypeAdapter uses the
approved public SummaryDisplayName type: strict string,1..256 Unicode characters,
at least one non-whitespace character. Missing or invalid labels become None;
there is no coercion, truncation or trimming, and the summary does not fail only
because its old display metadata is unusable. Literal markup-like names remain
literal data; the reporting/HTML/XML consumer must escape its output.

The change only creates new read DTOs. It has no persistence/write/file-store
path and does not enrich, reserialize or rewrite saved legacy payloads, hashes or
exported bytes. Root/reporting must retain the original representation of old
snapshots; new captures can use v3 names after producer/consumer adoption. Old
v2 strict decoders do not accept the new fields, even when null.

No schema, migration, dependency, UI source, permission, date/cutoff semantics or
root wiring change. Focused v3 SQLite/WAL tests and updated consumer browser
expectations are handed off in tests.md/ui.md. Reporting/accounting integration
and release/native acceptance remain separate root gates.

Final evidence: focused35 PASS/16.77s (25 new v3 +10 v2), full records156
PASS/70.58s, actual browser/API/WAL consumer1 PASS/20.0s on1421. Ruff/compileall/
diff checks PASS. The v2 numeric helper now excludes only the two optional display
fields before checking its exact eight components; no numeric assertion was
relaxed. No finding from the read-only producer review remains open.
