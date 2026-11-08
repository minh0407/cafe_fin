# Desktop delivery — baseline build, 08/11/2026

Assigned baseline eab8c96b851f039de515083189f4301cc09437c0 (only coordination docs
above business candidate 828d575b4a3c7b18ffafd8e2665a9d79b54ea403). Both READY tag
ancestry checks pass. New managed worktree:
C:/Users/NC/.codex/worktrees/cafe-fin-packaging-delivery/cafe_fin,
branch codex/cafe-fin-packaging-delivery-20261108. Old lane worktree is preserved.
This is a baseline build before integration of lane 00 runtime work, not final.

Windows 11 Pro 10.0.26200, x64 i5-14400F, RAM 34,138,931,200 bytes; C drive had
311,560,421,376 free bytes at environment check. Existing VS18 Build Tools/SDK
26100 and native-env.cmd were used without modification. Python 3.12.16,
SQLite 3.53.1, PyInstaller 6.22.3. Locked uv environment setup and npm ci PASS.

PASS: genuine desktop/scripts/build-sidecar.ps1, 51 native files. New executable
SHA256 DE82669E30C0FF247F8667FAA95252799E5AC091A4432F170B3C6AE9D885325F.
The actual file is in this worktree's ignored desktop/binaries directory; it is
not an installer, not the old CI hash, and has not been executed or uploaded.

Actual baseline preparation files and source archive were collected outside Git:
C:/Users/NC/.codex/artifacts/cafe-fin/20261108/baseline-eab8c96/.
Its build-receipt.json explicitly says BLOCKED_INSTALLER_MISSING. It is a
preparation collection, not an installable kit. Four synthetic receipt gate tests
PASS; scoped Ruff check/format and patch git-apply --check PASS. These gate tests
do not establish runtime, installer integrity or client acceptance.

FAIL/BLOCKED: one fresh normal NSIS attempt:
`tauri.cmd build --bundles nsis --ci -- --locked` after loading native-env.cmd.
Frontend tsc/vite production build PASS (large-chunk advisory remains). Cargo then
failed to execute icu_normalizer_data v2.4.0 build-script-build.exe, os error4551:
Application Control policy blocked this file. CodeIntegrity events3033/3077 at
2026-11-08 10:54:29 +07:00 confirm that exact worktree build helper was denied.
No local installer was produced. No retry, rename/path workaround, exclusion,
trust-policy change or execution of another candidate is attempted.

CI retention proposal is ci-retain-delivery-candidate.patch in this folder. It
does not change .github directly and has not been applied/uploaded by this lane.
Coordinator can review/apply it with candidate_receipt.py after source integration.
It pins actions/upload-artifact v4.6.2 to verified commit
ea165f8d65b6e75b540449e92b4886f43607fa02, seven-day retention, explicit staging only,
zero compression of compressed executables. Reference:
https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02
This is internal acceptance artifact retention, not a release/license clearance.

candidate_receipt.py requires actual matching sidecar/inventory, immutable source
and unchanged application inputs. Missing installer normally fails. Its explicit
allow-missing option records BLOCKED_INSTALLER_MISSING for the local preparation
kit; it cannot claim that a binary exists from a historical checksum. It copies
only candidate binaries/notices and a git archive of the assigned tracked source,
without Git history, data roots or environment files. Output must be new.

NOT RUN: local GUI, Windows client installation, offline first launch, PC2, update,
uninstall, signature/SmartScreen experience and installed benchmarks. WebView2
offlineInstaller is configured, not installation acceptance. Source/relink and
PC2 kit preparation continue independently. No production-ready claim or push.
