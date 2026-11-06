# Native renderer contract v1

Confirmed with coordination on 2026-11-07. Source baseline remains integration
`c93ecfd26c0f232fdef9608924fc80615ab0835b`; maintenance core implementation/SHA
has not yet been delivered to packaging. These commands are the agreed target
interface, not a claim that the current main.rs exposes working maintenance.

## Exact command names and invocation arguments

Tauri invocation arguments use camelCase; returned JSON fields use snake_case.
No command accepts a filesystem path, root UUID, fingerprint, role or actor ID.
`userToken` is the current login token, held only in memory and the private pipe.
It is not an authority by itself: core reauthenticates and checks permission.

| Command | invoke arguments | Result |
| --- | --- | --- |
| `maintenance_begin` | `{kind: "backup" | "move" | "restore"}` | `MaintenanceView` |
| `maintenance_select` | `{operationId: string, purpose: "destination" | "backup_source"}` | `MaintenanceView | null` (dialog cancelled) |
| `maintenance_run` | `{operationId: string, userToken: string}` | `MaintenanceResult` |
| `maintenance_status` | `{operationId: string, userToken: string}` | `MaintenanceResult` |
| `maintenance_activate` | `{operationId: string, userToken: string}` | `MaintenanceResult` |
| `open_reports` | `{userToken: string}` | `null` |

`operation_id` is native-generated and opaque. Picker handles are stored within
native state for that operation, purpose and generation; the renderer cannot
substitute them or provide a raw path. Before INTENT, selecting again replaces
that purpose's memory binding. After INTENT/dispatch, kind/op/destination/source
are immutable. Repeated Run/status after a lost ACK keeps the same operation.
Begin must not replace an unfinished persistent operation.

```typescript
type MaintenanceKind = "backup" | "move" | "restore";
type RuntimeState = "ACTIVE" | "QUIESCING" | "QUIESCED" | "PREPARING"
  | "PREPARED" | "CLOSING" | "CLOSED" | "DORMANT" | "ACTIVATING" | "FAILED_HELD";
type MaintenancePhase = "SELECTING" | "INTENT" | "QUIESCED" | "PREPARED"
  | "OLD_CLOSED" | "CONFIG_SWITCHED" | "CANDIDATE_DORMANT"
  | "ACTIVATION_DISPATCHED" | "ACTIVE";
interface PendingTransition {
  operation_id: string;
  kind: MaintenanceKind;
  phase: MaintenancePhase;
  recovery_required: boolean;
}
interface MaintenanceView extends PendingTransition {
  generation: string;
  runtime_state: RuntimeState | null;
  destination_display: string | null;
  backup_source_display: string | null;
  ready: boolean;
  can_activate: boolean;
}
interface MaintenanceResult {
  operation: MaintenanceView;
  boot_session: BootSession | null;
}
// Additive fields to existing BootSession and DesktopStatus:
// maintenance_protocol: 1 | null
// generation: string | null
// runtime_state: RuntimeState | null
// pending_transition: PendingTransition | null
```

`destination_display` and `backup_source_display` are output-only text to show
the selection/final destination before Run; do not parse or submit them back.
Do not log the DTO, login tokens or journal. PendingTransition contains no paths,
credentials, raw receipt, fingerprints or manifest. Before login, use the bounded
desktop_status summary; maintenance_status requires a current authorized login.
Capability is 1 only after negotiation with the current child, otherwise null;
UI must not infer support from version 0.1.0 or stale cached BootSession.

Backup returns no new BootSession. A successful move/restore run returns a NEW
target BootSession in DORMANT, and UI must clear source actor/cache/drafts then
require target login. Candidate activation requires that fresh target login.
Any recovered source Runtime also gets a new generation/session and starts
dormant while its transition is reconciled. A new returned BootSession must be
treated as a session boundary even if api_base happens to use the same port.
Successful `maintenance_activate` on the SAME child/generation returns
`boot_session: null`, operation.runtime_state=ACTIVE, can_activate=false and
recovery_required=false. UI updates that generation's bounded boot metadata to
ACTIVE/pending_transition=null and retains target login. Do not call setBoot as a
new boundary merely for this same-child activation. Same-child status also returns
boot_session=null. A genuinely NEW child always supplies a new BootSession.
`ready` is selection readiness, never proof of permission/prepared copy.
`can_activate` is false unless native has verified target binding and the current
child's DORMANT response. UI role checks cannot turn it true.

No explicit abandon command is exposed in this increment: recovery remains held
where core has not supplied a safe disposition. Do not wire Restart as cancellation
or silently reselect/reinitialize the old root. First-install restore/bootstrap
will be coordinated separately; it cannot boot a backup directory as active.

## Confirmed implementation split

- Core alone writes `.cafe-fin-activation.json` after verification and before
  PREPARED. Native persists journal/receipt hashes and keeps source/candidate
  fingerprints opaque. It must not become a second activation-marker writer.
- Marker v1: activation_id=operation_id, kind move|restore, origin_generation,
  source_root_id, candidate_root_id, source_fingerprint, candidate_fingerprint,
  manifest_sha256. Core validates it before public activation hooks/Runtime.start.
- Private `reports.authorize_open` has request_id, generation, access_token and
  maintenance_protocol, no operation_id/path. Success returns allowed=true,
  root_id and matching generation/request ID. Permission is current
  **reporting.read**, for an Admin or Operator who has it. Native rechecks current
  generation, containment and reparse points, then opens only currentRoot/reports.
- Native picker selects an existing local parent. Final child is exactly
  `CafeFinBackup-<operation_id>` for backup, `CafeFinData-<operation_id>` for
  move/restore. The backup-source picker selects an existing backup folder.
- CLOSED plus exit 0 remains mandatory. Unknown exit/lost ACK stays held; only
  core status/recovery proof can permit an explicit new close attempt. Dormant
  construction may migrate DB, so candidate boot is not assumed side-effect free.

Windows journal replacement will use bounded JSON, no-follow/reparse checks,
write-through file + explicit flush, same-directory replacement and readback.
This does not by itself prove hardware power-loss durability. Windows API sources:
[file caching](https://learn.microsoft.com/en-us/windows/win32/fileio/file-caching),
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw),
[reparse checks](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-point-operations).
Clean Windows, actual GUI, offline installation and power-loss remain separate
acceptance gates; mocks/CI source builds cannot mark those PASS.
