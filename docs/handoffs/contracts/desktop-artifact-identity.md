# Frozen application identity gate — 2026-11-08

Status: helper and synthetic archive tests PASS; actual final sidecar **NOT RUN**, artifact not supplied. No native build or old binary was used. This is preparatory QA in the contracts allowlist, not a replacement for packaging provenance or native acceptance.

`tests/contracts/artifact_identity.py` checks a supplied trusted executable SHA-256 before parsing its PyInstaller archive. It reads the exact committed tree through Git, compiles each tracked `backend/cafe_fin/**/*.py` using the verifier interpreter, and compares every packaged application module plus the separate executable entrypoint. Only `co_filename` is normalized because PyInstaller rewrites build paths; bytecode, constants, names, flags, line/exception tables and nested code remain compared. Missing, additional or changed application modules fail. Packaged application fonts, notices and contract JSON templates are compared byte for byte with the committed source. Python bytecode magic must match before unmarshalling the PYZ.

This checks application code/data only. It does not authenticate the person supplying the hash, verify bundled third-party/native components, prove a reproducible build, inspect an installer or execute the sidecar. It relies on the pinned PyInstaller archive format and matching Python version (this baseline: locked Python 3.12.16). An optimization/spec/archive-layout change needs review; a mismatch must be investigated, not silently ignored. Do not launch a different/older sidecar to fill an evidence gap.

After 00/05 deliver the final revision and retained artifact with receipt, run from the new worktree, substituting real values and a fresh output outside Git:

```powershell
.venv/Scripts/python.exe -m tests.contracts.artifact_identity `
  --binary <absolute-final-sidecar.exe> `
  --repo C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin `
  --revision <full-final-source-SHA> `
  --sha256 <trusted-sidecar-SHA256> `
  --output <absolute-new-external-identity.json>
```

Only a PASS receipt tied to that exact binary hash and final commit supplies application-source evidence. Then the independent `desktop_acceptance.py --binary ...` can run with new external data/output roots. Its provenance attachment remains labelled externally supplied evidence; it does not independently promote an arbitrary JSON declaration to verified provenance. Compare both manifests' binary hashes and commit manually. The harness restricts the frozen child's PATH and disables the market collector before boot, but neither condition proves a clean Windows machine or physically disconnected WAN.

Validation on the new locked environment:

```powershell
.venv/Scripts/python.exe -m pytest tests/contracts/test_artifact_identity.py -q
# PASS: 9 tests, 4.04 s
```

Tests create small synthetic Python archives in pytest temporary directories. They verify matching code/data/entrypoint, changed/missing/additional code, changed data, separate entrypoint mismatch, trusted hash guard, incompatible bytecode guard and filename-only normalization. They build no native executable and run no packaged code. Product source, dependencies, migrations, packaging and shared interfaces are unchanged.

Read-only expected-inventory compilation also PASS on committed `682861deae950de5cb4ebfb8cab7666439fd2903`: all 79 application modules and 11 packaged application data files normalized successfully. This checks verifier compatibility with the real source tree, not a frozen artifact match.

## Scoped Windows checkout CRLF delta — final source 3459370

Coordinator supplied artifact source `34593701477204cde2f5dc76181cb22a62e6eea2` and CI run `42457677174`. This lane independently verified the supplied sidecar SHA-256 `337a2e9ba21c7ad4c47bdcdebec5deb7c43aa26b54b2e0454869a442cd241f77`, then read its archive without executing it. Path: `C:\Users\NC\.codex\artifacts\cafe-fin\20261108\actions-3459370\expanded\release-candidate\binaries\cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`. All 79 application modules and the separate entrypoint match; both fonts match raw bytes. Before modifying the verifier, an independent byte comparison proved that all nine other assets are exactly `Git_blob.replace(b"\n", b"\r\n")`, with LF-only Git input and no other byte changes. These are two template JSON files plus seven known license/notice text files; per-path raw digests, sizes and EOL counts are retained outside Git.

Default verification remains **strict raw bytes**. Existing `strict-before.json` stays **FAIL** and was not overwritten. New opt-in CLI `--allow-windows-checkout-crlf` selects `windows_checkout_crlf_known_utf8_v1`, applying only to the nine explicit paths in `WINDOWS_CHECKOUT_CRLF_ASSETS`. It requires strict UTF-8 without BOM, LF-only source and exact whole-file conversion, without stripping/re-encoding content or whitespace. Existing tabs and form feeds remain byte-exact (the Pillow license has five form feeds). Other control bytes, mixed EOL, missing/new whitespace, BOM/content changes, unlisted assets and fonts/binary receive no exception. Python module/entrypoint, missing/unexpected data and executable-hash checks are unchanged.

Reports retain raw `data_diff`, `expected_data_digests` and `actual_data_digests`; `strict_status` remains FAIL even when the explicit policy returns overall PASS. `eol_only_assets` names every accepted path with raw expected/actual and expected-LF-to-CRLF digests, sizes and conversion count. `effective_data_diff` separately records unresolved mismatches. This policy is application-source compatibility evidence, not a reproducible-build, dependency, installer or runtime acceptance claim.

Evidence directory (outside Git): `C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-crlf-20261108-3459370`.

| Evidence | Result / SHA-256 |
|---|---|
| `strict-before.json` (original verifier) | FAIL, preserved; `c89c3c77f7cb3a16704756bd66cf929c45a6564c6dbc6ca5b0651ccf6f396693` |
| `raw-eol-proof.json` (before policy changes) | All nine exact LF→CRLF; `b53da59bf7ea11b223f4d9346abd98c3827b48b4656102d7520958b3e72f62e1` |
| `strict-final.json` (default CLI) | FAIL, same nine raw differences; `49963ba94e815201faf7cf30e14e78a18ba95d545d407d0ed586db40bee02ec9` |
| `windows-checkout-crlf-final.json` (explicit flag) | PASS, strict_status FAIL, exactly nine EOL-only exceptions; `5ec9a48c166bc457a6f0edca04a034cf2ad1371d5811d0a4afb847f456a63887` |
| `evidence-summary.json` | Cross-checks all receipts, unchanged raw diffs, two raw-exact fonts and helper/test source hashes |

Read-only reproduction: run the CLI above with the exact final source/binary/hash and a new external output; omit the flag for strict exit 1, add `--allow-windows-checkout-crlf` for policy exit 0. An intermediate opt-in receipt `windows-checkout-crlf.json` remains FAIL because the first text classifier rejected existing Pillow form feeds; the final classifier and regression test preserve them exactly. No old evidence was overwritten or deleted.

Validation: `.venv/Scripts/python.exe -m pytest tests/contracts/test_artifact_identity.py -q` **PASS: 30 tests, 11.93 s**; scoped Ruff check/format **PASS**. Tests include default versus explicit CLI, raw proof preservation, changed content/whitespace/BOM, mixed EOL, binary/invalid UTF-8, forbidden font/unlisted paths, exact form-feed preservation and unchanged code mismatch rejection. Native/UI/build/Docker checks **NOT RUN**, outside this tooling delta. Coordinator reported OS CodeIntegrity events 3077/3033 blocking this exact EXE before boot; this lane made no launch, retry or policy-bypass attempt. Runtime probes remain for the coordinator's permitted Windows Actions environment.

Delta worktree/branch remain `C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin` / `codex/cafe-fin-contracts-desktop-20261108`, starting `d16871907cef88f09052f101dc8e3f0e1f924a93`. Only this handoff and the verifier/test files change. No product, migration, shared interface/dependency or root checkout changes; no merge/push.
