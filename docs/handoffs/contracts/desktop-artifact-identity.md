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
