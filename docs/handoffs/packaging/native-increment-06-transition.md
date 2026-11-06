# Native increment 06 — serial transition library

2026-11-07. Same packaging worktree and branch as increment 05. Owner commits
123ed671 (source identity) and 59bbeb27 (bounded wire), plus reporting hooks
18951a63/1783f01e, are imported explicitly; no core/domain changes in this increment.

The private decoder now matches the delivered wire projection: independent
operation/runtime states, omitted optional fields rather than null, 128-character
token limit, strict correlation and hash validation, and source_identity without
operation/path fields. Native source fingerprints remain opaque core values and
are mandatory before durable INTENT. No marker/path hash substitution.

native_transition supplies serial Run/Activate/Status completion over a narrow
host adapter. It persists INTENT before quiesce, validates full prepared bindings,
requires correlated CLOSED plus observed exit 0 before OLD_CLOSED/config switch,
readbacks machine config before candidate construction, and constructs the target
DORMANT. Run never activates. Explicit activation verifies fresh target authority
and exact receipt fields; REPLAY_REQUIRED stays held. Completion archives the
private journal before removing the pending record; source data is retained.
The machine config stays version 1 with its existing data_root field.

PASS: `cargo check --manifest-path tests/desktop/Cargo.toml --tests --bins --locked --offline`
on this Windows development host with the existing MSVC/SDK helper; rustfmt and
Git whitespace validation. The harness uses only the existing serde/serde_json
pins and adds no product dependency. Seven synthetic-host transition cases compile:
ordering/explicit target activation, missing ACK/nonzero exit, constructor failure
without source fallback, source-token rejection/partial activation fencing,
prepared source DORMANT recovery, conflicting activation receipt, and lost-ACK
completion via fresh ACTIVE status. They use real native journal/config files.

NOT RUN: native test executables on this host (Device Guard previously blocked
execution; no policy/output-path workaround), actual Tauri dispatch, installed
GUI or clean/offline Windows acceptance. Coordinator may run the harness on the
permitted Windows CI. Synthetic host tests do not prove core copy or full crash
recovery. Matching Python wire interoperability and actual transition test runs
remain required before runtime acceptance. Tauri adapter/handlers follow in the
next increment; this library alone is not a working maintenance UI.

Known core boundary: if the source process dies after native INTENT but before
core prepare-intent commits, a new source DORMANT generation cannot prepare using
the old immutable origin_generation. Keep HELD with MAINTENANCE_GENERATION_CONFLICT;
do not rewrite origin, discard intent, or boot the source ACTIVE as a workaround.
Core-owned public recovery proof is needed to recover that boundary.

No migration, push, release, binary upload, credential, real data or outbound send.
No claim of production readiness. The four existing generated permission files
and generated sidecar inventory are excluded from this library increment.
