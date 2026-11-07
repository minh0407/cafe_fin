# Telegram interface for integration

Provider transition replaces the executable sender and Admin UI. Shared registry
keeps `module_manifest(...)` unchanged. No dependency/license change is required.
Baseline f59bff08d06a8e84dcab24d5b3f0fabbf12a55ab and shared OS namespace commit
516b536f1c0f0d2028deb0c6cceb50a680eaee24 are merged into the reporting branch.

## Command and settings contract

- PUT `/reporting/settings`: existing request_key/expected_version and local
  scheduling/book/format/attachment fields; destination is `chat_id`, a canonical
  negative integer string, empty while unconfigured. No OA/group/app fields.
- PUT `/reporting/credentials`: only `{bot_token: string}`. Password input, no
  read-back, request receipt, audit payload or DB token. It derives the public
  candidate bot ID from the token prefix, stores the token in OS storage and
  clears previous connection verification durably BEFORE OS token replacement.
  Failed/crashed OS writes leave the bot unverified. No WAN call on this command.
- GET settings: `provider='telegram'`, `chat_id`, readonly nullable `bot_id`,
  readonly nullable `bot_verified_at`, existing schedule/restore/status metadata.
  Candidate bot ID is not proof of verification. Missing chat, bot, token or
  connection proof remains UNCONFIGURED and creates zero network send attempts.
- POST `/reporting/connection-check`: current Admin, existing Command body. Uses
  getMe/getChat/getChatMember on the bot itself, checks group/supergroup and text/
  selected-document rights. No send. On success pins bot verification for the
  current configuration and increments settings version; clients refresh GET
  settings before their next versioned save. Changing destination/token clears
  verification. No OAuth/refresh operation remains.
- OS key is `cafe_fin/reporting/<root_uuid>/telegram/<positive_bot_id>` per shared
  contract. Never fall back to, read, migrate or delete legacy credentials.
- New delivery DTO fields: provider, bot_id, chat_id, message_chat_id,
  file_message_chat_id, retry_not_before; legacy destination/history stays readable.
  Message IDs are canonical positive integer strings paired with verified chat
  IDs; the live Telegram response must contain actual JSON integers, not bools or
  numeric strings. No OA field in new settings/commands/delivery DTO.

## Persistence and provider safety

Append-only reporting migration v4 adds neutral provider/bot/chat/receipt fields
to the existing outbox and provider provenance to attempts. Old schema migrations
and immutable snapshots/exports remain unchanged. The physical old `oa_id` column
and its existing uniqueness constraint remain only for storage compatibility;
new Telegram rows leave it empty and use real provider/bot/chat columns. Another
bot cannot silently repurpose an existing report/chat delivery; identity conflicts
require explicit new work, never mutation of an immutable delivery. An incomplete
setup uses an unbound UNCONFIGURED intent (bot_id=null, destination=''), so it
does not reserve a canonical route. After ordinary setup the same saved report
can automatically get a new bound delivery, without a report adjustment. The
old intent/payload stays unchanged. Known old-bot routes are skipped by automatic
selection; they cannot abort a tick or block healthy current-bot work.

Historical rows/attempts are identified as `zalo_legacy`, never relabelled Telegram.
Transition holds old retryable/inflight rows as UNKNOWN, preserves receipt columns,
disables old sender/daily schedules and clears the destination/bot. Legacy delivery
series are excluded from automatic Telegram catch-up/reuse. Current restore guard,
whole-series hold, local generation and human-copy re-materialization stay active.
No historical report/attempt/payload is deleted or rewritten as a Telegram send.

Existing restore verification remains conservative across constructor migrations;
v4 does not bypass core's cross-version backup verification/admission gate.

## Outbound limits and evidence

Only allowlisted methods at HTTPS api.telegram.org, verified TLS, finite timeout,
no redirects, bounded response/body sizes, and fixed sanitized error codes. Token
is necessarily in the Bot API request path; endpoint/raw provider errors and
exception messages are never logged/persisted/returned.

Plain-text sendMessage is bounded to 4096 UTF-16 code units without parse mode;
any truncation occurs before pinning the immutable payload. sendDocument accepts
only explicitly selected reporting PDF/XLSX canonical summaries, bounded to 5 MiB,
with a fixed sanitized filename. No arbitrary path, URL or uploaded original.
Text and document receipts are persisted separately before proceeding. Uncertain
POST outcomes stay UNKNOWN; explicit rejection and bounded 429 retry delay are
  distinct, with no automatic FAILED retry. A valid retry_after of 1..3600 seconds
  is kept exactly as supplied and blocks the entire bot, including other queued
  reports and connection checks, until the persisted deadline. An unsupported
  delay is never shortened: TELEGRAM_RETRY_REVIEW_REQUIRED puts a durable bot-wide
  hold in immutable attempts and cannot be bypassed with another report/chat.
  The current release offers no automatic disposition of that exceptional hold.
  A transient DB/ACK failure after text confirmation preserves its receipt and,
  if sendDocument was not entered, allows a document-only retry. Telegram offers no general sent-message
history endpoint: reconcile keeps UNKNOWN and tells the user to compare manually.

[Implementation, validation and setup instructions](telegram-handoff.md). No live
token or send is requested; BotFather/setup acceptance belongs to a later explicit trial.
