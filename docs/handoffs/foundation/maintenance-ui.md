# Maintenance Settings UI and native bridge

Root-owned implementation in the recovery worktree, following packaging's
`native-ui-contract-v1.md` (`d355119` plus the confirmed same-child/null activation
and lost-ACK safe-attach sections added during integration). No native, backend, feature module,
dependency, migration or installer changes are included in this patch.

## UI/API behavior

- The current BootSession must negotiate `maintenance_protocol: 1` and contain a
  generation before controls can invoke maintenance. Missing additive fields
  preserve the existing startup/login/product behavior and show unavailable
  maintenance controls. Capability is never inferred from app version or a
  previous BootSession.
- `open_reports({userToken})` is available to the current user with
  `reporting.read`, including Operator. Admin with `core.manage` may begin
  backup/move/restore. Core/native remain the authorization boundary.
- Exact command names and camelCase arguments follow the agreed contract.
  Native generates operation IDs and stores picker handles; UI supplies only
  kind, operationId, purpose or the current in-memory userToken as appropriate.
  Destination/source strings are output-only escaped text. There is no path
  input, root UUID/fingerprint argument, or renderer-generated operation key.
- After dispatch, operation ID and native selections remain frozen. Lost replies
  keep the existing operation with explicit status/retry; they never start a
  new operation. A lost picker reply also freezes previously ready selections
  until detailed native status confirms the actual labels.
  Status-proven intermediate phases may explicitly continue the same operation;
  native remains responsible for determining whether continuation is safe.
- A confirmed memory-only SELECTING draft offers **Chọn thao tác khác** with
  explicit alternative kinds. This invokes `maintenance_begin(kind)` and the
  normal native destination picker; native returns a new operation ID and revokes
  the old draft's handles (confirmed contract `8b8e20a`). UI does not clear a local
  view and pretend that native work was cancelled. Replacement is unavailable
  while busy, held, recovery-required, uncertain, or awaiting a Begin/picker ACK,
  and after INTENT. There is no cancellation of persistent work.
  A lost replacement ACK retains the old view as unconfirmed; fresh bounded
  desktop status can identify the replacement ID, then detailed status reconciles
  that ID. Cached/stale old-operation responses cannot resurrect the old draft.
- In-memory session metadata keeps the operation across route and actor changes.
  There is no credential, DTO or journal logging/persistence. Every asynchronous
  begin/select/run/status/activate/open action is fenced by component lifetime,
  store generation and current native boot generation. Native results validate
  operation identity/kind/generation and metadata before changing the store.
- All dispatched transitions, including backup, temporarily gate business pages
  and account management. DORMANT/held states allow login and recovery only;
  health remains available for dormant login. No Restart-as-abort, initialization,
  automatic fallback or abandon action is offered.
- Every non-null returned BootSession calls `setBoot`, even at the same API port:
  source actor/query cache/private drafts are cleared and target login is required.
  Target login does not activate business pages. Only a current target Admin and
  native `can_activate` permit activation. Ordinary same-child activation returns
  a null BootSession; verified current-generation ACTIVE metadata then preserves
  the target login. Unknown/error responses never mean completion.
- Lost target-BootSession or initial-Start ACK has an explicit **Kết nối phiên
  desktop hiện tại** action. It reads bounded desktop status, then invokes the
  existing `start_backend({initialize:false})` safe-attach contract. Native must
  return only its current verified live child while pending; there is no spawn,
  restart, initialization, activation, config fallback or source-token transfer.
  Every attached BootSession is a fresh session boundary. Refused/unknown attach
  remains held; UI does not infer completion from a missing child or status.
  Native's bounded generation/root/journal checks remain the authority across
  races between the earlier status read and the attach call.
- Recovered source transitions in INTENT/QUIESCED/PREPARED/OLD_CLOSED/
  CONFIG_SWITCHED may explicitly continue Run with the same operation even if
  the current source Runtime is DORMANT, provided native does not offer candidate
  activation. UI keeps DORMANT unchanged and delegates fresh verification/close
  to native/core. It does not emulate quiescence or activate the source.
  For ACTIVATION_DISPATCHED, an unknown optimistic dispatch remains uncertain
  with `can_activate=false`. Only a fresh validated native result that explicitly
  returns `can_activate=true` clears that uncertainty for a manual activation
  retry. Partial/replay-required activation with false remains held; status does
  not automatically retry either Run or Activate.
- Known native rejection codes map to fixed safe UI messages. Unrecognized
  rejection bodies/suffixes are not echoed, including paths or tokens.

## Verification and remaining gates

The browser tests use the actual App/session and synthetic HTTP/native responses.
They exercise cancellation, restore readiness, output-only paths, current tokens,
capability fallback, unknown begin/picker/run/activation results, exact-operation
retry, route/actor changes, stale generations/mismatched operation results,
same-port target boundaries, private draft clearing, dormant Operator/Admin gates,
activation metadata and held startup behavior. Existing foundation/session-race
tests are also run.

Verification on 2026-11-07:

- `npm run typecheck`: PASS.
- `npx playwright test tests/maintenance-ui.spec.ts tests/foundation.spec.ts
  tests/session-race.spec.ts --workers=1`: PASS, 25 tests in 34.4 seconds
  (19 maintenance, 4 foundation, 2 session-race).
- After strengthening lost-move-ACK coverage with logout plus unavailable source
  HTTP, `npx playwright test tests/maintenance-ui.spec.ts --grep "lost move ACK"
  --workers=1`: PASS, 1 test in 3.7 seconds.
- `git diff --check`: PASS. Independent read-only review: no remaining blocker.

Draft-switch follow-up, same date: focused maintenance browser suite PASS,
22 tests in 26.3 seconds, including three new cases for cancelled-picker→new native
kind/ID, stale old-operation status, lost replacement ACK→new-ID reconciliation,
and busy/INTENT/recovery gating. No full-suite or native GUI/install rerun.

Recovered-source/activation-ACK follow-up: `npm run typecheck` PASS; focused
`npx playwright test tests/maintenance-ui.spec.ts --workers=1` PASS, 25 tests in
27.9 seconds. Three added cases cover PREPARED/DORMANT source continuation with
the same operation, explicit activation retry after fresh native proof, and a
partial activation remaining held without that proof. Scoped whitespace check
PASS. No backend full-suite, build, native GUI or installer run for this UI patch.

These tests do not exercise actual native dialogs, filesystem copies, the private
sidecar protocol, Windows journal durability, frozen sidecar or installer. Those
remain packaging/core integration and clean-Windows acceptance gates. Native
maintenance commands are agreed interfaces and are not claimed to be wired by
this frontend patch.
