# Windows disk paths and local Operator 08

The first actual Rust/Python codec and frozen production-controller execution
identified a Windows interoperability defect: Rust canonical paths use the
`\\?\C:\...` disk spelling, which core classified as remote. Passing that spelling
directly to SQLite URI construction also produced an invalid authority.

Core now normalizes only safe verbatim drive aliases to the same standard drive
representation used by existing roots, receipts and fingerprints. Lexical checks
run before pathlib can erase ambiguous components. Real UNC, extended UNC,
devices, alternate streams, reserved names and ambiguous components remain
rejected. Reparse ancestors are checked before resolution, including broken links.
Backup/restore/move use the validated canonical values for overlap checks. This
adds no migration, marker rewrite, alternate fingerprint or network access.

Evidence before source push:

- 24 new actual Windows cases PASS / 7.16 s; combined existing/new core regression
  91 PASS / 56.21 s. A subsequent reparse-ordering adjustment passed 33 focused
  Windows/storage cases / 8.28 s, including a real junction and proof that resolve
  is never called before rejection. The earlier total is not a rerun claim.
- Independent probes passed all seven groups: historical `3fe66d6` normal-path
  markers/receipts activate through a verbatim alias without changing marker bytes;
  the retained old source remains dormant; mixed-alias backup/restore and overlap,
  four cloud alias combinations, junctions, lexical refusals and actual 348-character
  Runtime/SQLite/FileStore/backup all pass. Final ordering was checked independently.
- Paths longer than 260 characters were exercised on this host with existing
  LongPathsEnabled=1. No system policy changed; other client configurations remain
  acceptance work. Rust native execution remains on permitted Windows CI.

The local Operator also gains exactly `accounting.configure` and
`accounting.restore`. One person can create/configure independent books and recover
deleted rows without an Admin approval step. Accounts, contract templates, sender
settings and native data-root operations still require Admin. Actual default-
registry API/SQLite tests verify versions, idempotency, actor audit, revocation,
unchanged records tables and retained Admin boundaries: 7 PASS / 5.07 s in the
coordinator rerun. The earlier Admin-only assertion was updated explicitly;
typed validation and stale-version rejection remain. See the role matrix,
daily workflow and synthetic report example in [USER_GUIDE](../USER_GUIDE.md).

Windows run [42311533753](https://github.com/minh0407/cafe_fin/actions/runs/42311533753)
at `3fe66d6` is retained as a **failed** run: backend 1,125 PASS / 863.98 s, main UI
57 PASS, all six feature configurations PASS, frozen smoke 1 PASS / 17.42 s and
47 ordinary native tests PASS. Explicit codec boot and both actual frozen
production-controller cases failed with the disk-alias defect above. Installer
build was not reached. These results are not relabelled as acceptance of the fix;
the new source must pass those explicit native tests and candidate build again.
