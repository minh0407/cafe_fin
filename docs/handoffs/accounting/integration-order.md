# Coordinator integration

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`.
Branch: `codex/cafe-fin-accounting-20261106`.
Foundation tag peels to `e668355c227322994902f7e2e38ed7ffb19ff647`.
No push, merge or READY tag was made by this lane.

## Accounting-owned commits, chronological

Apply the complete series before opening an accounting data root; intermediate
development schema definitions are not application release points.

| Commit | Scope |
|---|---|
| 90ee46c | Exact parsers, validation and Decimal formula engine |
| 90ac611 | Books, staging, durable jobs, APIs and provider |
| 45bc416 | Paged UI and explicit v2 reporting semantics |
| eb4b007 | Independent review fixes and resource boundaries |
| 8e8cc28 | Large clipboard staging and inclusive business dates |
| d08f7cd | Approved file authority and cooperative complete-source parsing |
| 56b8c0e | Verification handoff only |
| 033e900 | Historical benchmark/interruption evidence only |
| 8b70f1f | Nullable-schema duplicate compatibility, bounded pair queries, migration2 |
| a82476e | Vietnamese DateInput adoption and invalid-draft guards |
| 9a52f02 | Numeric filter query plan and regressions |
| 3aa8c47 | Text/date filter query plan and retained timeout evidence |
| ae495d7 | P2 blank filter includes missing historical nullable cells |
| 8312023 | v3 book name from the same read snapshot as totals |
| e0359c1 | SchemaEditor lost-ACK command freeze and real POST/PATCH regressions |

The final test-harness/evidence commit follows these commits in branch history.
Its exact ID is supplied with the final chat handoff. It does not change the
frozen backend/runner used for the final CSV measurements.
The SchemaEditor regression config imports the shared test-only1424 harness
helper supplied by that final commit; apply the complete series before testing.

## Approved shared commits already copied locally

These copies are not accounting changes. The coordinator owns the original
commits and must not apply both the original and its local cherry-pick copy.

| Original approved commit | Local copy |
|---|---|
| 57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a | 0da9c87 |
| 22ca543106bdcc91e55e11067683f5514fbbada3 | 59d94da |
| 48858654f6263cb541e6e03aef55a0598ddbf896 | 1be5a0f |
| 6098a1111432995ed5b6be96fd0650af382a15e2 | ef29e46 |
| 3aa94c601dbf878f07b46b0902fc71b0f388c40c | 545d75e |
| 206a7e30ce702d8064084c90296aed3634ef28b7 | 6052d13 |

Only the explicitly approved shared commits were cherry-picked. No later core
proposal is assumed present or validated by this lane's results.

## Wiring and release checks

The coordinator applies `shared-integration.patch`, preserving every other lane's
module/feature entries. It registers accounting's ModuleManifest and frontend
feature and includes accounting tests in discovery. Migration namespace is
`accounting:1..2`; migration1 remains unchanged by migration2. No production data was
migrated, reset, truncated or deleted by this lane.

Run the integrated registry build/tests after wiring. Lane browser evidence
loads the actual feature via a test-owned entry; the baseline product registry
still has its pending accounting entry. Native WebView2, clean Windows and the
installer remain coordinator release gates, separate from Chromium evidence.
Accounting's test harness uses exact loopback port1424 through a test-process-only
adapter; production CSP/origin/development1420 settings are unchanged.
