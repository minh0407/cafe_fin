# Memory-only draft replacement increment 05

2026-11-07, same packaging branch/worktree, after `a211334...`. This increment
implements the confirmed small draft UX safety boundary; it does not add an
abandon API for journaled or uncertain operations.

## Native library

`native_draft.rs` supplies a single DraftSlot for the future native maintenance
handlers. Begin reads the real JournalStore and refuses any persistent journal
or journal read/validation error. Native latches prevent replacing an uncertain
draft, attempted intent write, dispatched operation or in-flight dialog. No
renderer-provided phase/busy/uncertain boolean grants replacement permission.
Known SELECTING may be replaced with a new native ID/kind; all old op handles
are revoked, without a data-root/config write or backend action.

Dialog selection uses a private operation/generation/sequence/purpose ticket.
State and journal are rechecked at completion; old/duplicate callbacks cannot
clear a newer dialog or mutate a replacement draft. Cancellation keeps a prior
selection. A persistent/invalid journal cannot be presented as disposable known
SELECTING by the draft view. Status must use the real journal path when present.

PickerHandles.replace_purpose validates nonce/path before revoking the prior
operation-purpose binding. Valid reselect rotates the handle, preserves other
purposes and reuses the slot. Failed validation preserves the previous binding.
Begin replacement revokes all purposes of the old draft. Source/destination paths
remain native-selected; output display text is never accepted back as authority.

Draft view can still say SELECTING with recovery_required=true for a native
uncertain/intent-attempt/dispatched latch whose persistent outcome needs proof.
That is NOT discardable. No reset/abandon method is added for those latches.
Renderer ACK uncertainty is also a UI reconciliation requirement: the UI must
obtain fresh native state before another Begin, not discard from cached SELECTING.

This component is not yet exposed by Tauri maintenance commands; the framing
SHA and pre-quiesce core identity seam from increment 04 are still required.
Do not infer that working picker/backup/move/restore UI exists from this library.

## Checks

PASS: Cargo check of library/tests/fixture binary under the locked existing
dependency pins; final check without warnings; rustfmt and Git whitespace check.
An initial test type-inference compile error was corrected with an explicit
Option<String>; the final source was checked again.

Added cases cover cancelled draft replacement, busy refusal, both restore-purpose
handles revoked on replacement, stale dialog callbacks, 100 repeated folder
reselects preserving source, invalid reselect preserving last destination, and
persistent/corrupt/uncertain/intent-attempt/dispatched refusal. The standalone
guard test also checks 100 rotations without exhausting the eight-handle bound.

NOT RUN: executable tests on the host previously blocked by Device Guard. No new
execution attempt, trust-policy change or output-path workaround. Coordinator
can execute `cargo test --manifest-path tests/desktop/Cargo.toml --locked` on its
permitted Windows CI. These are synthetic native library fixtures, not installed
GUI/clean-Windows acceptance. Full Tauri remains subject to genuine matching
sidecar build input and framing integration. No new installer/artifact.

No core/frontend/dependency/migration changes, push, release/upload, live data,
credential or outbound send. Persistent cancel/recovery remains a separate core
proof workflow; memory-only replacement is neither recovery nor source fallback.
