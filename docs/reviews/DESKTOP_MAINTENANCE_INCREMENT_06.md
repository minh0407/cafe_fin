# Desktop maintenance integration 06

Reviewed on 2026-11-07. Business integration remains based on immutable
`cafe-fin-integration-ready-v1` (`c93ecfd`). This increment adds the shared runtime,
private control protocol, renderer workflow and native library needed for verified
backup, relocation and restore. It does not mark installed desktop acceptance.

## Behavior and boundaries

- Runtime admission drains business requests before quiescence; dormant targets
  allow authenticated health/login/logout without starting jobs or timers.
- Core owns verified snapshots, physical-root fingerprints, activation markers,
  authenticated receipts and owner activation hooks. New private source identity
  supplies the current Admin's verified binding before native journal INTENT.
- Binary private-pipe frames are bounded and correlated by child generation,
  request and operation. Maintenance CLOSED requires successful Runtime/HTTP/
  listener teardown followed by child exit 0. EOF, timeout and forced exit provide
  no clean-close proof. Paths and tokens are not response or diagnostic fields.
- Native libraries implement bounded journal/readback, immutable selections,
  close/config fences, local-path checks and verified-child attachment. A known
  SELECTING memory draft can be replaced; journaled or uncertain work cannot.
- Renderer gates ordinary business while held, reconciles missing responses and
  requires a fresh target login after every new-child BootSession. Recovery Run
  and activation retries depend on the actual native phase/capability proof.
- Reporting restore hooks quarantine uncertain deliveries before startup and
  suspend schedules until explicit current-Admin review. Proven receipts and
  immutable report/export bytes remain. Automatic work holds every version of a
  day/book series containing a restored uncertain delivery, including a newer
  report already SAVED before backup. Explicit manual work remains available.

This reviewed native baseline still boots legacy protocol and does not advertise
maintenance capability. Its actual maintenance command/controller wiring is the
next packaging increment. The renderer therefore keeps these actions unavailable
on this baseline rather than reporting simulated completion.

## Verification

| Check | Observed result |
| --- | --- |
| Integrated backend before the final series predicate fix | PASS: 1,116 tests, 484.81 s; zero skips/failures |
| Source identity plus real-child control suite | PASS: 39 tests, 34.42 s |
| Independent transport rerun | PASS: 28 tests, 29.76 s, plus real unauthorized/no-effect and clean-close probe |
| Frontend including real API before the final recovery-button adjustment | PASS: 54 tests, 31.3 s |
| Final maintenance UI recovery adjustment | PASS: 25 focused tests, 27.9 s |
| Final frontend production build | PASS; Vite reports the existing large bundle warning |
| Owner restore series fix | PASS: 10 restore and 29 sender/daily cases |
| Independent final series fix with all four modules | PASS: both automatic modes make zero provider calls/attempts; new days and explicit manual sends work; two regression cases PASS in 4.25 s |
| Backend Ruff and compile checks | PASS after qualifying the new integrated reporting fixture import |
| Native product compile | PASS: cargo check, locked/offline, 59.02 s; genuine local sidecar built first |
| Native executable tests on this host | NOT RUN: previously blocked by Device Guard; no policy/path workaround |
| Windows CI native harness and current installer | Pending run for this source; no installer artifact uploaded/released |

The full backend initially stopped during collection because the new lane test
used an unqualified conftest import. The coordinator changed it to
`tests.reporting.conftest`, sorted the import, then obtained the 1,116-test PASS.
The final series fix changes only reporting predicates and its focused regression
cases; those timings are not relabelled as a new full-suite run.

The native compile verifies the same Rust baseline using a genuine sidecar built
before the reporting restore hook was integrated. It is compile evidence, not a
claim that that earlier binary contains the final reporting source. The Windows
workflow rebuilds the sidecar from its exact checked-out source and now runs the
standalone native library harness in a separate job. Build outputs and inventories
used for local evidence remain outside committed runtime data.

## Open acceptance work

Actual native command wiring, dialogs and installed lifecycle still need review
and execution. Clean Windows installation/offline use/upgrade/uninstall, physical
power-loss behavior and distribution licensing/source/relink evidence remain open.
Partial activation and cross-version restore remain conservatively held as
documented by the core handoffs; there is no implicit source fallback or first-
install restore flow. Zalo has no live destination/credential acceptance and no
real message was sent. Large import evidence remains in the accounting handoffs;
this increment does not re-run or re-label its benchmarks.
