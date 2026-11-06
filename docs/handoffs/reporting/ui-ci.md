# Reporting UI CI entrypoint

The module-owned `tests/reporting/ui/playwright.config.ts` is discoverable by the
root workflow's existing tests/**/playwright.config.* scan. No workflow, package,
production origin/CSP, desktop config or shared test file was edited.

Run from the repository root:

```powershell
.\frontend\node_modules\.bin\playwright.cmd test --config tests/reporting/ui/playwright.config.ts
```

Playwright webServer owns Vite on the existing dedicated **1431** address, with
strictPort in vite.config.mjs, matching URL/readiness/fixture API base and
`reuseExistingServer:false`. It refuses an occupied port rather than reusing or
killing another service. Root's 1420 and records' 1421 are untouched. Normal
Playwright teardown stops its owned server; no manual Vite pre-start is needed.
The process no longer listened on 1431 after the validation run.

One smoke.spec.ts test sequentially spawns check.mjs and check-books.mjs through
Node with argument arrays, windowsHide:true, no shell construction, and per-run
REPORTING_QA_OUTPUT in a new system temp directory. Logs are saved/attached there;
Playwright outputDir is also under os.tmpdir. No screenshots/logs/test-results are
written to Git paths. The primary assertions stay in the existing MJS harnesses.
Nonzero exit, timeout or missing PASS output fails the wrapper. Each child closes
its browser in finally and disconnects IPC; a 70-second deadline requests an
owned-browser close via IPC, then only that child may be terminated after five
seconds. Deadlines are cleared on close/error. No unrelated PID is enumerated or
terminated, and the wrapper runs with one worker and no retries.

PASS **1 Playwright wrapper test, 12.5s**: main harness 21 internal assertion
groups + picker harness 10 groups. These are internal coverage labels, not 31
Playwright test cases. Evidence directory for the observed run:
`%TEMP%\cafe-fin-reporting-ui-6Z0Boo`. Report snapshots/settings screenshots were
visually inspected. Existing inherited FORCE_COLOR/NO_COLOR environment warnings
are non-failing; no warning suppression was added.

This is a synthetic browser regression harness, not real accounting/provider,
live Zalo, native Explorer/tray/installer or performance acceptance. Root should
run this config through CI together with its actual integrated API checks. No
push/merge/READY tag or additional product browser feature was introduced.
