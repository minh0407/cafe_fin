# Private maintenance operations and candidate activation

Phase 2 adds core operations behind the phase 1 admission/quiesce boundary. It
does not implement stdio frames, native picker handles/journal/config replacement,
first-install restore/bootstrap, UI, owner reporting quarantine logic or clean
process-exit proof. No commit/push is performed by this implementation lane.

## Interfaces for the protocol/native adapter

```python
from cafe_fin.core.maintenance_operations import MaintenanceOperations

operations = MaintenanceOperations(runtime, generation=current_child_generation)
operations.prepare(operation_id, kind, access_token=current_token,
    origin_generation=original_generation, destination=trusted_native_path,
    backup_source=trusted_native_backup_path_or_none)
operations.status(operation_id, access_token=current_token,
    origin_generation=original_generation)
operations.authorize_open_reports(current_token)
operations.activate(operation_id, access_token=current_target_token,
    origin_generation=original_generation)
operations.authorize_close(operation_id, access_token=current_token,
    origin_generation=original_generation)
```

Operation/generation IDs are canonical UUIDs. Paths are accepted ONLY by this
trusted Python/private parent-control interface; no HTTP route or renderer raw
path is added. Native resolves its purpose/generation/op-bound picker handles.
Before any quiesce the native transition journal must already be durable. Native
and core control calls are serialized; the core reuses the Runtime lifecycle lock.

Native selects an existing local parent and derives the final child. Core enforces
`CafeFinBackup-<operation_id>` for backup and `CafeFinData-<operation_id>` for
move/restore. Destination is new and independent of the live root; restore source
and destination are independent. Local/cloud/reparse/containment preflight runs
before intent/copy and again at use. One core canonicalizer resolves the path,
applies OS case normalization and hashes it. Native treats fingerprints as opaque.

Prepare/status/replay/activate/close require current Admin `core.manage`, including
an actual serialized writer authorization fence. A queued role/version change or
token invalidation prevents receipt replay/completion. OpenReports requires current
`reporting.read`, including an Operator who has it, and returns exactly:

```json
{"allowed": true, "root_id": "<lineage UUID>"}
```

The protocol adds request ID/current generation. Native independently checks its
current generation and currentRoot/reports containment/reparse policy. Core returns
no reports path and accepts no arbitrary path for this command.

Prepare result is a bounded dict with `state=PREPARED`, operation_id, kind,
origin_generation, source_root_id, candidate_root_id, source_fingerprint,
candidate_fingerprint and manifest_sha256; move/restore also have activation_id.
Source status re-verifies published artifact/marker, returning that receipt or
`REPLAY_REQUIRED` / `FAILED_HELD` with a fixed code when proof is insufficient.
Candidate status adds marker fields, activation_completed and its current state;
an activation intent without completion is REPLAY_REQUIRED. These operation states
are distinct from `runtime.maintenance.status()['state']`: the native adapter must
not inject REPLAY_REQUIRED into its RuntimeState enum.

`authorize_close` returns CLOSE_AUTHORIZED only. It authenticates the operation
against the current source intent or candidate marker. The dispatcher must still
call Runtime.close, wait for HTTP-thread exit and observe process exit code 0 before
claiming CLOSED. PID disappearance, an eight-second kill or a lost ACK is no proof.

## Receipt and copy behavior

Existing REQUESTS stores immutable `maintenance.intent` and `maintenance.prepared`
actions, keyed by operation ID under reserved actor `core.maintenance`. This is a
receipt namespace, never a privileged Principal or an authenticated actor. Real
current Admin authorization runs for every call/replay; Audit records the actual
Admin ID. Thus a different current Admin can reconcile an existing operation.
No new DB schema/migration is required.

Intent binds kind, operation/origin generation, canonical source/destination,
physical fingerprints, source lineage and the pinned restore backup manifest hash.
Changing source/destination/kind/origin for the same operation conflicts. Private
core metadata may contain operational paths; neither tokens nor credentials enter
receipts/audit. These records are not exposed through a new HTTP endpoint.

Intent commits before copying. Optional BackupService operation metadata writes
`.cafe-fin-operation.json` inside the partial before final rename. It carries the
operation ID, canonical payload hash and bounded provenance binding. Backup/move
snapshots must also contain their committed intent inside their copied DB. Restore
targets must match the pinned original backup manifest. Ordinary backup remains
online; a concurrent real writer can finish while immutable source copying waits.

Move/restore require QUIESCED with the same operation ID and leave admission held
after PREPARED until the source actually closes. Move uses the existing verified
snapshot copy at the destination directly, avoiding an extra intermediate copy.
The older low-level BackupService.move primitive does not own Runtime admission;
native maintenance must use this controller and not call that primitive directly.

Copy/receipt/IPC/config cannot be one atomic transaction. After final publication
but before completion/ACK, the fixed destination can be adopted only after full
hash/reference/provenance/intent verification. No new destination or silent
overwrite is chosen. Completion pins the published manifest hash. Completed
move/restore replay/status also rechecks the activation marker. Unknown existing
folders are rejected. Unpublished partials remain untouched; retry can create a
fresh online backup snapshot, whose actual manifest timestamp/hash describe that
new cutoff. There is no broad partial deletion or invented old cutoff.

## Activation marker and owner hook

Core alone writes target `.cafe-fin-activation.json` after verification and before
PREPARED. Marker v1 fields are format=1 plus the frozen public context:

```python
from cafe_fin.core.activation import ActivationContext

# Frozen str fields:
# activation_id (= operation_id), kind ('move' | 'restore'), origin_generation,
# source_root_id, candidate_root_id, source_fingerprint, candidate_fingerprint,
# manifest_sha256
# context.operation_id aliases activation_id; context.marker() serializes v1.
```

The copied root UUID is lineage, not physical identity or authority. Core validates
the actual candidate path/marker/root identity, original manifest hash and operation
provenance. A marker copied to another physical location is rejected. Completion
receipts must match the marker before normal active boot is allowed.

ModuleManifest adds optional `on_activate(runtime, principal, context)`, default None,
with callable validation. Runtime.activate persists activation intent before hooks,
then invokes public hooks before ANY recovery/on_startup/worker/timer. Owner hooks
must revalidate their supplied target principal in each writer transaction. They
own their tables/settings and an idempotent quarantine/reconciliation receipt;
core does not import or write reporting private tables or copy/delete OS secrets.

Restore requires a reporting manifest with on_activate before prepare/copy, and
independently rechecks at target activation. Missing support yields
RESTORE_GUARD_UNAVAILABLE; this build must not claim working restore capability
until the reporting owner implements/reviews that hook. The hook must quarantine
restored schedules/retryable sends using owner semantics before ordinary startup.

Activation completion is recorded only after successful startup. Same operation
replay and later normal restart skip activation hooks once completion is proven,
so an explicit later Admin configuration choice is not disabled again. Failed
partial hooks/startup/completion retain the intent without completion. The current
Runtime remains held; a new Runtime is forced dormant and returns
ACTIVATION_REPLAY_REQUIRED rather than automatically repeating partial effects.
No abandon/fallback/disposition API is supplied in this increment.

## Boot guards and remaining boundaries

Runtime performs core boot preflight itself; the protocol adapter must not duplicate
the scans. A raw backup/archive without a candidate activation marker fails with
BACKUP_ARCHIVE_NOT_ACTIVE. Pending candidate markers, source relocation intents
and unfinished activation intents force dormant even if active was requested.
Source relocation intents remain conservative fences: no automatic old-root
reactivation or implicit cancellation exists. Dormant direct `start` does nothing.

The stdio adapter must reject an unnegotiated/requested-active boot that core forced
dormant, rather than reporting an ordinary active READY. Explicit negotiated
dormant boot may expose secured health/login/logout so the target Admin can log in.
Source tokens are not transferred to the target Runtime or treated as target users.

Dormant construction still validates/migrates the candidate database. First
activation requires a fully verified original backup snapshot; if constructor
migrations changed those bytes, activation conservatively fails verification and
needs an explicit migration-aware recovery path. This increment does not claim
cross-version restore acceptance or silently bless a changed candidate hash.
Native must never automatically fall back after candidate construction/effects.

Native journal/config durability, exact CLOSED transport framing, reporting owner
restore quarantine, migration-aware restore recovery and first-install restore are
separate remaining integration gates. No live credentials, network, benchmark,
reboot, policy changes or clean-Windows acceptance are claimed here.

## Verification

The focused tests use real SQLite/FileStore snapshots and original byte/hash
verification. They cover online concurrent backup, cross-Admin receipt replay,
revocation after copy before completion, copy failure with retained partial, the
published-copy/receipt ACK gap, source/destination/origin conflicts, Unicode and
real Windows junction rejection, a real pending accounting parse job preserved
in a dormant copy, source held until close and dormant on reopening, hook order
before recovery/threads, activation receipt idempotence, partial activation failure,
marker physical/provenance/completion binding, changed originals and missing restore
hook denial before copy and at activation. Fault injection chooses crash/ACK
boundaries while the filesystem/SQLite effects remain real; native process-kill
transport coverage belongs to the separate protocol increment.

Earlier combined regression: 84 PASS in 73.84 seconds across the initial phase 2
cases, phase 1, storage, registration, auth/jobs, sidecar, periodic and actual
business-workflow integration. Final scoped PASS: **52 cases in 31.94 seconds**,
including all **19 new phase 2 cases**, phase 1 admission/dormant/quiesce,
storage and module registration. JUnit records zero errors, failures or skips;
the existing Starlette/httpx deprecation warning remains. Scoped Ruff lint, format
check on all eight Python paths and Git whitespace check pass. No full backend
or large benchmark rerun.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_activation.py tests/core/test_maintenance_operations.py tests/core/test_runtime_maintenance.py tests/core/test_storage.py tests/core/test_module_registration.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/activation.py backend/cafe_fin/core/maintenance_operations.py backend/cafe_fin/core/modules.py backend/cafe_fin/core/runtime.py backend/cafe_fin/core/backup.py backend/cafe_fin/core/storage.py tests/core/test_activation.py tests/core/test_maintenance_operations.py
```

XML/log evidence is outside Git under the session visualization directory:
`maintenance-operations-phase2-20261107.{xml,txt}` (84-case regression) and
`maintenance-operations-final-20261107.{xml,txt}` (final 52-case run).
