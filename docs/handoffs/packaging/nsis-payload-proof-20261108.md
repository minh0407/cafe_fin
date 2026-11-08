# NSIS payload identity proof — 08/11/2026

Assigned baseline: eec5f95bc5d35d99a141e2ab678c136ac3ee3688.
Worktree: C:/Users/NC/.codex/worktrees/cafe-fin-nsis-payload-proof/cafe_fin.
Branch: codex/cafe-fin-nsis-payload-proof-20261108.

This separate coordinator-requested patch adds only verify_nsis_payload.py, its
synthetic tests and this handoff. It does not alter CI, the existing collector,
kit assembler, installer hooks, runtime, shared files or lane05's checkout.
No migrations or product API/interface changes. No push/upload/release.

## What the tool proves

The original collector can accept a stale installer in a reused build folder.
This tool reads the actual downloaded/collected NSIS archive with an already
permitted 7-Zip tool, selects exactly one regular cafe-fin-sidecar.exe member and
streams its decompressed bytes to SHA256 in memory. Its size/hash must equal
BOTH the receipted sidecar file and sidecar-native-inventory.json. It never runs
the installer, runs its script, writes/extracts a payload file, or opens a data root.

Before and after tool execution it verifies every receipted candidate file and
the exact SHA256SUMS map, source_commit against the caller's full expected SHA,
the matching source-archive filename, one receipted installer, and the sidecar
inventory. Receipt paths must be contained regular files, without links/junctions;
duplicate/case-colliding receipt paths and unsafe NSIS member paths are refused.
Listing must report Type=Nsis and one unambiguous sidecar member of expected size.
Folder/link/anti/encrypted members, ambiguous listing fields and wildcard/absolute/
traversal paths are refused. 7-Zip runs with argument arrays and shell=False.

Two pipes are drained concurrently; stdout/stderr have size bounds and each tool
command has a deadline (default120 seconds, configurable1..1200). Listing is capped
at4MiB, stderr64KiB and payload stdout at the exact expected sidecar size. Candidate
metadata/file/total bounds also apply. The tool's own hash is stable before/after.
Errors do not create a success receipt. Output must be a NEW file outside the
candidate collection; the parent directory must already exist.

The proof includes installer/source-archive/sidecar/inventory hashes, original
receipt/checksum-list hashes, exact member path and 7-Zip version/hash. Status is
always PAYLOAD_MATCH_ONLY; installer execution/GUI/signature remain NOT_RUN and
release_clearance is false. This is not proof that the installed app starts or
that notices/source/relink/legal or clean-Windows gates have closed.

## Coordinator invocation on an allowed runner

Run after NSIS build and candidate_receipt.py; or on an authenticated download
from the exact successful CI run. Independently compare that run's head SHA with
the reviewed SHA supplied below. A source label/archive filename does not itself
authenticate a Git commit; provenance relies on the selected CI run and receipts.
Do not derive --source from an untrusted downloaded receipt alone.

```powershell
$archiveTool = (Get-Command 7z.exe -ErrorAction Stop).Source
uv run --frozen python scripts/packaging/verify_nsis_payload.py `
  --candidate build/release-candidate `
  --source $env:GITHUB_SHA `
  --sevenzip $archiveTool `
  --output build/nsis-payload-proof.json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

For a downloaded candidate, replace source with the independently verified run
head SHA and use new explicit candidate/proof paths outside Git. The script can
verify an older candidate from a newer tooling checkout; --source identifies the
artifact, not the current tooling HEAD. 7-Zip must already be allowed/installed;
do not install it, change AppControl or use another executable path to bypass a
denial. Retaining this separate proof artifact is the coordinator's CI decision;
this patch changes no workflow or upload scope.

Primary format reference: https://www.7-zip.org/ lists NSIS unpacking support.
Actual parser/tool/installer interoperability remains NOT_RUN on this local host.

## Validation and limits

PASS: targeted synthetic tests cover source/status/checksum/inventory failures,
stale payload, modified installer during streaming, duplicate/unsafe/nonregular
members, source omission, a second receipted installer, receipt path escape/case
duplicates and immutable/external proof output. Actual small Python helper
processes verify binary stdout hashing, concurrent stderr draining, no-shell
invocation, timeout, output bounds and nonzero exit handling. These helpers are
Python source, not generated EXEs, NSIS, macros or imported app payloads.

PASS: `python -m pytest tests/packaging_delivery -q` —48 passed in2.86s, including
31 new payload-proof cases and17 existing packaging cases. Scoped `ruff check`,
`ruff format --check`, `py_compile` for the two new Python files and
`git diff --check` also PASS. Tests used the existing locked Python3.12 environment
from the packaging worktree; no environment/dependency installation occurred.

NOT_RUN: real 7-Zip/NSIS payload verification (no installed/allowed 7-Zip found on
this host); NSIS build, installer execution, installed GUI/offline acceptance,
PC2, upgrade and large benchmarks. AppControl is unchanged. All test bytes are
synthetic and temporary; no real DB/Excel/token/data-root or CRM was accessed.
