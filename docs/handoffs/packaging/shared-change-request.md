# Maintenance seam ACK and questions for coordination

Date: 2026-11-07 (Asia/Bangkok). Packaging source baseline:
`cafe-fin-integration-ready-v1` -> `c93ecfd26c0f232fdef9608924fc80615ab0835b`.
Foundation -> `e668355c227322994902f7e2e38ed7ffb19ff647`.

Read the coordinator's ignored `maintenance-seam-plan.md`, based on source
`548029875f702161b83b5e6137fd98da244062fb`. The proposal is not implemented
core behavior and this ACK does not freeze an API or authorize active switching.

## Agreed boundaries

- Native-selected paths stay in inherited private stdin/stdout. Renderer receives
  opaque memory handles bound to purpose, operation and child generation. Handle
  possession grants no core permission; current target/source Admin authorization
  must be checked by core at actual execution, including receipt replay.
- One bounded stdout reader routes boot and correlated responses. Strict frame
  schema, sanitized codes, no payload logging. Request bound includes newline:
  262144 bytes; response bound 16384 bytes. Never read an unlimited line then test
  its size. Native paths must be valid UTF-8 and fit Windows UTF-16 limits.
- Ordinary backup stays online. Move/restore persist native journal INTENT before
  quiescence; close HTTP admission, drain in-flight requests and stop both producers
  before cutoff. Do not hold writer barrier while waiting for those producers.
- Prepared move/restore stays held. A correlated CLOSED success and actual exit 0
  are BOTH necessary before config switching. Timeout/kill/EOF alone is unclean.
- Candidate is dormant/auth-only before explicit activation, with no module hooks,
  recovery, timers, jobs or sender. No automatic old-root fallback after candidate
  effects/activation dispatch. Retain source root.
- Activation of a restored root needs the reporting owner's persisted public
  quarantine/reconciliation hook before any startup/sender. Copied root UUID and
  current Windows credentials do not prove a delivery is safe to replay.

## Exact shapes to confirm before dependent implementation

1. Freeze tagged request/response schemas per command: `maintenance.quiesce`,
   `maintenance.prepare`, `maintenance.status`, `maintenance.close`,
   `maintenance.activate`. Define required/forbidden fields, optional result fields,
   sanitized error codes and CLOSED response order versus server/thread teardown.
   Keep `origin_generation` and immutable op/destination constant on retry while
   `generation` and `request_id` identify the current transport request.
2. OpenReports needs a current core.manage check without exposing a raw path API.
   Proposed private command `reports.authorize_open` with generation/request/op and
   current access_token; return authorization result bound to this runtime/root.
   Rust opens only its verified current root/reports with a fixed OS operation.
   Please confirm command name/response and whether core.manage is the policy.
   Native does not infer authorization from the renderer's role or picker handle.
3. Freeze the activation context/marker fields and ownership. Packaging can persist
   `.cafe-fin-activation.json` on the verified TARGET before activation dispatch;
   core must validate context against actual target and invoke public module hook
   before Runtime.start. Use stable activation_id distinct from copied root UUID;
   no credentials in marker/journal/receipts. Confirm physical-path fingerprint and
   manifest digest canonicalization shared with core; do not hash platform path
   spellings independently in the two implementations.
4. Confirm recovery bootstrap for each held phase and explicit cancellation before
   candidate effects. A missing close ACK after process disappearance cannot be
   converted to CLOSED from a PID check; define the core reconciliation proof.
   An orphan/unknown candidate is held for recovery, not silently adopted.
5. Native destination dialogs select folders. Backup/move/restore publication
   currently expects a NEW destination path. Confirm that native derives a fixed
   child name from operation_id beneath the selected parent (rather than passing
   an existing folder to create/restore), and show the final destination before
   confirmation. The destination cannot change after dispatch or lost ACK.

## First independent native increment

`desktop/src/native_guards.rs` supplies bounded frame reading, bounded opaque-handle
bindings, clean-close evidence and conservative transition/recovery guards. It has
no dependency additions, IPC invocation, config writes or data operations. It is
not yet wired into main.rs: core/renderer protocol remains subject to confirmation.
The transition guard does not itself persist a journal or prove power-loss
durability. Its recovery policy never grants active boot automatically.

Compile the production source through `tests/desktop/native_guards.rs`. This test
harness uses std only and creates no substitute Tauri/GUI acceptance result.

```powershell
# From the packaging worktree, with MSVC developer environment loaded:
rustc --edition=2021 --test tests/desktop/native_guards.rs -o desktop/target/native-guards-tests.exe
desktop/target/native-guards-tests.exe
```

Local evidence on 2026-11-07: rustfmt and native test compilation PASS; test
execution BLOCKED by Device Guard. CodeIntegrity events 3033/3077 were observed
after the single execution attempt. No policy change, path workaround or second
execution attempt. The updated final test source was compiled, not executed.
Coordinator can run this harness on its permitted standard Windows CI environment.
No test case is reported PASS until actual execution succeeds.

## Release gates still open

No new installer produced or installed by this lane yet. Native GUI, Windows
clean/offline, update/uninstall, physical storage failure/power loss, real app
50k/500k/1m benchmark and DOCX open/print remain NOT RUN. Exact lxml/iconv native
source/relink and distribution evidence remain unresolved; the no-iconv proposal
is an ignored draft, not an approved dependency change. No binary upload/release.
