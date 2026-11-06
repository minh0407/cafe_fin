# Native increment 07 — first production Tauri wiring candidate

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-packaging-v1\cafe_fin`.
Branch: `codex/cafe-fin-packaging-20261107-v1`.
Apply after library commits 58c2b341 and d69506f9, with their approved core owner
dependencies already imported. Latest backend owner import in this worktree is
e9a9244 (original reporting owner 1783f01e). Do not use a moving main baseline.

## Implemented source

main.rs is now a thin Tauri dispatcher over native_controller.rs, serialized by
the existing lifecycle mutex on Tauri's blocking pool. It exposes the six agreed
maintenance/reports commands with camelCase invocation fields and existing output
DTOs. Build command metadata, main-window permissions and six generated permission
files match. No renderer path, role, actor ID, root ID or fingerprint grants access.

The production adapter negotiates maintenance v1 and a fresh child generation,
uses one bounded stdout reader, strictly verifies ready/loopback health, and keeps
the actual Runtime state independent of operation receipts. Native folder dialogs
run without holding the mutex and finish through correlated purpose-bound tickets.
Selection/display text is never parsed back as authority. An uncertain draft,
intent-write attempt or pending IPC cannot be reset through restart.

Run obtains fresh core source_identity before durable INTENT, then uses the serial
library pipeline for quiesce/prepare/receipt checks/clean close/config readback and
DORMANT target boot. Correlated CLOSED, observed process exit 0 and reader closure
are required before OLD_CLOSED. Timeout keeps the IPC correlation slot; a later
call first reconciles that exact response. Legacy shutdown/forced app-exit cleanup
never advances maintenance or serves as closure proof. A late activate ACK remains
DISPATCHED until a fresh full status verifies completion.

Explicit Activate requires fresh target Admin auth and candidate bindings. The
minimal ACTIVE ACK is followed by a new authenticated full status before archive.
Same-child status/activation returns boot_session=null. A non-null Run BootSession
is a session boundary requiring fresh target login. Status never implicitly starts
or activates a Runtime. Core remains the only activation-marker writer; native's
read-only comparison pins that marker to the saved journal before cutover/boot.

Cold recovery is a separate setup action before ordinary UI boot: source DORMANT
for pre-close move/restore phases, verified target DORMANT after durable closure/
config cutover, normal source for online backup. Ordinary start_backend(false)
with pending transition only attaches a qualified current child. Failure stays
held; no source fallback, initialize, auto-activation or origin rewrite. Candidate
construction may migrate DB and is never treated as side-effect free.

Open reports calls current core reporting.read authorization (Admin or permitted
Operator), rechecks current generation/liveness and the fixed currentRoot/reports
containment/reparse rules, then uses the existing fixed OS folder action. No shell
command, renderer path or stale late authorization can cause an OS open.

## Validation and build evidence

PASS on this Windows 11 Pro 10.0.26200 development host, i5-14400F, installed RAM
34,138,931,200 bytes, MSVC Build Tools/SDK 26100 via existing native-env.cmd:

- `cargo check --manifest-path desktop/Cargo.toml --locked --offline` with genuine
  rebuilt sidecar; final result without warnings.
- `cargo check --manifest-path tests/desktop/Cargo.toml --tests --bins --locked --offline`.
- `cargo fmt --manifest-path desktop/Cargo.toml --check` and the harness equivalent.
- `git diff --check` and scoped diff/permission review.
- `.venv/Scripts/python.exe -m pytest tests/core/test_maintenance_protocol.py -q`:
  28 PASS in 30.90 seconds, actual Python children/HTTP/core protocol tests.
- `desktop/scripts/build-sidecar.ps1`: genuine source build, Python 3.12.16,
  SQLite 3.53.1, PyInstaller 6.22.3, 36 notice distributions/51 native files.
  Ignored artifact: `desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`,
  33,410,537 bytes, SHA256
  `5fa30ca9e632a7ee3c13aaf4a2a1ae31bfb95e36660b5d52a6ea593e33d3c889`.
  Generated native inventory is committed; executable is not committed/uploaded
  or executed here. This is a compile input, not a release installer.

NOT RUN: Rust test executables or Tauri GUI on this host (previous Device Guard
block); no repeat execution, policy change or output-path workaround. Coordinator
can run ordinary harness tests on permitted Windows CI. The new ignored
wire_interop test is explicitly opt-in and uses the production Python entrypoint,
actual loopback auth, source identity, move/close, fresh target login, rejection of
source token, DORMANT status, minimal activation ACK and full ACTIVE status through
the Rust encoder/decoder. It is NOT marked PASS based on compilation. On permitted
CI with locked Python dependencies, set CAFE_FIN_TEST_PYTHON to the absolute build
Python executable and run:

`cargo test --manifest-path tests/desktop/Cargo.toml --locked --test wire_interop -- --ignored`

That test is a codec/core interoperability probe, not the production adapter,
GUI, installer, installed application or power-loss acceptance. Existing synthetic
transition tests cover ordering/failure fences using real journal/config files.
Clippy NOT RUN: component unavailable in the supplied toolchain.

## Remaining integration and release boundaries

Frontend owner 5af2d2b is not imported into this lane. Coordinator integrates its
current UI recovery-gate fixes with this native candidate. Compilation alone does
not prove actual OS dialogs, dispatch, session reset, Explorer open or all crash
paths. Candidate constructor failure leaves config/journal held; closing/reopening
the app retries qualified setup recovery, never the old source. No first-install
restore flow or persistent abandon/cancel API is introduced.

The documented native INTENT / absent core prepare-intent crash boundary remains
HELD with MAINTENANCE_GENERATION_CONFLICT on a new source generation. Only a
core-owned public recovery seam can resolve that immutable-origin case. Do not
reset journal/source binding to make it pass. Missing/nonzero/unknown close proof
likewise remains held. Old source data is always retained.

No migration, product dependency or core/frontend edits in this increment. Only
desktop/**, tests/desktop/** and packaging handoff docs change. No push, release,
signing claim, installer upload, real data, credential or outbound send. Clean
Windows/offline/update/uninstall/Word-PDF visual acceptance, installed 50k/500k/1m
benchmarks and existing license gates (including lxml/iconv provenance/relink
obligations) remain unresolved; this candidate is not production-ready.
