# Core operations alignment increment 04

2026-11-07, same packaging branch/worktree. Approved core phase 2
`b998a25948635094dd26450432813a5f2a0fa24d` was cherry-picked as `6e07871`
after the approved phase 1 import. Exactly its nine files were imported; packaging
did not edit core, its tests, reporting or frontend. Integration tag remains c93.

Read `docs/handoffs/foundation/maintenance-operations.md` and the actual controller.
No framing/stdio SHA or reporting restore hook has been imported yet. Phase 2
results do not by themselves establish the final wire envelope.

## Native changes

- Separate OperationState from RuntimeState. PREPARED/REPLAY_REQUIRED describe an
  operation receipt/artifact; actual runtime may remain QUIESCED or DORMANT.
  REPLAY_REQUIRED and CLOSE_AUTHORIZED were NOT added to RuntimeState.
- Decoder now requires separate `state` and `runtime_state`. A successful close
  must have operation CLOSED and actual runtime CLOSED; quiesce/activation also
  require matching actual runtime states. CLOSE_AUTHORIZED plus child exit 0
  cannot become a close ACK. Prepared result does not invent Runtime PREPARED.
- Optional origin_generation, activation_id, activation_completed and marker
  format are bounded/validated, including original-generation and operation ID
  matching. Activation replay cannot claim completion and REPLAY_REQUIRED together.
  A status operation may report FAILED_HELD with a fixed code while actual Runtime
  remains QUIESCED. This is never interpreted as successful preparation/activation.
- Align native journal with approved controller policy: backup destination, like
  move/restore, must be independent of the active root. A nested destination is
  rejected before journal intent/quiescence; no relaxed backup-only exception.

The expected wire representation needs to be compared with the approved framing
SHA before real commands are connected. No raw core method result is guessed to
be a completed process-close response. Core authorize_close is authorization only;
the dispatcher still owns Runtime/HTTP/server/listener teardown and native still
requires correlated CLOSED plus observed exit 0.

Restore prepare/activation remain RESTORE_GUARD_UNAVAILABLE until the reporting
owner's public activation hook is supplied/reviewed. No native/private reporting
SQL, credential reuse or synthetic sender success is introduced. Same-version
move support cannot be used to claim cross-version migration-aware restore.

## Remaining pre-quiesce identity seam

Native journal INTENT currently pins source_root_id and the core-produced opaque
source_fingerprint before requesting quiesce. Core phase 2 `status(new_operation)`
authenticates, then returns MAINTENANCE_OPERATION_NOT_FOUND because prepare has not
yet persisted its intent. The approved public methods do not yet provide a
pre-intent source identity result, and the original boot shape did not carry it.

Do NOT call private `_source()` from this lane, compute a native path hash, loosen
journal identity requirements, write a core intent outside its owner, or quiesce
before the journal has enough verified identity.

Suggested minimal seam for coordination/protocol owner: add private negotiated
boot fields `root_id` and `root_fingerprint` for the actual opened Runtime, or an
authenticated public core source-identity/preflight result usable by the adapter
before quiesce. Native retains these in private verified-child state and copies
them into journal; BootSession/DesktopStatus renderer DTOs do not expose them.
No new UI arguments or generic raw-path HTTP API are needed. Field names/exact
wire shape must be supplied with the approved framing commit before use.

Until that seam and the actual framing SHA arrive, new maintenance operations
cannot be dispatched safely from native. Keep them unavailable/held; legacy boot
does not advertise maintenance capability. Safe attach remains available only
for an already verified child, not a hidden dormant bootstrap/fallback.

## Evidence

PASS: Cargo check library/test harness/fixture binary with locked existing pins,
without warnings; rustfmt; Git whitespace check. Three added source-level cases
cover separate operation/runtime states, false close authorization/undrained
runtime despite process exit 0, and invalid runtime/activation wire binding.
The fixture peer is synthetic, not the real stdio adapter.

NOT RUN: executable tests on Device-Guard-blocked host; actual approved stdio
subprocess flow; full Tauri app check/build after the prior missing genuine-sidecar
prerequisite; GUI/clean-client/offline/update/uninstall and packaged benchmarks.
Core test PASS counts belong to coordinator evidence and were not rerun or
promoted to packaging acceptance by this lane. No new installer/distribution.

Coordinator CI can run `cargo test --manifest-path tests/desktop/Cargo.toml --locked`
after review, then build the real matching sidecar before full Tauri check/build.
No push, release/upload, policy change, new dependency, live credential or send.
