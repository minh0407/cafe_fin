# Native increment 06a — activation wire correction

2026-11-07, follows 58c2b341. Actual core activate returns only the correlated
operation/runtime state, without prepared artifact fields. Increment 06 incorrectly
required the full candidate binding on that ACK; its synthetic host supplied fields
that the actual producer omits. This would hold an already ACTIVE target.

The controller now accepts the correlated successful ACTIVE admission ACK, then
issues a new freshly authenticated status and requires all saved candidate binding
fields plus actual ACTIVE state before advancing or archiving. The validator is
unchanged. A late activation ACK alone likewise must not advance the journal.
The synthetic activate fixture now emits the actual minimal projection. Regression
cases cover success, changed hash, missing post-ACK receipt and revoked target auth.

Native also compares the bounded core-owned v1 activation marker to the saved
journal before config cutover. This is read-only and preserves opaque fingerprints;
core remains responsible for physical/provenance/hash checks and the only marker
writer. The production adapter uses this same comparison before dormant candidate
construction. A changed marker leaves OLD_CLOSED/config untouched.

PASS: locked/offline desktop and harness cargo check, both cargo fmt checks.
The actual delivered Python private protocol suite passed 28 tests in 30.90 seconds
on Windows 11 Pro build 26200, i5-14400F, 34,138,931,200 bytes installed RAM,
Python 3.12.16, SQLite 3.53.1. This is Python protocol evidence, not execution of
the Rust adapter or installed app. The genuine sidecar was rebuilt successfully
from the current backend owner commits (latest imported e9a9244).

NOT RUN: native Rust executables, cross-language Rust codec test, GUI/clean Windows.
Host Device Guard restriction remains; no execution or output-path workaround.
Coordinator should run the new harness tests on permitted Windows CI. A separate
explicit wire_interop test is being added with the Tauri increment to exercise the
production Python child through Rust, including this minimal ACK shape.

No core, frontend, dependency or migration edits. No push/release/binary upload.
