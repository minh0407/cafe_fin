# Accounting workloads for the packaged desktop candidate

Definitions only (manifest revision `2026-11-08.3`). **No source workload, frozen sidecar, native GUI, installer or large benchmark was run by this subtask for this handoff.** Parent-runner evidence, if produced separately, is not overwritten by these definition statuses. The machine-readable plan is [workloads.json](../../../tests/accounting/desktop_delivery/workloads.json); every execution/evidence status starts at `NOT_RUN`. Manifest validation is not execution evidence.

Planning worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting-desktop-20261108\cafe_fin`, branch `codex/cafe-fin-accounting-desktop-20261108`, baseline `eab8c96b851f039de515083189f4301cc09437c0`. Its ancestor `828d575b4a3c7b18ffafd8e2665a9d79b54ea403` is the business candidate in prompt 06. This planning SHA is **not** a claim that a final installer/sidecar has been built. Use the coordinator's later designated source and source-matched artifact. The old worktree and all old CSV results remain untouched.

## Workloads and the two different minis

| ID | Input / intended evidence | Invalid / duplicate flags | Decisions | First / second / final published |
| --- | --- | --- | --- | --- |
| `csv-mini-1000` | CSV v1, mini frozen-sidecar/API preparation | 1 amount / 2 flags from 1 exact pair | Keep all; exclude none; business key `code` | 999 / 1 / 1,000 |
| `csv-checkpoint-5000` | Explicitly authorized bounded CSV checkpoint test, source or approved frozen sidecar | 5 amount / 10 flags from 5 exact pairs | Same CSV policy | 4,995 / 5 / 5,000 |
| `csv-50k` | Future CSV v1 packaged workload | 50 amount / 100 flags from 50 pairs | Same CSV policy | 49,950 / 50 / 50,000 |
| `csv-500k` | Future CSV v1 packaged workload | 500 amount / 1,000 flags from 500 pairs | Same CSV policy | 499,500 / 500 / 500,000 |
| `csv-1m` | Future CSV v1 packaged workload | 1,000 amount / 2,000 flags from 1,000 pairs | Same CSV policy | 999,000 / 1,000 / 1,000,000 |
| `desktop-mini-xlsm-1000` | Rich genuine inert XLSM, frozen-sidecar/API | 17 = 10 amount + 5 date + 2 formula; 20 flags from 10 pairs | **No business key**; skip source row 5; keep duplicate warnings | 982 / 17 / 999 |
| `desktop-mini-xlsx-1000` | Separately hashed rich XLSX, real native GUI | Same rich fixture expectations | Same rich policy | 982 / 17 / 999 |

All inputs have eight columns and one header. CSV v1 header is row1/data starts row2. Rich XLSX/XLSM explicitly selects sheet2 `Sổ cà phê`, with two preamble rows, header row3 and data rows4..1003; its header is not row1. Data-cell counts are 8,000 / 40,000 / 400,000 / 4,000,000 / 8,000,000 for CSV 1k / bounded 5k / 50k / 500k / 1m, excluding eight header cells. The named 5k test has 5,001 CSV records including the header; expected export is 5,000 × 8 = 40,000 data cells. Rich mini has 8,000 input data cells and 7,992 exported data cells after the one exclusion. Duplicate flags overlap valid rows and must not be added as a disjoint count. A rich formula error is not silently converted into zero.

The rich mini is owned by the fixture subtask (`tests/accounting/desktop_delivery/fixtures.py`). Its separate generated fixture manifest supplies schema/mapping, source coordinates, repairs, raw-file hashes and **exact first/final sums**. The workload plan deliberately leaves those rich sums null. The runner must resolve them from that manifest or return `BLOCKED`; it must not substitute the CSV totals below. Rich row 5 remains excluded in both attempts. The valid-before-decision count is 983, so skipping one valid row gives 982 first-published rows; repairing the 17 invalid rows gives final 999. Actual exclusions/overlapping warning locations must agree with the rich fixture manifest.

The actual rich manifest schema is `kit_version=accounting-desktop-fixtures-v1`; read `/book`, `/files/xlsm` for API or `/files/xlsx` for GUI, and that file's `/scenarios/skip_first_duplicate/first_income` and `/final_income` for exact VND strings. Repairs come from the separately hashed `repair_jsonl`. Its macro-enabled OOXML container holds an **opaque inert `vbaProject.bin` sentinel, not a valid VBA project** (`valid_vba_project=false`, `execution_claim=false`). Do not turn sentinel preservation into proof of executing or validating genuine VBA. The source row5 exclusion removes the second record of the first exact duplicate pair.

## CSV v1: reference recipe and exact arithmetic

The reference is `record_for`, `cents_for`, `amount_for`, `generate` in [the existing source benchmark](../../../tests/accounting/benchmark.py) at planning baseline eab8c96. Git-blob SHA-256 is `9239f0a253dc2d76fcbceba926fdf227b0352074ecfc706d2a9fa6cc58f1a0d4`; Windows checkout SHA was `107bdcf43396b2d2f26bd9944ecbf760a2153aa9d69763713080ee0895edd19e`. The source texts match after CRLF normalization. Raw fixture/artifact hashes must never be normalized this way.

The parent owns a pure generator for future packaged runs. This reference does not authorize running the old in-process benchmark and calling its result packaged/native. Record the actual generator implementation/source hash, algorithm ID `accounting.csv.v1` and generated fixture manifest hash. Claim identical CSV bytes only when BOM, CRLF, header, column order, quoting and all field rules match.

For data ordinal `i=1..N`, source row is `i+1`; `original=i-1` when `i mod1000=2`, otherwise `original=i`. Fields are a 12-digit zero-padded code; ISO `2026-01-01 + original mod28 days`; money cents `10000 + original mod100000`; quantity milliunits `1000 + original mod1000`; Robusta for odd original/Arabica otherwise; the exact Vietnamese/literal-prefix note in the manifest; VND; LOCAL-01. At every `i mod1000=0`, amount is `INVALID_AMOUNT`. Records 2,1002,... exactly repeat the previous valid row across all eight fields. Repair amount from the original source ordinal; keep all exact pairs as intentional new records.

| CSV size | First income cents | Final income cents | First / final VND |
| --- | ---: | ---: | --- |
| 1,000 | `10489499` | `10500499` | `104894.99` / `105004.99` |
| 5,000 (bounded checkpoint) | `62437495` | `62502495` | `624374.95` / `625024.95` |
| 50,000 | `1748249950` | `1750024950` | `17482499.50` / `17500249.50` |
| 500,000 | `29969999500` | `29999749500` | `299699995.00` / `299997495.00` |
| 1,000,000 | `59939999000` | `59999499000` | `599399990.00` / `599994990.00` |

These are integer/Decimal **expected values**, not observed app results. For these N (multiples of 1000), with `(q,r)=divmod(N,100000)`, final cents = `10000*N + q*4999950000 + r*(r+1)//2 - N//1000`. If `(a,b)=divmod(N//1000,100)`, invalid-row cents = `10000*(N//1000) + a*4950000 + 1000*b*(b+1)//2`; subtract them for first cents. The independent 1,000-row in-memory sum is 10,500,499 cents; invalid row 1000 contributes 11,000 cents. The independent 5,000-row in-memory sum is 62,502,495 cents; its five invalid rows contribute 65,000 cents, leaving 62,437,495 first-publication cents. No large dataset, CSV file or Runtime is needed to validate this arithmetic.

## Identity, mini authorization and large-run CoordinatorSlot

Source developer minis are already explicitly authorized; there is no added formal CoordinatorSlot requirement for them. A frozen mini requires the coordinator-approved candidate/source identity and matching retained bytes. Its slot is optional unless the coordinator requests one; any supplied receipt must validate. A coordinator may designate a nonfinal candidate for a mini, which stays labelled nonfinal. The coordinator has separately authorized **only the named bounded `csv-checkpoint-5000` test**, in source or approved frozen-sidecar mode, to make an actual partial cancel checkpoint observable. It has no formal large-run slot requirement unless requested; this exception does not authorize arbitrary larger cases or 50k/500k/1m.

**Large workloads (50k/500k/1m; runner threshold 50,000 rows) require a recorded CoordinatorSlot** plus the **final** candidate and explicit 50k/500k/1m authorization. The receipt binds approved source, workload IDs, evidence modes, grant/expiry times and declared scope. Selecting a large workload in JSON is not permission to start it. The current CLI validates candidate identity and slot before creating output or fixtures, and rejects source-mode large runs. It does not infer or independently attest final-candidate designation: that remains an explicit coordinator approval for the bound source/artifact.

Do not overlap an installer/cargo build or another large benchmark in the granted scope. A slot is scheduling evidence, not proof of an exclusive host. Record actual root/other-chat/backend/browser load, CPU/I/O affinity and cache state; unknown/not controlled stays explicit. Old source/browser observations are neither quiet-host estimates nor native measurements for the new artifact. No speed promise is derived from the expected math.

Treat these evidence dimensions independently:

| Dimension | What can establish it | What it cannot establish |
| --- | --- | --- |
| Source | Exact source identity plus actual source test/workload evidence | Frozen bytes, a native window or installed/offline behavior |
| Frozen sidecar | Actual source-bound frozen image, correct image/PID, private launch and real loopback operations | Native GUI controls or clean-client installation |
| GUI native | Actual packaged app/native window/WebView, observed controls and its real source-bound child | A clean Windows machine unless separately observed |
| Clean Windows client | Actual installer/first launch/offline observations with recorded machine/runtime baseline | Inferred PASS from NSIS SUCCESS or a developer machine |

Record identity checks, behavior/assertion results and measurement availability separately. A sidecar's file hash alone is not GUI identity PASS. Unrequested modes remain `NOT_RUN`; missing measurements remain null/`NOT_MEASURED`, not zero. Overall PASS for a requested scope requires its identity gates and mandatory assertions. No artifact/fixture hash may be invented from an old source run.

## Proposed external interface to lane05 — document only

This is a **proposal**, not an added shared API, packaging schema or controller hook. Parent/coordinator approval and lane05's actual manifest format remain authoritative. The minimal candidate identity file passed to the parent runner is:

```json
{
  "source_sha": "<full coordinator-approved 40-hex commit>",
  "sidecar": {
    "path": "<absolute existing source-bound frozen exe>",
    "sha256": "<64-hex raw file SHA-256>",
    "bytes": "<positive integer, serialized as a JSON integer>"
  },
  "app": null
}
```

`app`, when supplied, has the same `path`/`sha256`/integer-`bytes` shape and is mandatory for GUI evidence. Angle-bracket values above are placeholders and **cannot pass** validation. The file itself is outside Git and pinned by SHA in the result. `source_sha` must equal the coordinator's expected candidate, not an assumed planning SHA or version 0.1.0. The trusted lane05 tuple binds a build's declared source to the frozen bytes; the current ready handshake cannot independently prove compiled source. Missing build/source attestation is not cured by changing a filename or editing a receipt.

Validate existing local file paths, positive byte counts and raw SHA-256 before launch and after owned-process exit. Record actual process image paths/hash, creation time and parent relationship; an installed sidecar may have the normal packaged name, but its bytes must match the bound sidecar receipt. A stale binary at the right path or the same version string is insufficient. Replaced/missing files, source mismatch or a Python fallback stop the affected mode.

Fixture identity is **independent** of this candidate file. The parent runner resolves/generates CSV v1 or obtains the rich fixture manifest separately, pins that manifest's SHA and every chosen raw input's SHA/bytes, and binds them together with the workload-manifest SHA in the result. Lane05 need not map the bulk CSV input path. Rich XLSX/XLSM variants have separate identities and are not extension renames. Unknown rich-manifest versions/missing exact expectations require an explicit adapter or BLOCKED, not guessed JSON pointers or CSV sums.

Current runner-local codes include `COORDINATOR_LARGE_SLOT_REQUIRED`, `COORDINATOR_SLOT_INVALID`, `LARGE_PACKAGED_CANDIDATE_REQUIRED`, `PACKAGED_IDENTITY_REQUIRED`, `ARTIFACT_SOURCE_MISMATCH`, `ARTIFACT_HASH_MISMATCH`, `PACKAGED_PROCESS_IMAGE_MISMATCH`, `PACKAGED_PYTHON_FALLBACK_DENIED`, `FRESH_OUTPUT_ROOT_REQUIRED` and `CHECKPOINT_WINDOW_MISSED`. GUI/fixture-adapter reason codes would be future interface proposals, not implemented shared API errors. None changes the core API error contract. On Defender/AppControl/policy rejection, retain BLOCKED/error evidence; do not disable policy, add exclusions, rename/copy binaries to evade it, or manufacture a signer.

## Existing hooks and limits found at eab8c96

- [build-sidecar.ps1](../../../desktop/scripts/build-sidecar.ps1) builds the PyInstaller executable named `cafe-fin-sidecar-x86_64-pc-windows-msvc.exe` and writes `desktop/notices/sidecar-native-inventory.json` containing `exe_sha256`, `exe_bytes` and native-file hashes. **That inventory does not contain source_sha or a full app/installer candidate binding.** Lane05 still needs an external source-bound candidate identity file. This script also performs build/notices work and was not executed here.
- [sidecar.spec](../../../desktop/sidecar.spec) is a one-file EXE with `console=True`, no arbitrary benchmark entry point and `runtime_tmpdir=None`. The native parent hides its console. Track a separate bootloader/serving child if observed; do not assume the first PID is the API process or that OS-temp extraction bytes were sampled.
- [native_controller.rs](../../../desktop/src/native_controller.rs) resolves `cafe-fin-sidecar.exe` beside the app in production. Debug builds can try the worktree frozen binary and then `.venv` Python. Frozen evidence must reject that interpreted fallback by inspecting the actual image; it must not rely solely on resolver intent.
- [the sidecar entry point](../../../backend/cafe_fin/__main__.py) rejects extra CLI arguments (`BOOT_ARGUMENTS_DENIED`). It accepts a bounded private stdio BootRequest (protocol 1, optional maintenance 1), binds authenticated loopback on an ephemeral port and returns a ready frame. Native startup validates generation/state/protocol and loopback shape. **Ready/health do not include a source SHA.** Boot/auth frames contain authority and must stay in memory/private pipe.
- [production_controller.rs](../../../tests/desktop/production_controller.rs) explicitly exercises the actual controller/frozen-sidecar adapter **headlessly**, without a Tauri window. Such a result belongs to frozen/controller evidence, never GUI-native or clean-client PASS.
- [tauri.conf.json](../../../desktop/tauri.conf.json) specifies NSIS/currentUser, bundled sidecar, frontendDist and WebView2 offlineInstaller. That is build configuration, not proof of an offline first installation, tray behavior or a retained final artifact. Historical candidate09 hashes in [the clean-client kit](../../release/CLEAN_WINDOWS_TEST_KIT.md) are not downloadable retained files or hashes for the new candidate.

Do not add a secret controller store or a generic get-token endpoint. No BootSession, app-session/login token, password, Authorization header, private frame, journal or secret-derived fingerprint belongs in fixture/workload/artifact manifests, result JSON, screenshots, argv, environment dumps or logs. A headless launcher may own credentials only in process memory/private stdio. GUI tests must use actual UI actions or an owner-approved nonsecret hook; they cannot steal/replay the app's private session or inject a browser Tauri mock. This lane does not implement a new 00/05 hook.

## Checkpoint and publication observations

CSV v1 targets the first observed durable chunk at `500 <= parsed < source_rows`, with the public job counter equal to its checkpoint counter. The current controller calls the existing public **cancel API before closing the process**, then waits for cooperative `CANCELLED`. Cancellation is not instantaneous: the stopped count may be greater than the observed count, but must still be strictly below the full input. A `500` pre-cancel observation followed by `CANCELLED` at all 1,000 rows remains `WINDOW_MISSED`, not a checkpoint PASS. The parent reported exactly that 1k race; this handoff adds no execution result or artifact for it. The explicitly approved `csv-checkpoint-5000` is a separate bounded attempt, not permission for a large benchmark.

For a stopped partial checkpoint, verify owned-sidecar graceful exit and closed/empty WAL first. Only then open **this run's synthetic DB** read-only/immutable. Require persisted job state `CANCELLED`, `500 <= parsed < source_rows`, staged count = distinct staged source IDs = parsed job counter = persisted checkpoint, and matching `parse:{parsed}` receipt/result. Hash the ordered `row_id`, source sheet, source row and raw JSON prefix. This is a bounded synthetic diagnostic after closure, not a live DB/WAL copy or an unrestricted receipt inventory.

Restart must keep the same batch/job/book/file/file hash and **the same `CANCELLED` partial counter**. Then invoke the existing explicit resume API and complete parsing/validation/two publications/export. Resume must complete the same parse-job ID, full input-row checkpoint and exactly one job-generation increment. Final closed-DB reconciliation verifies all input rows have distinct staged IDs, the checkpoint prefix SHA and receipt payload hash remain unchanged, and published = lineage = distinct targets with two PUBLISHED attempts. Record old exit/new process creation identity and the hashes binding this run. This proves cooperative cancel/persist/restart/resume in the requested scope; it is **not a `RECOVERABLE`, hard-kill, crash or power-loss claim**. An older graceful-restart fallback/older result is historical evidence under its original code/hash and must not be relabelled as this new protocol.

Rich mini still requires **restart after completed first validation and before decisions**, retaining the expected 1,000 staged rows/17 errors and zero published rows. Its mid-parse observation is optional and stays NOT_RUN unless captured separately; the completed-phase restart does not prove partial-parse resume. Only supported lifecycle for owned app/sidecar is allowed. Closing a window to tray is not process exit. No parser monkeypatch, frozen-code injection or new production checkpoint endpoint is part of this test.

If the cancel races with completion or stops at all rows, retain the actual events and `WINDOW_MISSED`; the current required-checkpoint scope remains overall `BLOCKED` even if later functional checks pass. A later reopen cannot repair that missing observation. Pending visibility windows stay separate: if too fast/unobserved, mark `NOT_MEASURED`; final counts do not prove every intermediate window. Conditional total receipt counts in this plan remain expected values under 500-row/byte caps. The implemented stopped-parse receipt check does not measure every parse/normalize/dedup/snapshot/pending/seal receipt count. Broader receipt diagnostics/dbstat remain NOT_MEASURED unless actually recorded.

Repair uses at most 500 rows/patch request. Confirm 1 pins the validated revision/decisions; repair/revalidate/confirm 2 imports only remaining rows, keeps exclusions and preserves earlier lineage/targets. List/report/export must use published data. Original download SHA must match upload after preview, repair, import and derived export. Export records its own new hash and scope; it does not claim workbook macro/style/pivot fidelity. Inert macro presence plus unchanged bytes alone does not prove no execution: preserve the refused unsupported/external formula observations and actual process/network scope where observable, without executing macro content as a test.

## Measurement and result contract

Use Windows monotonic high-resolution time for every phase; retain clock implementation/resolution. The current measurement helper defaults to 500 ms resource sampling and normal 100 ms job polling; the cooperative parse-checkpoint probe polls at 10 ms and records its actual interval; record the actual intervals and any faster sampling overhead. The implemented Windows snapshot records PID, parent PID, executable/image path, creation `FILETIME` in 100 ns ticks, combined CPU, RSS/private and OS peak RSS. Summary identity is `(pid, creation_filetime_100ns)`; this separates reused PIDs when creation time is captured. If the Win32 call cannot supply creation time, identity is incomplete and must remain explicitly unverified. **Process architecture is `NOT_MEASURED`.** The sampler does not hash/classify every descendant image; detailed bootloader/API/Tauri/WebView2 roles and descendant hashes remain planned unless separately observed. Root frozen artifact/image verification is separate from these sampling fields. Unavailable identity observations must remain explicit, not fabricated from a filename or PID alone.

CPU: the current helper combines GetProcessTimes user+kernel seconds since process creation, then emits each unique PID+creation-time's **last sampled minus first sampled CPU delta**. This excludes unsampled startup/exit time. Separate user/kernel results, per-phase CPU deltas and percent are **NOT_MEASURED** unless explicitly derived with a stated method; tagged resource samples alone are not those calculations. If percent is later emitted, state whether 100% means one logical CPU or the full machine. Parser/API/worker commonly share one sidecar PID; do not count that CPU three times. Memory: GetProcessMemoryInfo sampled WorkingSetSize/PrivateUsage peaks per unique process; OS PeakWorkingSetSize is cumulative since process start, including startup. **Do not sum role RSS, or sum app/WebView RSS into unique physical memory.** Shared pages make such a total misleading. In this headless runner, GUI memory/latency is **NOT_MEASURED** and GUI execution evidence is separately **NOT_RUN**.

Disk implementation samples DB/WAL/SHM, synthetic data-root total bytes, files beneath `imports`, sampled peaks and free volume before/after. The `app_import_temp_bytes` field counts every file under an `imports` path; it is not a measurement isolating only transient temp. Original/export hashes and downloaded byte counts are separate evidence; these sizes can overlap app-data totals and must not be added as disjoint disk usage. Fixtures/controller output outside the data root are not included by that sampler. Table pages/dbstat and richer disjoint disk accounting remain **NOT_MEASURED** unless separately recorded. App-root sampling does not cover all PyInstaller/SQLite OS-temp paths: OS-temp stays **NOT_MEASURED** unless owned paths/method were actually recorded. No global temp/secret scan or copy of a live SQLite DB/WAL is authorized by this plan.

The implemented HTTP helper groups request labels into count, p50, p95 and max. Job-status, ledger/staging preview and bulk **whole-dataset filter/page**/separate-book foreground edits use direct API calls. Exact label names remain in results, for example `foreground_whole_book_filter`; they do not imply GUI interaction or every planned preview/jump operation. Explicit timeout/failure aggregate counters are **NOT_MEASURED** in the current summary, although operation failures fail the run with their reason code. Actual native GUI action latency is **NOT_MEASURED** here. Preserve phase/publication context from observations alongside latency groups. The current helper uses linear interpolation at zero-based rank `(n-1)*p` (p=.5/.95); record that definition, do not relabel it as nearest-rank p95. For n=0 keep null/NOT_MEASURED. Mixed pending/published observations are not a steady-state fully published dataset benchmark. Keep direct API, browser source harness and actual native GUI latency separate.

Result receipt should bind workload ID/schema/revision/SHA, scenario, candidate source and external identity-manifest SHA, sidecar/app identities, fixture-manifest/input/output hashes, CoordinatorSlot receipt when large or otherwise requested/supplied, observed machine/runtime versions, process-role records, phase/count/checkpoint events, exact sums, measurement availability and host interference. Include source/frozen-sidecar/GUI/clean-client statuses separately. Preserve a FAIL/BLOCKED/INTERRUPTED artifact; retries get fresh run IDs/roots and never overwrite it. No secrets or old source timing copied as native measurements.

## Current runner coverage and commands (not executed here)

The runner currently supports `--mode source|frozen-sidecar` and six IDs: rich XLSM mini plus CSV 1k, named bounded 5k, 50k, 500k and 1m. The JSON has seven IDs because it additionally defines the separate native XLSX scenario. `desktop-mini-xlsx-1000` is a separate future/actual-native UI scenario; passing it to this CLI is not supported. The CLI hashes `workloads.json` into the result; it does **not** interpret every assertion/metric defined in this plan. Its static workload choices, fixture definitions and acceptance implementation drive execution. Result harness-file hashes identify the code actually run while these parallel files are being finalized.

Implemented assertions cover two partial publications, exact fixture-supplied sums, retained exclusions/errors, original download/source SHA, bounded pages/patches, owned graceful restart, and closed-DB published/lineage/distinct-target reconciliation with two PUBLISHED attempts. Rich mini specifically restarts after completed first validation. CSV uses the cooperative-cancel, closed-checkpoint and explicit-resume guards above. Source and frozen executions each need their own result/identity; one does not prove the other. Derived CSV download is streamed with a bounded 256 KiB line limit: raw bytes/SHA, exact header, record width, data-row/cell counts and Decimal income are reconciled against fixture expectations. This checks the synthetic derived CSV, not original-workbook fidelity. Full-phase receipt inventories, hard-crash tests, full GUI/process-role accounting, clean installation, clock/host inventory beyond actual emitted fields and every proposed phase-specific metric are not implied by an overall functional PASS.

Run the following **only from the desktop worktree root**. These are documented commands, not execution performed by this subtask. The controller needs a Python environment with the backend dependencies; its use does not make that environment a Cafe Fin product prerequisite. Source mode records current Git HEAD and rejects dirty product paths (`backend`, `frontend/src`, `desktop`). Fresh external output roots are mandatory; reuse is rejected. No credential is placed on the command line.

Authorized source rich mini, with no invented slot requirement:

```powershell
$controllerPython = 'C:/Users/NC/AppData/Local/Temp/cafe-fin-foundation-tools/python/cpython-3.12.16-windows-x86_64-none/python.exe'
$miniOutput = Join-Path ([IO.Path]::GetTempPath()) ('cafe-fin-source-rich-mini-' + [guid]::NewGuid().ToString('N'))
& $controllerPython -B -m tests.accounting.desktop_delivery.runner --mode source --workload desktop-mini-xlsm-1000 --output-root $miniOutput
```

Frozen large template: set real coordinator-approved values in these environment variables **before** invoking it. The manifest supplies a source-bound existing `.exe`; the current trusted provenance is the coordinator's declaration plus digest, not a compiled-SHA attestation. A final designation and real unexpired slot must cover the chosen workload/mode/source. Empty values fail here; the runner independently validates hashes/receipt before output creation. No slot is generated or inferred by this template.

```powershell
$controllerPython = 'C:/Users/NC/AppData/Local/Temp/cafe-fin-foundation-tools/python/cpython-3.12.16-windows-x86_64-none/python.exe'
$candidateIdentity = $env:CAFE_FIN_CANDIDATE_MANIFEST
$approvedSource = $env:CAFE_FIN_EXPECTED_SOURCE_SHA
$largeSlot = $env:CAFE_FIN_LARGE_SLOT_RECEIPT
if ([string]::IsNullOrWhiteSpace($candidateIdentity) -or [string]::IsNullOrWhiteSpace($approvedSource) -or [string]::IsNullOrWhiteSpace($largeSlot)) { throw 'Supply actual coordinator-approved candidate identity/source and large-slot receipt.' }
$largeOutput = Join-Path ([IO.Path]::GetTempPath()) ('cafe-fin-frozen-csv-50k-' + [guid]::NewGuid().ToString('N'))
& $controllerPython -B -m tests.accounting.desktop_delivery.runner --mode frozen-sidecar --workload csv-50k --candidate-manifest $candidateIdentity --expected-source-sha $approvedSource --slot-receipt $largeSlot --output-root $largeOutput
```

The named bounded source checkpoint command is the source example above with `--workload csv-checkpoint-5000` and a new unique external output root. Frozen bounded scope uses that ID with actual `--candidate-manifest` and `--expected-source-sha`, without `--slot-receipt` unless requested. Both scopes stay NOT_RUN in this plan; no command here was executed. A missed 1k window is not rewritten by a later 5k result.

For separately authorized `csv-500k` / `csv-1m`, select that ID, obtain a receipt that covers it, and create another fresh output root; do not launch the three workloads in parallel. Frozen mini uses the same candidate/source flags with `--workload desktop-mini-xlsm-1000`; omit `--slot-receipt` unless requested, and label any approved nonfinal candidate explicitly. This template does not run a build, alter policy or provide native GUI evidence.

## Handoff and verification

Owned files are only `tests/accounting/desktop_delivery/workloads.json` and this document. No migration, dependency, shared desktop/protocol/packaging code or old worktree was changed. No stage/commit/push was performed. Native hook/candidate-manifest proposals above remain coordination work.

Definition checks: JSON parse, unique workload IDs, mini/large slot-policy and CLI-support consistency, evidence/status fields, exact integer-cent formulas and independent in-memory 1,000/5,000-row arithmetic comparisons. Read-only runner/acceptance/measurement reconciliation checks current CLI support and explicit missing-metric limitations. Those checks use no Runtime, sidecar, GUI or generated fixture. All workload execution statuses remain NOT_RUN in this definition manifest, including the new bounded test; 50k/500k/1m are future gated definitions. Actual fixtures/mini results are supplied by the fixture and parent-runner owners and must be hash-bound separately before execution.

## Delta after f1bfc4f

This revision adds only the versioned `csv-checkpoint-5000` definition and the current public-cancel/closed-proof/resume contract. It reuses exact CSV v1 bytes/semantics/business key `code`; five invalid rows (0.1%) and five extra exact duplicates (0.1%, ten warning rows) overlap valid rows as before. Expected first/final money is `624374.95` / `625024.95` VND, with first 4,995 then five remaining records, no exclusions and final lineage/distinct targets 5,000. These are integer-derived expectations, not measured results. Existing mini/large/native/historical artifacts keep their original identities/statuses; no previous evidence is upgraded by this document. No runtime, fixture generation, build or large test was performed by this subtask.
