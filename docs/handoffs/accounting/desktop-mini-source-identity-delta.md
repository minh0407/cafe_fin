# Source UI approved-identity delta after f1bfc4f

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting-desktop-20261108\cafe_fin`.
Branch: `codex/cafe-fin-accounting-desktop-20261108`.
Harness HEAD during this validation: **`f1bfc4f0fd12e8bd586e5ebdded6cf9e176b9913`**.
The coordinator explicitly authorized that source for this mini run. It has the same product paths as the historical eab baseline; it is **not** a coordinator final-candidate/native/packaged designation.

## Change and source contract

The UI source harness now accepts `CAFE_FIN_MINI_APPROVED_SOURCE_SHA` as an explicit full40hex commit SHA. **Only an absent setting** defaults to legacy `eab8c96b851f039de515083189f4301cc09437c0`. Empty/whitespace, abbreviated, symbolic or malformed values reject; no failure falls back to HEAD. A valid-looking unknown object rejects. A blob/tree/tag object is not accepted as a commit.

The helper requires the approved commit to exist locally and be an ancestor of actual harness HEAD. Guarded source/runtime paths must have no staged, unstaged or nonignored untracked changes, and `git diff` against the approved commit must be empty for those paths. Test/docs-only descendants and uncommitted test/docs work are permitted. Product changes require a **new explicit approved source** matching the actual clean product, not edits to a historical hardcoded pin. Approval is a coordinator/caller input; this helper cannot independently attest human approval, compiled artifact provenance or final-candidate status.

Guarded paths:

- `backend`, `frontend/src`, `desktop`;
- `pyproject.toml`, `uv.lock`;
- `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`;
- `Dockerfile`, `compose.preview.yaml`.

Git is invoked through argument arrays with no shell interpolation; diff disables external diff helpers. No fetch, checkout, merge, source mutation or current-repository staging/commit is performed by this guard. Evidence records `approved_source_sha`, `approval_input`, `harness_head`, exact guarded paths and guard results separately. Historical `baseline`/`product_baseline` evidence fields now name the selected approved SHA. Child `CAFE_FIN_MARKET_NETWORK=0` remains explicit.

Only these delta files are owned here:

- Changed `tests/accounting/ui/desktop-mini.spec.ts`.
- New `tests/accounting/ui/mini-source-identity.cjs`, `mini-source-identity.d.cts`, `mini-source-identity.test.cjs`.
- This new delta handoff; the earlier `desktop-mini-ui.md` remains the historical eab-run evidence and native checklist. This document supersedes its fixed-eab guard description for the new harness.

No product/shared/dependency/manifest/runtime/packaging changes, migration, installer/Cargo build, source checkout, current-data operation, stage or commit. Parent-owned CSV/controller changes in the same worktree are preserved separately.

## Regression proof

**17/17 Node tests PASS — 15,691.6ms.** Each Git fixture is a fresh synthetic repository directly under OS Temp, and cleanup verifies its resolved containment/prefix first. Git commits/staging used by these tests occur **only inside those disposable fixtures**, never this source checkout.

Coverage: absent approval retains the legacy constant instead of HEAD; malformed/unknown/noncommit/nonancestor approval rejects; tests/docs-only descendants keep separate approved/harness identities; an explicitly approved different-product commit succeeds while the old source rejects; every listed runtime root input is tested both dirty and committed-different; untracked source and staged differences hidden by restoring working-file content reject. The different-source positive case is a temporary Git product fixture, not a fabricated approval of a live product change.

Strict mini-harness TypeScript **PASS**. Exact commands from repository root:

```powershell
node --test tests/accounting/ui/mini-source-identity.test.cjs
& frontend/node_modules/.bin/tsc.cmd --noEmit --strict --target ES2022 --module ESNext --moduleResolution Bundler --jsx react-jsx --esModuleInterop --skipLibCheck --types node tests/accounting/ui/desktop-mini.spec.ts tests/accounting/ui/desktop-mini.config.ts --typeRoots frontend/node_modules/@types
```

## Explicit approved-source mini UI proof

**PASS — one source mini1000 case, 24.8s (26.9s total).** Normal integrated source App/login/accounting UI, actual source Python/SQLite/files/jobs. Bootstrap-only native adapter and controlled accepted-confirm ACK drop are the same explicitly scoped mechanisms described in the earlier UI handoff. No API fake response/database, >1000 workload, native GUI, frozen artifact or installer run.

Command/environment used (choose a fresh output root when reproducing):

```powershell
$env:CAFE_FIN_MINI_APPROVED_SOURCE_SHA = 'f1bfc4f0fd12e8bd586e5ebdded6cf9e176b9913'
$env:CAFE_FIN_MINI_MANIFEST = 'C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-kit-eab8c96-20261108-001\manifest.json'
$env:CAFE_FIN_MINI_PYTHON = 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe'
$env:CAFE_FIN_MINI_OUTPUT = Join-Path $env:TEMP ('cafe-fin-desktop-mini-ui-approved-f1-' + [guid]::NewGuid().ToString('N'))
& frontend/node_modules/.bin/playwright.cmd test --config tests/accounting/ui/desktop-mini.config.ts
```

`CAFE_FIN_MINI_FORMAT` was absent, selecting the documented XLSM default. Python dependencies come from the specified existing interpreter, while the child always sets PYTHONPATH to the **new desktop worktree's backend** and disables market network explicitly. No credentials or session token appear in the command or evidence.

Actual evidence:

`C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-mini-ui-approved-f1-e8d8219c399e42b2a269a4101ab8c4e7\desktop-mini-source-deskto-9d5a4-pair-and-immutable-original\desktop-mini-evidence.json`

- Approved SHA and harness HEAD both `f1bfc4f0fd12e8bd586e5ebdded6cf9e176b9913`; input `explicit_env`. Existing commit/ancestor/equal product paths/clean product worktree checks all true.
- Worksheet2/header3/start4; bounded preview/edit/TSV copy/paste,17 expected issue coordinates, explicit duplicate keep/skip, unknown-ACK exact HTTP retry, UI resume and retained-error repair all passed.
- Resume visible totals **[0,0,0,982]**, then final **999published /1excluded /0invalid /0pending**. Actual final ledger **999total /200loaded**;19 observed staging responses all≤200items.
- Original XLSM49,567bytes SHA256 **`29b8225f8e10fc71aa72281f61bd4e522774973d8d2320169fcbdf49493a3d63`** conserved, including original download. Opaque inert VBA sentinel is not a valid-VBA/no-execution OS attestation.
- No browser page errors/nonloopback browser requests observed. Market network0 recorded; this is not a complete OS-network capture.
- `mini-ledger-published.png` opened/inspected: populated actual ledger999/200. `mini-issue-coordinates.png` and `mini-final.png` remain alongside it.
- Retained fresh synthetic data root: `C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-mini-data-TlOKdO`. Cleanup verified **0owned sidecars /0port1424listeners**.

Pending-at-cancel remained0: nonzero pending-chunk visibility/crash/lease recovery are **NOT_RUN** in this UI case. Packaged/native/clean-client and50k/500k/1m remain **NOT_RUN** by this lane; earlier evidence is not relabelled to a final candidate. Source identity selection does not remove the parent's artifact identity, final-candidate or dedicated-load-slot gates.
