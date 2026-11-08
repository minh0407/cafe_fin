# Contracts desktop sidecar acceptance harness — 08/11/2026

## Scope and provenance

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin`.
Branch: `codex/cafe-fin-contracts-desktop-20261108`. Starting source: `eab8c96b851f039de515083189f4301cc09437c0`.

`tests/contracts/desktop_acceptance.py` is a standalone CLI for a real sidecar
process. It writes the actual newline-framed boot message to private stdin,
reads the bounded ready frame, and calls authenticated HTTP on the returned
`127.0.0.1` port with `httpx` (`trust_env=False`, redirects disabled). It uses
neither TestClient nor a browser mock. Windows subprocesses use `CREATE_NO_WINDOW`.
It does not build an executable, installer, or native runtime.

Select exactly one execution mode:

```powershell
.venv/Scripts/python.exe tests/contracts/desktop_acceptance.py `
  --python .venv/Scripts/python.exe `
  --data-root 'C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-desktop-UNIQUE-data' `
  --output-dir 'C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-desktop-UNIQUE-output'
```

For the final packaging candidate, replace `--python` with `--binary` and the
explicit sidecar EXE path supplied by lane 05. Use new external paths each run.
`--source-root` selects the expected source checkout; `--provenance` can preserve
an external artifact-identity JSON receipt and its hash. Supplying a SHA or a
receipt does not cause this harness to assert that a frozen EXE matches source.
The coordinator verifies the exact binary hash and source revision separately
with `tests/contracts/artifact_identity.py`. Frozen `source_match` stays
`NOT_VERIFIED_BY_HARNESS`; assess the external receipt alongside the manifest.

For source mode the manifest records interpreter path, executable SHA-256,
actual import origin, Python version, observed Git HEAD/backend status, and a
hash inventory of backend code/data/fonts before and after acceptance. Each
child PID, executable hash, boot/shutdown result, and exit code is recorded.
The harness/fixture source hashes are also recorded. Session/login tokens and
the randomly generated local password stay in memory and are never included
in command-line arguments, printed results, or evidence. Stderr is drained to
a count/hash, without copying arbitrary stderr text into the report.

## Data and network boundaries

Both data root and output directory must be absolute, nonexistent local paths
with existing parent directories. Existing roots, repository descendants,
operational-root descendants, overlapping roots, and UNC locations are refused.
The harness never deletes/reuses an existing operational root. All generated
SQLite data, documents and manifests stay outside Git.

The market collector defaults enabled and can run before login. The child uses
the existing production guard `CAFE_FIN_MARKET_NETWORK=0` from boot, then Admin
disables the collector through `PUT /records/market/processed/settings` and
verifies that reporting is disabled/unconfigured with no automatic generation.
The harness does not change firewall, adapter, system policy, or startup settings.
This proves collector-disabled local functionality and loopback HTTP use; it
does **not** prove a physical WAN cut or clean-Windows operation. Frozen mode
uses a System32-only child PATH and removes Python environment overrides; that
still does not make the developer host a clean client.

## Acceptance flow

1. Create a fresh root and a synthetic local Admin. Before seeding any records,
   preview/save/export a fully manual purchase contract with no source references
   or attachment. Compare public stock/cash/accounting state before/after.
2. Through public records commands, seed a Farm, a customer company, and two
   manual weighings. Seed the complete fixture PartyInput, retaining the long
   customer name/address, representative, contacts and bank details. No private
   records ORM or DB mutations are used.
3. Resolve both sources through the contracts typed read bridge. Copy the rich
   party DTO and source weighing snapshot; retain the user's fixture quantity
   and chosen price. Source net kg deliberately differs from contract quantity.
   Assert the saved party fields match input and that names, full addresses,
   contact values, bank names and account numbers appear in document text.
   Known quantity-source labels must be localized; source snapshot kg uses
   Vietnamese separators. A custom human quantity-source description on the
   manual contract must remain literal.
4. Preview/save/export purchase and sale to DOCX and PDF. Check independent
   literal fixture totals, canonical complete snapshot SHA-256, file hashes,
   byte sizes and response hash headers. Export errors produce FAIL.
5. Replay each command: exact returned version/files, one version, and no new
   physical document. Public API references and physical files are checked;
   there is no unsupported claim of a generic private DB file-metadata count.
6. Verify source records are unchanged by contract overrides, then edit source
   party/weighing, draft terms and the template through their public APIs.
   Reload the original version and compare exact original bytes and hashes.
7. Compare public records dashboard, stock balances/movements, receivables,
   trades/entries/payment counts and accounting books before/after contracts.
8. Send trusted-parent shutdown, require exit 0, start a new process on the same
   root, log in again, and verify all original versions/files and side-effect
   state. This is graceful shutdown/restart evidence, not maintenance CLOSED ACK.

The run creates **three versions and five files**: `manual.docx`,
`purchase.docx`, `purchase.pdf`, `sale.docx`, `sale.pdf`. Optional attachments
remain absent. `manifest.json` contains expected totals, expected/observed
snapshot hashes, actual file metadata/paths and the full synthetic snapshots.
No visual layout PASS is inferred from successful bytes or extracted text.

## Validation and evidence

- PASS: `python -m pytest tests/contracts/test_desktop_acceptance.py -q` — 9
  focused guards for external/fresh paths, loopback-only handshake, and refusal
  to accept caller assertions as frozen-source verification.
- PASS: scoped Ruff check/format and CLI `--help`.
- PASS: actual source sidecar run on committed source
  `682861deae950de5cb4ebfb8cab7666439fd2903` with Python **3.12.16**, initialized
  process PID 31168 and restarted process PID 5352; both exit 0 with empty stderr.
  Backend status was clean before/after the run. This includes the lane-owned
  quantity-label/source-kg presentation fix found during visual review.
- Source executable SHA-256:
  `2a5550d982664f182db9b0629bebdadc6a980b0093b8741966e820419288211d`.
- Observed backend tree SHA-256:
  `a9223c2f593cc6eee4d2af319efadd7aafe8301ad5c2e7cdd88c3b650efcecbc`.
- Exact acceptance harness SHA-256 used by the final run:
  `b2b780bc755bc7deb09424baaf652def013a604026973e14af470174953b118f`.
- Final rich-fixture source evidence:
  `C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-desktop-source-20261108-efa2d9ee67-output\manifest.json`.
  Data root uses the same prefix ending `-data`. The generated five files are
  alongside the manifest for the separate visual QA workflow.
- The earlier `88a1001d7d` run passed with minimal seeded parties and is superseded
  for rich visual coverage. Intermediate `2cfd670517` failed a harness comparison
  of DTO-added null defaults against input; the assertion direction was corrected.
  Rich `3576bf944d` passed but predates the presentation fix. Intermediate
  `dcec187d25` correctly rejected a harness-generated request key after a local
  variable shadowed its label; the harness variable was corrected. These two
  harness defects required no application/core edits. Final `efa2d9ee67` passed
  all checks and supersedes those artifacts for current acceptance.
- NOT RUN: frozen sidecar/installer (no matched artifact supplied), native GUI,
  clean Windows/second PC, and physical WAN-cut testing. Visual QA is owned by
  the separate contracts render check; see `desktop-render-qa.md` for its status.

No migrations, shared runtime, dependencies, records/accounting implementations,
or old/coordinator checkout were changed by this harness work.
