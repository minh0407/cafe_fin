# Lost-ACK safe attach increment 03

2026-11-07, same packaging branch/worktree. Parent includes native library
`a3a147c072e896761bc7eaa94b92fa5cc95701f6` and approved core phase 1 cherry-pick
`4afa1b76f0d4382b3e205214ca8ff8e1f0147cd3` (original `6294e417...`). No phase 2
filesystem/controller/stdio SHA has been imported, and no restore activation hook
or candidate bootstrap is inferred from phase 1.

## Confirmed and implemented source behavior

Existing `start_backend({initialize:false})` may safely attach to the current
already verified child after lost Run ACK or lost first-start ACK. It returns its
app-session BootSession; no source user token is accepted/transferred. UI clears
the previous actor/cache for any returned BootSession, even if port is unchanged.
The safe-attach guard has no spawn/stop/initialize/activate/config-write interface.

The real main.rs now calls this guard while holding its native state mutex:

- Load/validate native journal before deciding any normal start branch. A corrupt
  journal is HELD, never equivalent to absence. For pending transitions, reconcile
  config and actual current child's physical root against journal, check liveness,
  app-session health and generation, then recheck journal/root binding before
  returning. The current summary replaces cached pre-Run pending metadata.
- A pending transition with no existing child, dead/unverified child, failed
  health, missing capability, generation mismatch or initialize=true returns
  MAINTENANCE_RECOVERY_HELD. Never spawn the selected/configured source as fallback.
  A dead existing child also does not implicitly respawn on a plain Start call.
- Restart is forbidden while pending, as is choosing/reselecting a root. Dialog
  completion checks state again to refuse a result that raced another command.
  Normal explicit Restart without a journal retains the legacy behavior; its
  forced-stop fallback is never maintenance close/config-switch evidence.
- The stdio reader is now the library's single bounded ControlPipe reader;
  stdout after handshake is retained for correlated processing, not drained to a
  sink. Legacy fixed shutdown is allowed only outside a pending control request
  and grants no CLOSED proof. The close/config journal fence is unchanged.
- Blocking file/process/health operations run on Tauri's existing blocking pool,
  not directly inside the async command executor. No custom worker/job runner was
  added. State is Arc<Mutex<DesktopState>> so the blocking closure owns its handle.
  Pinned reqwest blocking wait code explicitly checks runtime entry in debug;
  native HTTP calls should not be run directly on the async executor.

Current boot is intentionally still legacy v1: maintenance capability/generation
are null until phase 2 is explicitly negotiated. A private native generation
tracks the legacy child for attach races; it is not advertised as negotiation.
An unsolicited maintenance handshake is rejected. Thus a legacy current child
can recover a first-start ACK with no journal, but cannot pretend to be a verified
maintenance candidate. Pending recovery with no qualified child remains HELD.

Phase 2 still needs approved dormant bootstrap/prepare/activate and actual native
maintenance commands/pickers. Safe attach is not that bootstrap, a token getter,
an abandon operation or permission to open an archived backup as an active root.
Core remains sole activation-marker writer. First-install restore is not added.

Private reports response now accepts the coordinator's optional opaque
source_fingerprint alongside allowed/root_id. It is not a renderer field or path.

## Checks and limits

- PASS: `cargo check --manifest-path tests/desktop/Cargo.toml --tests --bins
  --locked --offline`, without warnings. Harness contains 10 guard and 19
  maintenance cases, including four attach cases for current-target lost ACK,
  initialize/no-child/unverified refusal, generation/stale-session/health/death
  races and legacy first-start retry. These are source/guard tests, not native GUI.
- PASS: rustfmt and Git whitespace checks.
- NOT RUN: test execution. Host Device Guard previously blocked native test
  executables; this increment did not retry execution or change paths/policy.
- Full product `cargo check --manifest-path desktop/Cargo.toml --locked --offline`
  attempted once. It stopped in the Tauri build script: the worktree lacks genuine
  `desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`. Dependency compile
  reached the app build script, but main.rs typecheck is NOT proven by this run.
  No placeholder, foreign-source binary copy, config override or retry was used.
  Coordination CI must build sidecar from the intended source, then check/build
  the full Tauri binary and execute the standalone harness.
- NOT RUN: actual installed/native lost-ACK attach, dialogs, process lifecycle,
  clean Windows/offline/update/uninstall, physical power loss and packaged app
  benchmarks. No installer or distributed artifact was produced by this increment.

No frontend/core edits, migration, dependency change, push, release, binary upload,
policy change, real credential or outbound send.
