# Native increment 08 — controller review fixes and actual adapter probes

2026-11-07, same worktree/branch; apply after 64346f8e. This increment addresses
both concrete coordinator P2 findings without changing core, domain or interfaces.

`operation_status` no longer returns a full view for OLD_CLOSED from a dead or
missing source child. It requires a current verified live/healthy child, then
continues through fresh core identity/Admin authorization before constructing a
full view. Dead/missing/unqualified child returns MAINTENANCE_RECOVERY_HELD; no
path-bearing view, dead generation, implicit spawn or activation. Only bounded
desktop_status remains available without login. Recovery bootstrap stays a
separate startup action; this change does not add a status recovery shortcut.

The initial selected_root is consumed only after machine config save and explicit
configured-root readback match. Restart requires durable configured_root and
clears any old selection before stopping the current child. A move/restore target
therefore remains the root used by restart, rather than the first-install source.

## Actual production-adapter tests, not codec/fake-host substitutes

The binary's cfg(test) child module loads
tests/desktop/production_controller.rs. Its two opt-in tests instantiate the real
NativeController and JournalStore and require the normal debug resolver to select
the genuine frozen executable in desktop/binaries. They fail if it would resolve
to Python or another path. No product spawn substitution, mock server, Tauri
window/dialog, Explorer action or outbound provider call is used.

The first workflow uses choose_root/start, actual loopback setup/Admin and Operator
login/user creation, begin/select tickets/run/status/activate/restart. It covers
online backup without a session boundary, Operator denial before INTENT, move to
DORMANT with a new generation, source-token denial, fresh target Admin/Operator
authorization, the real minimal activation ACK/full-status completion, and restart
remaining on the moved target with a fresh generation. It then restores the backup
to another new root, checks fresh auth and the default reporting restore suspension,
and restarts again on the restored target. Both old sources and backup are retained.

The second workflow deliberately stops at OLD_CLOSED before config cutover. It
uses real production Host methods/private calls, core copy, CLOSED acknowledgment,
observed child exit 0 and real journal files; only the later config-switch step is
withheld as the fault boundary. Invalid, Operator and old Admin tokens must all
receive HELD while the source is dead, without a new process/view/config change.
The missing-child case is also checked, alongside the bounded prelogin summary.

All HTTP calls have finite timeouts and bounded JSON reads. The fixture uses a
unique absolute synthetic Temp root; cleanup verifies the canonical Temp ancestor,
its own name prefix and local/no-reparse policy before recursive removal. Product
shutdown cleanup is never counted as maintenance closure proof. No real account,
credential, workbook, CRM data or Zalo destination is configured.

## Checks and required CI execution

PASS on the existing Windows development host/toolchain:

- `cargo check --manifest-path desktop/Cargo.toml --tests --bins --locked --offline`
  including both production-adapter tests; no warnings.
- `cargo check --manifest-path tests/desktop/Cargo.toml --tests --bins --locked --offline`.
- `cargo fmt --manifest-path desktop/Cargo.toml --check` and Git whitespace review.

NOT RUN: both production-adapter tests, native harness tests and actual GUI on
this host because of the established Device Guard restriction. No executable run,
trust-policy change or output-path workaround was attempted. The current local
compile input is the genuine sidecar from increment 07; backend source has not
changed in this lane. The earlier 28 Python protocol tests are not rerun or used
as evidence that these controller regressions pass.

On the permitted Windows runner, first build the frozen sidecar from the same
integrated backend source being reviewed. Then execute the binary tests explicitly:

`cargo test --manifest-path desktop/Cargo.toml --bin cafe-fin-desktop --locked -- --ignored --test-threads=1`

The tests are ignored by default: an ordinary cargo test that reports two ignored
tests is NOT a runtime PASS. These probes are headless adapter/core tests, not
installed GUI, clean Windows, offline installer, power-loss or release acceptance.
The separate Rust/Python codec test and ordinary native harness remain useful but
do not replace these actual-adapter checks.

No migration, dependency, DTO, frontend or core change. No new sidecar build,
installer, push, release or upload in this increment. Existing immutable-origin
recovery seam and release/license gates remain unchanged; not production-ready.

## CI follow-up diagnostic

Coordinator subsequently reported 47 ordinary native cases PASS on permitted CI,
but explicit wire_interop failed at boot. The confirmed core Windows-path policy
rejects Rust canonical verbatim disk paths as remote; foundation owns that fix.
The wire test now includes only a bounded uppercase/digit/underscore boot.code in
its failure message, or BOOT_CODE_UNAVAILABLE. It never dumps the boot frame,
message, path or token. No test-only path stripping or product policy change is
made here. Host harness cargo check/fmt remain PASS; native execution here remains
NOT RUN. Await the approved core SHA and a fresh actual CI run.
