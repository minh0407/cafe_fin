# Private maintenance protocol v1

This is the frozen native-to-sidecar wire contract. It adds a capability to boot
protocol_version=1; it creates no HTTP maintenance endpoint and grants no filesystem
permission. Native must durably record transition intent before quiescence and
must retain its journal on an unknown result. Paths/tokens are private pipe inputs,
never renderer arguments, stdout fields, diagnostic text or transport receipts.

## Framing and schemas

Exactly one binary stdin reader reads boot and subsequent UTF-8 JSON lines. Each
line, including newline, is at most **262144 bytes**. Reads use the byte limit
before decode/JSON parsing; no text/binary read-ahead mixing or unbounded read.
Malformed UTF-8/JSON, duplicate object keys, nonfinite JSON numbers, unknown fields,
unknown commands, missing newline and oversized frames fail closed with a fixed
code and nonzero exit. A valid legacy shutdown frame is precisely
`{"command":"shutdown"}`; it remains trusted-parent ordinary app exit, including
on a negotiated connection, and never produces a maintenance CLOSED proof.

The strict schemas allow one path in boot and at most two in restore preparation.
Each path must be absolute, have no NUL, be at most 32767 Unicode characters and
at most 98304 UTF-8 bytes. The core operations revalidate actual local-path,
containment/reparse/identity/manifest policy; transport validation is not authority.
No inline file bytes, workbook data, manifests or arbitrary result objects exist.

Stdout has one lock-protected JSON-line writer. Each encoded response including
newline is at most **16384 bytes**. No request or exception representation is
printed. Token and path model fields use repr=False. Unknown implementation errors
map to MAINTENANCE_COMMAND_FAILED; known domain codes use an explicit allowlist.
There are no raw exception messages, field values or tracebacks in responses.

## Boot and handshake

Legacy boot keeps protocol_version, session_token, data_root, initialize and
allowed_origin unchanged. Without capability, generation must be absent/null and
activation_mode defaults to active; dormant requires negotiation. Negotiated boot:

```json
{"protocol_version":1,"maintenance_protocol":1,"generation":"<canonical UUID>","activation_mode":"dormant","session_token":"<private app session>","data_root":"<native absolute path>","initialize":false,"allowed_origin":"http://tauri.localhost"}
```

Versions must be integers (bool is rejected). UUID identities must be canonical
lowercase strings. Negotiated ready adds maintenance_protocol=1, generation and
runtime_state to the existing protocol_version/status/api_base fields. A legacy
ready response retains its original shape.

Runtime performs its phase-2 boot guards before any HTTP lifespan/start. An archive
without activation binding is rejected. If Runtime forces dormant for a pending
physical-root transition but boot requested active, boot fails MAINTENANCE_REQUIRED
and closes before creating HTTP/lifespan; this applies to legacy clients too.
An explicitly negotiated dormant boot permits only the phase-1 safe HTTP routes;
no recovery, startup hooks, job worker or timer is started. Dormant construction
still validates/migrates DB as documented by core; it is not a read-only sandbox.

## Commands

Every command includes exactly maintenance_protocol=1, a fresh canonical request_id,
current child generation, command and access_token. Tokens are 1–128 characters,
private memory only; they are authenticated by the target core on every operation.

| Command | Additional fields | Binding |
|---|---|---|
| maintenance.quiesce | operation_id, origin_generation | Runtime.quiesce |
| maintenance.prepare | operation_id, origin_generation, kind, destination; backup_source only for restore | MaintenanceOperations.prepare |
| maintenance.status | operation_id, origin_generation | MaintenanceOperations.status |
| maintenance.activate | operation_id, origin_generation | MaintenanceOperations.activate |
| maintenance.close | operation_id, origin_generation | authorize_close, then verified teardown |
| reports.authorize_open | none | authorize_open_reports, current reporting.read |
| maintenance.source_identity | none | authorize_source_identity, current core.manage Admin |

kind is backup/move/restore. Preparation destination is the native-selected final
child path from native-ui-contract-v1.md, not a renderer-supplied path. Restore
requires backup_source; other kinds reject that field even when null. Reports
opening accepts no operation ID, path, actor, role or root identity.

Additive source identity command (no boot-field changes) supplies the current
physical source binding before native writes its journal INTENT and requests
quiescence. It does not need a preexisting operation/intent and creates none:

```json
{"maintenance_protocol":1,"request_id":"<fresh canonical UUID>","generation":"<current child UUID>","command":"maintenance.source_identity","access_token":"<current Admin token>"}
```

It extends Control directly, so operation_id, origin_generation, paths and input
identity/role fields are forbidden. Core freshly authenticates and checks current
core.manage under the Runtime lifecycle lock and serialized authorization fence,
then validates the canonical opened root. Public Python method
`MaintenanceOperations.authorize_source_identity(access_token)` returns only
root_id and source_fingerprint. Its bounded private response is exactly:

```json
{"maintenance_protocol":1,"request_id":"<matching UUID>","generation":"<current child UUID>","status":"ok","state":"ACTIVE","runtime_state":"ACTIVE","root_id":"<lineage UUID>","source_fingerprint":"<opaque core fingerprint>"}
```

state/runtime_state always reflect the actual admission state, including DORMANT
when applicable. The same current-generation and fresh recent-window nonce checks
apply. Operator, revoked or logged-out users receive no source identity. The call
does not mutate DB/files, create an intent/receipt/login, freeze admission or grant
permission. Native stores the returned binding in its own durable journal before
quiesce; native must not hash path spellings itself or call a private core helper.

The child serializes commands. It rejects a stale generation without invoking a
core operation or consuming the current-generation nonce namespace. A current-
generation request ID can be used only once per child (including core rejections);
a retry uses a **new request ID with the same operation ID and immutable
payload**. Origin generation is the original operation generation, not the current
transport generation after recovery; operations verify its stored binding. UUIDs
are not permissions. Nonce memory is a bounded recent window of 4096 accepted IDs;
oldest IDs are evicted without limiting the child's lifetime or blocking status,
recovery or close. A duplicate still in the window is rejected. After eviction an
old request ID may be processed again, with fresh target authentication and the
same core operation/receipt checks; this is not permanent replay history. Native
must mint fresh UUIDs for correlation. The private parent pipe, generation check,
current authorization and immutable operation ID/receipts remain the security and
mutation/idempotency boundary. No HTTP client can submit these private frames.

## Exact response projection

Each parsed-command response contains:

```json
{"maintenance_protocol":1,"request_id":"<matching UUID>","generation":"<current child UUID>","status":"ok","state":"PREPARED","runtime_state":"QUIESCED","operation_id":"<matching operation UUID>"}
```

operation_id is present only for operation commands. status is ok/error. Errors
add only a fixed code; no raw message/payload/paths/tokens are included. These are
the only optional result fields: kind, root_id, source_root_id, candidate_root_id,
manifest_sha256, source_fingerprint, candidate_fingerprint, allowed. IDs are
canonical UUIDs; hashes/fingerprints are lowercase 64-character hexadecimal;
allowed is a boolean. Unknown controller dictionary fields are omitted. In
particular activation markers, private intent bodies, source/destination paths,
activation_completed and raw manifests are not dumped.

state can be ACTIVE, QUIESCING, QUIESCED, PREPARING, PREPARED, CLOSING, CLOSED,
DORMANT, ACTIVATING, FAILED_HELD or REPLAY_REQUIRED. REPLAY_REQUIRED is an operation
reconciliation result; runtime_state always describes the actual admission gate.
An operation result with a fixed failure code becomes status=error. Malformed
frames/schema failures are terminal and may return an uncorrelated bounded error;
native must treat it, EOF or nonzero exit as an unknown/held transition, never as
success. Stale-generation, nonce and authorization errors on valid commands are
correlated and do not close a normally operating child.

## CLOSED proof and EOF

For maintenance.close, core first authenticates the current target Admin and
checks the exact operation/origin binding. Only after that does the child request
HTTP server exit, drain/close Runtime, wait for the HTTP thread and its lifespan
finally to finish, successfully call idempotent Runtime.close again and close the
listener. Then, and only then, it emits the matching status=ok/state=CLOSED and
exits **0**. There is no subsequent potentially failing teardown after that ACK.

A close failure returns a correlated error, never a successful CLOSED state, and
exits nonzero. Resources remain held according to Runtime's fail-closed rules until
safe closure or unclean process termination. The transport does not force-kill or
claim an eight-second kill is safe. A missing/lost ACK, pipe EOF, malformed frame,
stdout write failure or nonzero exit never authorizes native to switch roots.
Native must observe both matching CLOSED **and exit 0**. Ordinary legacy shutdown
can exit 0 but provides no maintenance proof.

## Validation and limits

The focused suite uses bounded binary-reader/writer and dispatcher boundary tests,
plus real Python child processes, loopback HTTP, SQLite, FileStore and actual core
operations. It covers legacy shutdown versus EOF, strict/malformed/oversized frames,
UTF-8 path bounds, generation/nonce correlation, sanitized failures, current Admin/
Operator/revoked authorization, online backup preparation/status, real move source
quiescence, active/legacy candidate boot refusal, dormant fresh-target login and
activation, clean closure, HTTP stream drain and failure in final post-HTTP close.
No actual Zalo call, live credential, installer/UI or power-loss proof is included.
The core phase-2 tests own backup/restore/quarantine correctness beyond these wire
integration cases. No fake method result is presented as filesystem acceptance.

Final transport validation: **28 PASS, 30.28 seconds**, scoped Ruff lint/format and whitespace checks PASS. The bounded recent-window test executes over 8192 distinct safe dispatcher commands, rejects a recent duplicate, rechecks authorization after eviction, and keeps close callable. A separate current-policy test proves reports opening uses fresh reporting.read rather than an Admin-only shortcut. Error projection preserves a whitelisted operation FAILED_HELD state while runtime_state still reflects the actual admission gate. The actual-backup child uses a two-entry test window to prove an evicted wire ID replays the same verified core artifact and cannot bypass a logged-out token. It does not substitute a filesystem result. Earlier combined protocol + existing API/sidecar/file-transfer/recovery regression was **44 PASS, 55.11 seconds** before the final recent-window and unexpected-BaseException hardening; the final 28-case transport suite was rerun after both changes. The existing nineteen HTTP regression cases were not repeated for the private-window-only change. No commit/push
or native/UI/activation/operations source edits belong to this transport increment.

Additive source-identity validation: **39 focused cases PASS in 34.42 seconds**
(`test_source_identity.py` plus the 28-case transport suite). Real current Admin
reads leave all SQLite rows, data-file hashes, sessions, admission and the live
exclusive root lease unchanged. Operator, revoked/logged-out token, stale generation
and repeated recent nonce are denied; schema probes reject operation/origin/path/
identity inputs. The real child flow now obtains source identity before preparing
a verified backup and matching CLOSED plus exit 0, and checks the prepared source
UUID/fingerprint match the earlier identity. Scoped Ruff lint/format and whitespace
checks pass. Evidence XML/log is outside Git as `source-identity-20261107.{xml,txt}`.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_source_identity.py tests/core/test_maintenance_protocol.py -q -p no:cacheprovider
```



