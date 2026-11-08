# Bàn giao kit chuẩn bị desktop — 08/11/2026

Worktree: C:/Users/NC/.codex/worktrees/cafe-fin-packaging-delivery/cafe_fin.
Branch: codex/cafe-fin-packaging-delivery-20261108.
Assigned source: eab8c96b851f039de515083189f4301cc09437c0, business code identical to
828d575b4a3c7b18ffafd8e2665a9d79b54ea403. This remains the pre-runtime-integration
baseline. Do not substitute this kit for the coordinator's eventual final SHA.

## Actual files outside Git

- Preparation folder:
  C:/Users/NC/.codex/artifacts/cafe-fin/20261108/pc2-preparation-eab8c96/
- ZIP:
  C:/Users/NC/.codex/artifacts/cafe-fin/20261108/pc2-preparation-eab8c96.zip
  — 302,992,401 bytes, SHA256
  8ad52941fad9cec7492103bcce607027ebd624bf8b6a304708581d4916452614.
- Readback/integrity receipt:
  C:/Users/NC/.codex/artifacts/cafe-fin/20261108/pc2-preparation-eab8c96.integrity.json.
  All8,629 payload files/389,142,783 bytes hash-verified, manifest/checksum list
  consistent, ZIP readback CRC PASS. Status is FILE_INTEGRITY_PASS_ONLY;
  PREPARATION_ONLY_NOT_READY_FOR_INSTALL. No upload or transfer was performed.

The folder includes source/version/dependency-lock/notices/checksum receipts;
actual rebuilt baseline frozen sidecar; exact tracked app source archive; all12
pinned source/native materials and unpacked trees; recipient recipe; GUI client
guide; CSV/XLSX/XLSM fixtures and expected results; offline WebView2 support file;
and RESULTS.json with client cases NOT RUN. It **does not contain an installer**.
The preparation warning is the first text in START_HERE.txt.

Baseline frozen file: 33,475,329 bytes, SHA256
de82669e30c0ff247f8667faa95252799e5ac091a4432f170b3c6ae9d885325f.
WebView2 standalone x64 support file: 214,927,568 bytes, SHA256
2688308af55753c62fda4e8140024e230c1ffc16b7c091b25889572f38dff6e8.
It was downloaded from Microsoft's x64 fwlink2124701. Get-AuthenticodeSignature
returned Valid, Microsoft Corporation. Installer product metadata1.3.315.17 is
not asserted to be the runtime version. The support file was NOT installed/run;
its presence/signature do not prove Cafe Fin's offline setup/first-launch path.
https://developer.microsoft.com/en-us/microsoft-edge/webview2/

## What was actually checked

PASS: locked uv/Python setup; npm ci; genuine sidecar build; frontend tsc/vite
production build. Node24.21.0, npm11.19.0, Rust/Cargo1.99.1. Frontend notices
regenerated from146 installed locked packages and Rust notices from279 reachable
Windows crates; their normalized content matched baseline. Existing line-ending
noise was restored. Backend notices came from the fresh sidecar build. Full
iconv COPYING.LIB2.1 was added as a separate notice, without closing its gate.

PASS:17 synthetic packaging gate/integrity cases; scoped Ruff check/format;
compileall for packaging scripts; Node syntax check; PowerShell AST parse;
source archive/native asset size+hash validation; upstream iconv patch --check;
relink plan-only with12 files; candidate-retention patch git apply --check.
These checks do not stand in for core/runtime/GUI/installer acceptance.

The single-sheet mini workbook was authored with the bundled Artifact Tool,
inspected and visually reviewed. Saved readback verifies code0001 remains a
string, dates are typed, null and0 remain distinct. Expected counts/totals are
explicit fixture scenarios, not imported data or a performance claim. Corrected
an export-variant issue in the XLSM helper (implicit main MIME/no dimension) before
assembling this kit; a structure regression covers both cases.

preserve-only.xlsm is a macro-enabled OPC container with the byte-pinned XlsxWriter
example vbaProject.bin and a reserved example.invalid external reference. VBA
sample provenance/license and expected original hashes are supplied. oletools0.60.2
was used in an isolated developer environment only for static source extraction:
say_hello/MsgBox source, other extracted modules empty, hex-string warning. No VBA,
external link, Office application or macro function was executed. This is not
a safety/P-code certification or native Excel compatibility acceptance.
https://github.com/jmcnamara/XlsxWriter/tree/e943bee8c9cdf0661cfdb83d5497e0725390e41e

## Blockers and next coordinator action

1. Local NSIS is BLOCKED: the one new normal build failed on Enterprise AppControl
   os error4551 for icu_normalizer_data build-script-build.exe; events3033/3077.
   Details in delivery-20261108-build.md. No policy change, rename/path workaround,
   extra native execution or repeated build attempt. Local GUI/install/offline/
   upgrade/uninstall/PC2 remain NOT RUN. This machine is a development host.
2. Apply/review the separate ci-retain-delivery-candidate.patch with the receipt
   script if appropriate. .github itself was not edited here. Retention follows
   actual repository/Actions permissions; the name “internal” adds no privacy
   boundary or release/license clearance. It collects explicit candidate files,
   not data roots/logs/environments. This lane has not uploaded anything.
3. Integrate lane00/runtime and module changes, including command metadata in
   build.rs if its approved interface needs it, then assign an exact final SHA.
   Build/retain that matching final installer on the permitted runner. Reassemble
   with a fresh receipt and new output path; do not reuse this baseline checksum.
4. Source/relink material now exists, not just notices. Actual recipient -Build
   remains NOT RUN: local compiler is14.51 while the reviewed recipe requiresv143
   14.44.x; AppControl also prevents native build/test proof here. Complete the
   recipe in a permitted matching environment, assess historical wheel provenance
   or a controlled rebuilt artifact, and review recipient modification/debugging
   terms. SOURCE_RELINK_20261108.md gives the concrete recipe/remaining gates.
5. Only after appropriate artifact/material decisions, perform GUI evidence on
   the actual Windows11x64 PC2. Do not preinstall WebView2 before the missing-runtime
   offline case. No access to PC2 occurred here. No from/to version pair was
   assigned, so version-upgrade acceptance is also NOT RUN.

No migration or core/frontend/runtime/Cargo/capability/shared-harness change.
Only packaging scripts, separate packaging tests, notices and release/handoff
docs changed. No new chat/cross-chat message, real data, old CRM/Docker volume,
startup setting, credential or Telegram group send. No push/merge/release.
No production-ready or full desktop-delivery completion claim.
