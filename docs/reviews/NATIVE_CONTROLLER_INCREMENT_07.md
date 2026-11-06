# Native controller integration 07

Reviewed 2026-11-07 after maintenance baseline `ae82d00`. This increment connects
the renderer's six maintenance/reports commands to the production Windows
controller, including native-selected directories, verified source identity,
durable journal/config transitions, clean child closure and dormant target login.
Activation is explicit; no source fallback, marker rewriting or Google auth is
introduced. Actual installed GUI acceptance remains separate.

## Findings fixed before integration

- A successful core Activate ACK contains admission state without artifact
  metadata. The native library now obtains a fresh authenticated Status, validates
  every saved binding and confirms ACTIVE before archiving its journal. Minimal
  ACK and rejected/missing/conflicting status cases have regression coverage.
- OLD_CLOSED with a dead source previously returned a full operation view before
  authenticating. It now stays HELD; only the bounded desktop summary is available
  until qualified recovery creates an authenticated current child.
- A first-install picker selection could survive a successful relocation and
  cause Restart to try the source. The controller consumes that selection only
  after successful config readback; Restart follows the durable configured target.
- Derived human-readable report copies were absent after relocation despite a
  copied READY receipt. Reporting now invalidates projections inside its
  activation receipt and rebuilds canonical bytes in pages of 100 before workers.
  Conflicting external files are preserved and failures remain visible for retry.
- The accounting browser bootstrap did not accept Runtime's new activation_mode
  argument. Its explicit test adapter now forwards the argument without changing
  production origin/security policy.

## Evidence and exact limits

Previous Windows run [42306336184](https://github.com/minh0407/cafe_fin/actions/runs/42306336184)
at `ae82d00`: backend **1,119 PASS / 737.39 s**, main UI **57 PASS / 52.4 s**,
accounting mock **17 PASS / 23.3 s**, native library **37 PASS**. The overall run
FAILED at accounting real-API browser startup because of the test-adapter signature;
later feature/frozen/installer steps were not run. This is not a green build claim.

After the adapter fix, all six feature configurations ran locally and passed:
accounting mock 17/22.9 s, real API 1/23.3 s, schema 11/20.8 s, contracts 3/27.8 s,
records 1/20.2 s and reporting 1 wrapper/13.9 s with its internal assertion groups.
The independent original accounting failure was also rerun PASS in 21.5 s.

The final human-copy integration ran **28 tests PASS / 35.70 s**, including actual
private-wire restore across all four modules. Human TXT bytes in the target's
reports folder and source old folder match after activation and restart; canonical
data and exports remain unchanged. PDF/XLSX/TXT, paging, interruption, conflict and
revocation cases have separate owner coverage and six independently rerun cases.

Native code received independent static controller and UI/permission mapping
reviews. Actual Python/core probes confirmed the minimal ACK mismatch and the
corrected full-status/authority/marker behavior. These are not execution of the
Rust production adapter. Final root `cargo check --tests --bins --locked --offline`
and both Rust formatting checks PASS; no native executable was retried on this
Device-Guard-blocked host.

A genuine sidecar was rebuilt from the integrated reporting/core source before
that final product compile: **33,412,442 bytes**, SHA256
`b7549bac636945b967d639761d1c50dcf563f7ca3498c146381da247429310d6`.
Its inventory contains 51 native files. The executable stays outside Git and was
not distributed or used to claim installer/GUI acceptance.

The Windows workflow now explicitly executes the previously opt-in real
Rust/Python codec test and both headless production-controller tests. The latter
use the normal resolver and matching rebuilt frozen sidecar, real auth, actual
backup/move/restore, source closure and fresh target login, target-preserving
restart, and unauthenticated dead-source refusal. Until their run completes,
their runtime result remains **NOT RUN**; compilation/ignored counts are not PASS.

## Remaining boundaries

Clean-client install, dialogs/Explorer/native GUI, offline use, upgrades/uninstall,
physical power loss and packaged large-file timings are not proven here. The
documented native INTENT with absent core intent after process death remains
HELD; partial activation, cross-version and first-install restore also retain
their published limits. No real Zalo message, live credential or destination was
used. Native corresponding-source/relink evidence remains open; the factual
[source inventory](../handoffs/packaging/iconv-source-provenance-20261107.md) does
not clear distribution licensing. No release/artifact upload or production-ready
claim accompanies this source push.
