# Contracts domain and document adapter

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts\cafe_fin`.
Baseline: `e668355` (`cafe-fin-foundation-ready-v1`). This subtask changes only schemas, rendering, two original JSON templates, domain tests and this handoff. No migrations, new dependencies, shared files or old CRM source were used.

## Public interface

- `schemas.ContractData`: strict Pydantic input for purchase/sale, embedded core parties, manual or linked weighing lines, tax, structured terms and payment. Input/output dates remain validated `YYYY-MM-DD` strings. Amounts normalize through core helpers to money two decimals and kg three decimals. Contacts/bank-details JSON arrays normalize to the core tuple DTO without changing its interface.
- `schemas.TEMPLATE_IDS`: purchase `be33fbce-4a0d-50eb-b203-895a24102ce1`; sale `9be1e97b-8278-55d3-aaba-13f663349ab2`. Template kind and ID must match. Linked weighing IDs normalize as UUIDs. Duplicate `(weighing.id,line_index)` is rejected even when versions differ; independent contracts can reuse the same party or source.
- `rendering.totals(data)`: dict with `quantity_kg`, `line_amounts`, `subtotal`, `net_amount`, `tax_amount`, `grand_total`, `tax_mode`, `tax_rate`, `rounding_policy`, `amount_in_words`. Money/kg values are canonical strings; unknown total/tax/net/words are `None`. `subtotal` always means the sum of entered-price line amounts; for inclusive tax it already includes tax.
- `rendering.DEFAULT_TEMPLATES`: tuple of descriptors `id,kind,version,title,body,hash`. Source payloads are `templates/purchase.json` and `templates/sale.json`. Version is 1; no party, bank, signer or tax policy is hardcoded.
- `validate_template(payload)` and `template_hash(payload)` accept exactly `{title,body}`. Pass only these fields from a descriptor. All supported tokens must remain present; malformed/unknown tokens and invalid control characters are rejected. The hash is SHA-256 of UTF-8 canonical JSON with sorted keys and compact separators.
- `build_document(data,computed_totals,template_payload)` returns core `DocumentSnapshot`. It recomputes and compares totals to reject stale/forged inputs. Persist `dataclasses.asdict(snapshot)` plus input, totals and template/version metadata before separately rendering the same snapshot with core `DocumentRenderer.docx` / `.pdf`.

Tokens: `number`, `occurred_on`, `place`, `company`, `counterparty`, `goods`, `totals`, `delivery`, `packaging`, `quality`, `deadline`, `responsibilities`, `additional`, `payment`, `signatures`, surrounded by `{{` / `}}`. Substitution is a single literal pass. Braces entered as user text remain user text and are never recursively evaluated. Free text, HTML-looking content, ampersands and newlines flow to the shared escaped PDF/literal DOCX renderer. Nested core DTO text is checked recursively for characters XML cannot represent.

Goods are numbered prose in logical template order: parties → goods → totals → terms/payment → signatures. Every selected quantity, unit price, amount, optional gross/tare/net, note and source identity is shown; original weighing snapshot kg remains distinguished from the quantity selected on the contract. The shared renderer places its one optional table after every paragraph, so using that table here would put goods after signatures. No shared renderer change is necessary for complete readable output.

## Arithmetic and payment semantics

Integer kg thousandths multiply integer price hundredths; each line is rounded half up to 0.01 VND. Rounded lines are summed, then contract tax is computed and rounded half up once. Products and sums are checked against core int64 limits. Binary floats and Decimal context-dependent arithmetic are not used.

- `unspecified`: no implied rate, tax, net or grand total. Output explicitly says tax and total payment are unknown.
- `none`: explicit tax zero; total equals subtotal.
- `exclusive`: subtotal is net; rounded tax is added once.
- `inclusive`: subtotal is grand total; rounded included tax is `subtotal × rate / (100 + rate)` and net is grand minus tax. No tax is added twice.

Rate is required only for inclusive/exclusive, 0–100 percent, using core two-decimal precision. Zero amount is preserved, including deposits, recorded-paid amounts and installments. Vietnamese money words read the exact rounded money including fractional VND as `… đồng và … phần trăm đồng`; they do not discard cents. Payment methods and account/due-date/schedule/description are exported from actual input. Deposit is labeled a contract term; recorded paid is separately labeled as user-recorded. Nothing in this module writes stock, cash, accounting or source records.

## Validation evidence

PASS, repository pinned `.venv`:

```powershell
.venv/Scripts/python.exe -m pytest tests/contracts/test_domain.py -q
# 56 passed in 0.90s
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/contracts/schemas.py backend/cafe_fin/contracts/rendering.py tests/contracts/test_domain.py
# All checks passed!
```

Tests cover all tax modes and rate zero, line-first rounding, int64 overflow, precision/type/date errors, source duplicate/version rules, distinct source and selected kg, exact Vietnamese words including zero/fractions, both kinds and all four payment methods in real DOCX/PDF encoders, structured terms, safe literal HTML-like input, nested invalid controls, source UUIDs, template editing/hash/token failures, stale totals and long Unicode/multipage content. Byte/text checks establish content, not DOCX visual layout.

## Synthetic document and visual evidence

Applied the documents/pdf skills. Both format-specific artifact marker scripts ran successfully once with `create`, expected count 2 and their corresponding format. Fixtures and logs live only outside Git at:

`C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-render-proof`

Bundled Node: `C:/Users/NC/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe`.
Bundled Python: `C:/Users/NC/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Bundled Poppler: `C:/Users/NC/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe`.

`build_proofs.py` in that temporary directory imports the repository backend and actual core DocumentRenderer, generating the same snapshot into independent DOCX/PDF files. The artifact runtime contains ReportLab 4.4.9 and python-docx 1.2.0 (matching project pins) and Pydantic 2.14.1 (project tests use pinned 2.14.3). `manifest.json` records final byte hashes and snapshot hashes.

```powershell
& '<bundled-python>' "$env:TEMP/cafe-fin-contracts-render-proof/build_proofs.py"
& '<bundled-poppler>/pdftoppm.exe' -scale-to 1500 -png "$env:TEMP/cafe-fin-contracts-render-proof/purchase-short.pdf" "$env:TEMP/cafe-fin-contracts-render-proof/purchase-short-page"
& '<bundled-poppler>/pdftoppm.exe' -scale-to 1500 -png "$env:TEMP/cafe-fin-contracts-render-proof/sale-long.pdf" "$env:TEMP/cafe-fin-contracts-render-proof/sale-long-page"
```

| Fixture | Format | Bytes | SHA-256 | Pages |
|---|---|---:|---|---:|
| purchase-short | DOCX | 38078 | `5c4a0aab1ffa8c64018cd72fa469edc0a9a81e0b1384e00e21339ac08e4d2120` | Not visually rendered |
| purchase-short | PDF | 36820 | `6bbd25f604a4293ecb6c91c957b1c57e890682be490b85a26d7f5fdf97164e87` | 2 |
| sale-long | DOCX | 38808 | `83b153a1391300fdf9e46a20f73326ca2abc978ab26cd994f6e8252b0fd04b67` | Not visually rendered |
| sale-long | PDF | 40339 | `bc45f2e4b20145c479fb8d171879b67f417ba12f41009e4cf4e08e43ebe15199` | 5 |

PDF visual PASS for readable Vietnamese, A4 margins, safe literal `<script>`/ampersand, totals, schedules, all 24 long-fixture goods, long names/addresses/terms and signatures. Every raster was opened and inspected: purchase pages 1–2 and sale pages 1–5. No overlap, clipped glyphs, missing content or unresolved template tokens were observed. Prose may continue across page breaks: sale row 9's note begins page 2, responsibilities continue from page 3 to 4, and seller signature ends page 4 while buyer signature starts page 5. This is a documented pagination limitation rather than a claim that signature blocks stay together.

DOCX visual NOT RUN: attempted bundled `render_docx.py` with `--output_dir .../docx-purchase --emit_pdf --verbose`. PATH was constrained to bundled Python/Poppler directories to prevent use of an installed desktop LibreOffice. It failed with `FileNotFoundError: LibreOffice soffice.exe was not found on PATH`, captured in `docx-render-attempt.log`. Bundle inventory contains no soffice executable. No installed desktop LibreOffice or online conversion was used. DOCX files are not asserted visually approved; clean Windows/native and DOCX layout remain release gates.

## Optional shared renderer request

For stronger page grouping, core could add immutable ordered document blocks with explicit `keep_with_next` / `keep_together` hints, including an inline table between paragraph blocks. Both encoders would need equivalent handling, JSON reconstruction compatibility, snapshot hashing and pagination tests. This would permit headings, individual goods records and the two signature blocks to stay together when they fit on a page, while allowing long free text to flow. No such shared patch is included or required to preserve current content.
