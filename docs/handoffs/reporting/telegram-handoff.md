# Telegram reporting handoff

The executable sender and Admin configuration now use Telegram Bot API only.
The OA/GMF adapter was removed. Historical data stays labelled `zalo_legacy`;
legacy recipients, payloads and receipts are never turned into Telegram routes.
Local reports, immutable snapshots/exports, daily generation, restore quarantine
and human-copy re-materialization retain their existing contracts.

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-reporting\cafe_fin`.
Branch: `codex/cafe-fin-reporting-20261106`. No push/merge to main or live send.

Runtime/UI/fixture checkpoint: `5ef2f734d5a4985c6cb933d69fe5ad0052b7c55c`.
The following regression/handoff commit completes its WIP validation. Coordinator
already owns integration baseline f59bff08 and OS namespace 516b536; skip the lane's
baseline merge commits when cherry-picking. Root's shared-consumer b354fa61 is not
merged back into this lane while reporting validation runs.

## Interface and implementation

[Exact HTTP/settings/OS/provenance contract](telegram-contract.md). The shared
module_manifest signature and read bridge are unchanged. Credentials PUT accepts
only a private `bot_token`; settings use negative numeric `chat_id`, readonly
candidate `bot_id` and readonly `bot_verified_at`. Identity proof is persisted as
cleared before OS replacement, so interrupted/failed token updates cannot reuse
old verification. The candidate ID comes from the token prefix, then getMe must
verify it. Check-connection only verifies identity/chat/self membership/rights;
it never sends. UI refreshes metadata/version after both success and failure,
resets the password, and preserves editable settings drafts.

New files: `telegram.py` and `telegram_migrations.py`. Changed runtime files:
`models.py`, `module.py`, `service.py`, `sender.py`, `restore.py`, `schedule.py`;
removed `zalo.py`. UI changes are ReportingPage, types and DailyScheduleHistory.
Test helpers/harnesses and provider/privacy/recovery/migration suites are updated.
No dependency/license, shared registry, core, desktop or external-document edit.

Migration **reporting v4** is additive: provider/bot/chat/paired-receipt/retry
columns on existing outbox and attempts, safe indexes, immutable provenance/attempt
triggers, and a versioned settings reset. Migrations 1/2/3 fingerprints stay exact.
Old retryable/inflight rows become UNKNOWN, old unfinished daily runs NEEDS_MANUAL,
old sender/daily schedules disabled. Legacy SENT receipts and attempt/payload data
are retained. Real upgrade tests cover all old states and original canonical bytes.
The v4 fingerprint uses ordered actual ALTER SQL, avoiding nondeterministic cloned
constraint order; six independent process/hash-seed checks verify reopen stability.

Only five allowlisted methods at HTTPS api.telegram.org are used: getMe, getChat,
getChatMember, sendMessage, sendDocument. TLS defaults are verified, redirects and
environment proxies disabled, request timeout 20s, response at most 1 MiB. Raw
endpoints/exceptions/Telegram descriptions never enter errors/audit/logs. Plain text
is pinned within 4096 UTF-16 code units; no parse mode, no link preview. Selected
reporting-only canonical PDF/XLSX attachments have fixed names, verified hashes and
a 5 MiB limit. Text and document IDs are separately paired with the actual chat.
Message ID zero, bool/string IDs, wrong group/bot/type and malformed POST responses
cannot become SENT. Anonymous administrators are rejected before a POST; an ordinary
member with send rights is sufficient, no administrator promotion is required.

## Reviewed edge cases

- An incomplete setup creates an unbound UNCONFIGURED local intent with empty
  destination and no bot binding. It does not reserve a real route. After normal
  setup/check, the same saved report can automatically get its bound delivery,
  without forcing a report adjustment. Original intent bytes remain unchanged.
- A known bot switch retains the old route. Automatic selection skips the
  conflicting series; dispatcher claims only the current bot/chat. Old identity
  backlog cannot abort a tick or prevent healthy work. An explicit new report
  revision can be sent with the new identity.
- 429 waits are durable and bot-wide, including other queued reports and connection
  checks. A valid 1..3600 second delay is kept exactly; no fresh WAN or attempt runs
  before it expires. Unsupported delays are not shortened: immutable attempt
  evidence creates a bot-wide REVIEW_REQUIRED hold, not bypassable by another
  report/chat. No automatic disposition of that exceptional hold is offered.
- A transient DB/ACK failure after a positively confirmed text send preserves its
  receipt. If document POST was not entered, retry sends only the document. If a
  POST outcome is ambiguous, UNKNOWN remains blocked; no exactly-once claim.
- Telegram has no general sent-message history query. Reconcile performs no WAN
  or secret access, preserves UNKNOWN and requests manual comparison in the group;
  no invented receipt, text/time match or manual fake-SENT operation exists.

## Validation

Windows 11 / Python 3.12.16 / SQLite 3.53.1; synthetic data only. Tests include
230 transport cases, 20 real legacy upgrade/restore/process cases, token lifecycle
faults, genuine Windows Credential Manager with exact synthetic-key cleanup,
current-actor/lock concurrency, two queued reports under cooldown, plain/document
receipts, exact-size real XLSX attachments, process death after outbound effects,
real timer/daily generation, local export recovery and browser behavior.

```powershell
.venv/Scripts/python.exe -m pytest tests/reporting -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/reporting -q -k 'not real_production_60_second_timer' -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.venv/Scripts/python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
git diff --check
# frontend:
npm run build
node node_modules/@playwright/test/cli.js test --config ../tests/reporting/ui/playwright.config.ts
```

The first full reporting invocation ran **403 cases in 190.29s**: 402 PASS,
including the actual 60-second timer; one old API fixture still submitted OA
credentials and expected 403 instead of schema 422. That fixture was corrected to
a valid Telegram body, with added no-readback/no-token-in-DB assertions; its focused
rerun PASS in 1.32s. Final regression: **402 PASS, 1 timer deselected, 130.49s**.
The source was unchanged between the full invocation and final rerun. Existing
Starlette/httpx deprecation warning is unchanged. Ruff lint/format checks all 40
reporting Python paths and Git whitespace PASS.

PASS: frontend production build, TypeScript, both browser assertion harnesses under
one Playwright wrapper (latest 16.1s), Ruff and Git whitespace. Synthetic evidence
stays outside Git at `%TEMP%\cafe-fin-reporting-ui-tGSAOO`; the Telegram settings
screenshot was visually reviewed. No stale OA/app/refresh input or GMF label remains.
Browser tests cover password reset on failed token storage, refreshed lost proof/
version without losing drafts, PDF/XLSX attachment filtering with TXT local export,
legacy channel/read-only receipt display, UNKNOWN, restore/date/book/schedule UI.

NOT RUN here: live Telegram/BotFather/account/group tests, clean-Windows installer,
native packaging, benchmark or full non-reporting backend suite. Root separately
reported its shared namespace + actual default-registry wire restore + real
business-workflow checks PASS with this source checkpoint; that is coordinator
evidence, not a lane claim of rerunning those commands.

## BotFather and local setup

1. Use the official [BotFather](https://t.me/BotFather) in Telegram and `/newbot` to
   create your own bot. Keep the token private; paste it only in cafe_fin's Admin
   password input. Do not put it in a browser URL, chat, screenshot or support log.
2. Add that bot to your own group/supergroup. Grant only sending messages and, if
   selected attachments are needed, documents. Keep privacy mode enabled. Do not
   make it an anonymous administrator or use another bot to read your group.
3. Enter the confirmed numeric negative Chat ID supplied by that group's admin;
   usernames, invite links, private chats and channels are not accepted. This build
   does not implement getUpdates/group discovery or read group-message history.
4. Save Chat ID/time/local options and save the token in either order, then click
   Check connection. Check the displayed bot ID and verification time. This makes
   no test send. A token/chat change requires checking again.
5. Enable the sender schedule only when that destination is intended. Daily local
   generation is a separate opt-in; local PDF/XLSX/TXT works without Telegram.
   Actual trial sending requires a later explicit, verified destination request.

Official behavior was checked against [Bot API](https://core.telegram.org/bots/api),
[membership rights](https://core.telegram.org/bots/api#getchatmember), and
[BotFather/privacy guidance](https://core.telegram.org/bots/features#botfather).
No webhook, inbound command bot, personal-account automation or OAuth refresh is
part of this sender. Existing cross-version restore verification and partial
activation held-state limits remain; v4 does not bypass core integrity checks.
