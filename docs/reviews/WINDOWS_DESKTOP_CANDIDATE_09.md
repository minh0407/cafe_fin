# Reviewed Windows desktop candidate 09

Run [42314420634](https://github.com/minh0407/cafe_fin/actions/runs/42314420634),
source **baa8e86a20520ae0613ae5f36b3c672554c42d21**: **SUCCESS**. Coordinator
observed both completed jobs and read their logs on 2026-11-07. Dependencies are
locked; runner is `windows-2025-vs2026`, Python 3.12.16 / SQLite 3.53.1,
Node 24 and Rust 1.99.1. This is a tested source/build candidate, not installed
clean-client or production release acceptance.

| Check | Actual result |
| --- | --- |
| Backend, including Windows aliases and Operator policy | 1,153 PASS / 886.36 s; no skips |
| Backend lint and compile | PASS |
| Frontend production build | PASS; existing Vite size warning |
| Main browser suite including real local API | 57 PASS |
| Accounting mock / real API / schema | 17 PASS / 1 PASS / 11 PASS |
| Contracts / records / reporting browser configurations | 3 PASS / 1 PASS / 1 wrapper PASS |
| Native library: control, journal, handles and transitions | 47 PASS |
| Explicit Rust codec and production Python interoperability | 1 PASS / 7.14 s; not ignored in this execution |
| Newly built frozen sidecar with restricted developer PATH | 1 PASS / 14.90 s |
| Headless production native controller with matching frozen sidecar | 2 PASS / 24.28 s; zero ignored |
| Tauri release compile and NSIS build | PASS |

Native library job: `128223449631`; full Windows job: `128223450031`.
The production controller tests exercise actual source setup, online backup,
move, verified closure, dormant target login, explicit activation, restart on the
durable target, restore and reporting suspension. A separate actual closed-source
boundary denies full operation status to invalid, Operator and old Admin tokens
without starting another process. These are actual controller/core/filesystem
tests, distinct from synthetic-host tests and actual GUI installation.

## Build receipt

Frozen sidecar SHA256:
`672F6ACF8620EFF2930CB683F1E570C6303452B05F2940CA708F74EC46D3B9C4`.

Installer: `Cafe Fin_0.1.0_x64-setup.exe`, **253,033,714 bytes**.
SHA256: `8499656CBF6CF3F092E8829A43238731D439119AC68D5F57DA1ABAA9276C9220`.
Tauri release compilation took 3m36s. The workflow bundled WebView2 offline
installation support and printed the candidate receipt to logs and the job summary.
Binary hashes are evidence for this run, not a reproducible-build claim.

No artifact was uploaded, release published or installer installed. The binary
existed only on the temporary build runner; this receipt is not a download link.
The later coordinator documentation commit has identical application, test and
build source to the SHA above; only review documentation and README are changed.

## Current acceptance boundaries

The single-PC role matrix, daily workflow and synthetic report example are in
[USER_GUIDE](../USER_GUIDE.md). Business data starts new; old CRM source/database
are untouched. Application data remains local; no Google authentication or
multi-person approval is introduced. Zalo remains unconfigured without the actual
eligible group/account/credentials; no real message was sent during validation.

Clean Windows install, OS dialogs/Explorer/native GUI, disconnected-WAN use,
upgrade/uninstall, physical power loss and packaged large-file timings remain
NOT RUN. Local native executable restrictions were not changed or bypassed.
Native corresponding-source/relink evidence remains open. First-install and
cross-version restore, native INTENT before absent core intent after a crash, and
partial activation retain the conservative held-state limits documented in the
core/native handoffs. No production-ready or binary-distribution clearance claim
is made from this build.

Prior failed runs remain documented: `42306336184` exposed a browser test-adapter
signature mismatch; `42311533753` exposed Windows verbatim disk paths. The fixes
were validated in this new exact-source run rather than re-labelling those failures.
