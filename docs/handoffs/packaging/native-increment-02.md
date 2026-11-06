# Native maintenance library increment 02

2026-11-07, packaging worktree `cafe-fin-packaging-v1/cafe_fin`, branch
`codex/cafe-fin-packaging-20261107-v1`. Baseline integration tag/SHA remains
`cafe-fin-integration-ready-v1` / `c93ecfd26c0f232fdef9608924fc80615ab0835b`.
Previous lane commits: guards `87e9e116e3e3897a9d4c202bba37f91215196d84`,
renderer contract `d355119c2701ce4365ca9c7c93ea5dc2be07e1e0`.

## Implemented as a library, not yet wired into main.rs

- `maintenance_dto.rs`: exact typed output shapes from native-ui-contract-v1.
  Same-child activation/status returns no BootSession; activation updates ACTIVE
  metadata and clears pending without discarding the fresh target login. New-child
  move/restore returns a DORMANT BootSession and creates a session boundary.
- `native_journal.rs`: bounded strict JSON, immutable op/kind/destination/source
  binding, monotonic verified receipt metadata, same-directory new temp file,
  write-through plus explicit flush, MoveFileExW replacement and exact readback.
  No token or activation-marker writer. Unknown/newer/corrupt journals fail closed.
  `record_closed` requires a matching clean-close proof; ordinary `advance` cannot
  skip that fence. No retirement/abandon API yet and no unknown-partial adoption.
- Move/restore startup resolves journal/config before boot: source DORMANT,
  reconcile-only around OLD_CLOSED, then candidate DORMANT. After config switch,
  pointing at the source is a conflict, including ACTIVE/activation-ACK recovery.
  Backup never switches roots: a validated pending backup binding permits normal
  startup only of the same configured source, with receipt reconciliation later.
  Copying a root UUID does not identify the physical candidate; core fingerprints
  remain opaque. This library does not verify the copied artifact by itself.
- `control.rs`: a single bounded stdout reader for boot and subsequent responses,
  queue bound 1, serial requests, exact request/generation/op correlation, strict
  response schemas, fixed sanitized errors. Lost ACK retains the same pending
  request; new send is refused until it is resolved. No token/path is retained in
  the correlation slot. EOF/timeout/kill cannot prove clean closure.
- `native_paths.rs`: local-drive/reparse/ancestor checks, operation-derived new
  destination names, reports containment revalidation. Fixed ShellExecuteW folder
  action has no renderer path or shell command and initializes COM STA. It is not
  invoked before the future controller authenticates current reporting.read and
  rechecks generation. Library helpers do not themselves grant authorization.

No native command has been wired to call the proposed core filesystem protocol.
Core phase 1 SHA `6294e41706e8d878adddfa76e0c72ff4c74f52d4` supplies admission and
lifecycle only; its status has no artifact/path-fingerprint metadata. Phase 2
controller/protocol SHA is still required before actual prepare/status/cutover.
Unsupported operations must fail UNAVAILABLE, never report mock completion.

## Controller integration details to retain

Private prepare response must provide exact kind before any PREPARED/cutover
action. The kind key is required; the decoder tolerates null in early quiesce/status where an
operation intent may not exist yet; prepared success must match the requested
kind. Coordination should keep this aligned in the phase 2 controller schema.
reports.authorize_open requires no operation/origin/path; its success has matching
request/generation and allowed=true/root_id. No generic open-path command exists.

Journal read/advance checks are library boundaries, not a full transition engine:
the future native controller must persist before quiesce/activation dispatch,
reauthenticate through core, verify returned metadata, observe actual child exit,
switch/read back machine config, and keep held state on every failed boundary.
Do not wire existing eight-second forced shutdown into record_closed. Explicit
recovery/retirement requires a core disposition; absence of it stays pending.

## Validation

Added a small standalone Cargo harness under tests/desktop. Its 11 registry
packages have the same versions/checksums already present in desktop/Cargo.lock;
no product dependency, root lockfile, migration or stack was changed. The harness
builds the actual desktop library, excluding the Tauri build script/GUI so its
state/stdio/filesystem tests can be checked independently. It does not replace
Tauri/native lifecycle or clean-Windows acceptance.

The fixtures cover real native journal files, Unicode paths, immutable operation
replay, corrupt/newer/oversize JSON, close/config fences, no source fallback,
destination identity, reports symlink substitution, plus a synthetic subprocess
pipe peer for late/mismatched/oversize responses and zero/nonzero process exits.
The symlink case requires its actual Windows privilege and fails if unavailable;
it is not silently skipped. All fixture data is synthetic and outside Git.

```powershell
# MSVC developer environment, from worktree root:
cargo check --manifest-path tests/desktop/Cargo.toml --tests --bins --locked --offline
# Permitted standard Windows CI, not attempted on blocked host:
cargo test --manifest-path tests/desktop/Cargo.toml --locked
```

- PASS: rustfmt, Cargo check of library/tests/fixture binary, Git whitespace check.
  Final Cargo check completed without warnings.
- NOT RUN: test executable execution for this increment. Earlier standalone guard
  execution was blocked by host Device Guard; no path/trust-policy workaround or
  new execution attempt was used. Coordinator owns execution on permitted CI.
- NOT RUN: Clippy. The installed Rust toolchain does not include cargo-clippy;
  the attempted command reported the missing component, not a source lint result.
- NOT RUN: actual ShellExecute/native dialog/GUI, actual backend control seam,
  journal power-loss testing, clean client/install/offline/update/uninstall and
  packaged-app benchmarks. No new installer/artifact was created or distributed.

Write-through/flush and replacement/readback are implemented according to the
documented Windows APIs. Hardware power-loss durability remains unproven, including
namespace persistence; these library tests cannot close that release gate. Sources:
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw),
[file caching](https://learn.microsoft.com/en-us/windows/win32/fileio/file-caching),
[GetDriveTypeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew),
[reparse points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations),
[ShellExecuteW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecutew).

No push, merge, release, binary upload, policy change, real credential or outbound
send. Packaging acceptance and licensing/source/relink gates remain open.
