# Accounting desktop delivery — mini UI evidence

## Source and ownership

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting-desktop-20261108\cafe_fin`.
Branch: `codex/cafe-fin-accounting-desktop-20261108`.
Approved/tested source: **`eab8c96b851f039de515083189f4301cc09437c0`**.
The previous accounting worktree is preserved. This lane changed only:

- `tests/accounting/ui/desktop-mini.spec.ts`;
- `tests/accounting/ui/desktop-mini.config.ts`;
- this handoff.

No product/shared/backend, schema, API, migration, lockfile, runtime, installer or Cargo changes. No stage/commit/push. Frontend dependencies were installed in the new tree with `npm ci --ignore-scripts`; the existing Python virtual environment executable supplied dependencies while `PYTHONPATH` selected **this new tree's backend source**.

## Executed source UI gate

**PASS — latest real-backend mini1000 browser case, 22.8 seconds (24.6 seconds total)**, after the reproducible product-tree guard and explicit child market-network disable were added. Strict TypeScript compilation of both new harness files **PASS**. This is integrated production-source App/registry/login/AccountingPage in Vite/Chromium, with actual Python source sidecar, auth, SQLite/file storage and job machinery. Native IPC is replaced only for `desktop_status`/`start_backend` bootstrap. Existing `serve.py` adds the exact loopback1424 origin in its test process; production origins/CSP remain untouched. No entry-module rewrite, API response mock, fake success or alternate database implementation.

The only deliberate response loss forwards the first real confirm to the server, waits for its actual HTTP200, then issues a real cancel command and drops that acknowledgement. The exact captured confirm body/key is explicitly replayed through real HTTP; the user-facing Resume action is then exercised in the UI. This is a controlled API interruption/unknown-ACK test, **not a native crash/power-loss test**. Port1424 uses strictPort and `reuseExistingServer:false`; it does not reuse another lane's listener.

Fixture supplied/verified by the file-parser lane:

- Manifest: `C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-kit-eab8c96-20261108-001\manifest.json`.
- Manifest SHA256: `b98b754acac49448739f4e48f4edc61f618e39623530748eff8cdfa90787adf4`.
- Exercised source: `desktop-source.xlsm`, **49,567 bytes**; original SHA256 **`29b8225f8e10fc71aa72281f61bd4e522774973d8d2320169fcbdf49493a3d63`**.
- XLSM contains an **opaque inert `xl/vbaProject.bin` sentinel**, explicitly not a valid VBA project. Its original bytes survive; this is not proof of valid executable-VBA compatibility or macro execution. Unsupported/external formulas are retained as errors, not executed or replaced by their misleading cached values.
- Eight stable columns: code/day/amount/quantity/category/note/currency/reference, mapping A:H. Worksheet1 is instructions; selected worksheet2 is **Sổ cà phê**, header3, data starts4. Exactly1,000 source rows. Money remains exact strings.

| Step actually checked | Result |
| --- | --- |
| Upload worksheet1, then choose worksheet2/header3/start4 and map A:H in UI | Reparse gives1,000 staging rows; each preview response at most200 |
| Inline edit source row6 amount, copy a three-cell TSV range, paste amount via preview/confirmed draft save | Backend versioned patches confirm123.45 then124.45; leading-zero code/copy text preserved |
| Whole-job validation and issue dialog | 983valid,17invalid,20duplicate-warning rows; all expected issue source coordinates/codes match, including2!C28 unsupported and2!C78 external formula |
| Duplicate review | Explicit keep source4 / skip source5, then keep remaining undecided warnings; skip survives the default decision |
| Accepted confirm / dropped ACK / actual cancel / exact HTTP replay | Cancelled, published0, book0; exact replay does not add a second selection/publication |
| UI Resume and published visibility | Latest book totals observed **[0,0,982]**, never an intermediate count;982first publication,17errors retained |
| Close/reopen durable job; filter invalid; apply17 fixture repairs through bounded clipboard preview/save |17×8=136cells, below500-cell limit; validate invalid0; next confirmation publishes only remaining17 |
| Final reconciliation | **999published,1excluded,0invalid,0pending**; imported staging999; excluded source5 remains unimported |
| Final visible ledger | **999total /200loaded** after closing modal and refreshing the actual page |
| Original download and source file recheck | Download SHA matches original; source hash and mtime unchanged |

There were18 observed staging responses in the latest rerun, all HTTP200 and at most200items. No browser page errors or non-loopback browser requests were observed. This does not measure every backend OS network event. Counts are overlapping flags: after repairs valid1000 includes the explicitly excluded row; do not add valid/duplicate/excluded as disjoint populations. Source row6 was deliberately changed to124.45, so the fixture's untouched-source money totals are not asserted as totals for this edited scenario.

At controlled cancellation **staged_committed_rows=0**. Therefore **nonzero pending-chunk visibility, mid-chunk crash, process restart and lease recovery are NOT RUN in this UI case**. The observed0→982 publication is evidence for this run only. Parent-owned controller/native tests own stronger interruption probes. No50k/500k/1m benchmark, installer build or native GUI run was started by this lane.

## Evidence and reproduction

Final evidence directory:

`C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-mini-ui-repro-61f8dd0440bb4e339a97d9f4f0a80518\desktop-mini-source-deskto-9d5a4-pair-and-immutable-original`

- `desktop-mini-evidence.json`: counts, accepted/lost ACK, source conservation, bounded responses and explicit scope limits.
- `mini-issue-coordinates.png`: source error dialog.
- `mini-final.png`: durable job completed999/excluded1/invalid0.
- `mini-ledger-published.png`: actual ledger999total/200loaded.

Screenshots from the successful source runs were opened and inspected, including the latest rerun ledger999/200; the ledger is populated, error coordinates are visible and no blank/error overlay was substituted. Latest synthetic root retained for parent inspection: `C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-mini-data-ZeWRC6`. Credentials/tokens are not written into evidence; trace is off. A prior harness-only FAIL (relative locator incorrectly retained its outer grid scope) is preserved separately at `cafe-fin-desktop-mini-ui-1794110518035` under Temp, original hash conserved. Earlier full-flow PASS26.1s remains at `cafe-fin-desktop-mini-ui-final-b1888c9150854ea885fa12bc0de54194`; the22.8s rerun is the final guard/network proof. It records harness HEAD and product baseline both `eab8c96b851f039de515083189f4301cc09437c0`, all three product guard results true, and market_network='0'. Tests/docs descendant commits are permitted by the guard; this rerun did not create a commit to simulate one. Cleanup confirmed0owned sidecars and0port1424listeners.

Run from this worktree, with an existing environment providing the pinned Python dependencies:

Exact strict TypeScript command used for the recorded PASS (PowerShell, from the repository root):

```powershell
& frontend/node_modules/.bin/tsc.cmd --noEmit --strict --target ES2022 --module ESNext --moduleResolution Bundler --jsx react-jsx --esModuleInterop --skipLibCheck --types node tests/accounting/ui/desktop-mini.spec.ts tests/accounting/ui/desktop-mini.config.ts --typeRoots frontend/node_modules/@types
```

Mini UI run:

```powershell
$env:CAFE_FIN_MINI_MANIFEST = 'C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-kit-eab8c96-20261108-001\manifest.json'
$env:CAFE_FIN_MINI_PYTHON = 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe'
$env:CAFE_FIN_MINI_FORMAT = 'xlsm' # xlsx is also accepted; only xlsm was executed here
$env:CAFE_FIN_MINI_OUTPUT = Join-Path $env:TEMP ('cafe-fin-desktop-mini-ui-' + [guid]::NewGuid().ToString('N'))
frontend/node_modules/.bin/playwright.cmd test --config tests/accounting/ui/desktop-mini.config.ts
```

The test records **harness HEAD separately from product baseline**. Tests/docs-only commits may follow the approved baseline: the guard requires `eab8c96b851f039de515083189f4301cc09437c0` to be an ancestor, zero `git diff` from it under `backend`, `frontend/src`, `desktop`, and no staged/unstaged/untracked changes in those same product paths. Git runs through argument arrays, not shell-built commands. Thus the tested product paths remain exactly the approved baseline while harness/docs can be committed independently. The child explicitly receives `CAFE_FIN_MARKET_NETWORK=0`, so this mini source check does not implicitly enable live market scheduling on the shared host. For a fresh kit, the file-parser generator entry is `tests/accounting/desktop_delivery/fixtures.py --root <fresh external directory> --rows 1000`; fixture generation does not install or launch a native app. Never point this source harness at operational data or use it as a packaged/native command.

## Parent-owned headless controller entry

The controller entry is now `tests.accounting.desktop_delivery.runner`. Its default workload is `desktop-mini-xlsm-1000`. The source equivalent is:

```text
python -m tests.accounting.desktop_delivery.runner --mode source --output-root <fresh-external>
```

After parent/05 supplies an approved external candidate manifest and its exact40-hex source SHA, the frozen-sidecar mini entry is:

```text
python -m tests.accounting.desktop_delivery.runner --mode frozen-sidecar --workload desktop-mini-xlsm-1000 --candidate-manifest <external05.json> --expected-source-sha <40hex> --output-root <fresh-external>
```

Use a fresh external output directory and the actual approved05 manifest; do not substitute an arbitrary executable/artifact. These are **headless source/frozen-sidecar controller checks**, not native GUI/installer/WebView2/OS-clipboard acceptance. Their evidence belongs in the separate controller ledger maintained by parent. This documentation update did not execute either command or start a large workload. The source browser result above and the native GUI checklist below keep their own statuses.

## Packaged GUI entry and checklist — NOT RUN

No approved artifact05 manifest/executable was supplied to this lane for native GUI acceptance. **Native packaged GUI, native OS clipboard/save dialogs, installer, WebView2, offline clean-client, tray/startup and application exit/restart remain NOT_RUN.** Source/browser or headless controller PASS is not carried forward to those gates.

When parent/05 supplies the final artifact, the native GUI entry is the **verified installed shortcut or executable named by that exact05 manifest**, under the parent's approved native GUI acceptance procedure. The headless frozen-sidecar command above does not open or drive that native window. Record the actual executable/sidecar SHA256, artifact source SHA, manifest SHA, app version and Windows/WebView2 versions before launch. Do not use the source Vite command, substitute a development executable, infer success from NSIS build or invent a GUI runner command. This lane can apply the following UI sequence once the real artifact/entry is provided:

1. Verify source/artifact identity with parent; install/launch the provided artifact, without opening Vite, Docker, terminal services or external Office. Select a **fresh synthetic** GUI data root and authenticate normally. Keep operational roots, old CRM, startup configuration and external Telegram destinations untouched.
2. Open **Sổ kế toán** → the fixture book → **Nhập Excel / CSV · mở job đã lưu**. Use the same verified kit/hash and the schema/mapping from its manifest; worksheet2/header3/start4. Confirm bounded preview and actual leading-zero/date/text rendering in the native window.
3. Exercise native edit/copy/clipboard paste with preview and confirmed save; preserve the same controlled row6 amount override. Review coordinates2!C28 /2!C78,17invalid and duplicate candidates. Keep4, skip5, keep other undecided warnings; verify book remains unpublished before confirmation.
4. Confirm valid only; verify982published and17retained errors in the native GUI. Close/reopen the modal; repair the17 known invalid rows with the verified repair fixture, revalidate and confirm; final999/excluded1 with stable lineage and original downloaded hash unchanged.
5. For native unknown-ACK, nonzero pending, cancellation/crash/restart/resume: use only the parent's source-matched packaged controller/fault mechanism and record actual phase/checkpoint before interruption. If that mechanism or checkpoint is unavailable, retain the affected subcase as **NOT RUN**; do not label the source API interruption as a native crash proof.
6. Capture native-window screenshots before/after publication, original download bytes/hash and persisted counts. Native OS clipboard/file dialogs must be exercised without source bootstrap substitution. Quit through the actual app's approved Exit action and verify owned sidecar stops; reopen from the same installed shortcut and inspect the durable job/data again. Packaging/foundation own tray/startup/single-instance acceptance.

Gate ledger must keep source UI, frozen/controller API, packaged native GUI and clean-PC acceptance as separate statuses with their own artifact/source hashes. High-load packaged runs remain blocked until final candidate and parent grants the dedicated load slot.
