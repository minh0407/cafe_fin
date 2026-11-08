# Desktop contract fixtures and render QA — 2026-11-08

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin`.
Branch: `codex/cafe-fin-contracts-desktop-20261108`.
Exact baseline: `eab8c96b851f039de515083189f4301cc09437c0`.

This subtask owns only `tests/contracts/desktop_fixtures.py`, `tests/contracts/test_desktop_fixtures.py` and this document. It changes no product source, shared renderer, dependency, migration or packaging. Names, contacts, tax/identification values and account details are invented test data. No CRM source, real profile, production database, signature or seal was read or copied.

## Fixture interface

`contract_payloads()` returns fresh JSON-ready dictionaries keyed `purchase` and `sale`, accepted by current `ContractData`. They use fixed date `2026-11-08`, deterministic template/product UUIDs and empty source references. This explicitly supports manual entry without Records. A real HTTP runner may seed Records and replace product/source references on its own copy; those variants must record their own snapshot hashes because displayed weighing lineage changes the document.

The company, farm and customer include Vietnamese names/addresses, contacts, synthetic identification/tax strings, representatives and bank details. Reserved `.example` email domains and prefixed `THU-` identifiers distinguish fixture text. Farm human code `AB01`, area `VÙNG-THỬ-01` and plot `LÔ-THỬ-02` appear in freeform terms because core `PartyInput` has no farm-specific fields.

Purchase includes two rows: manual net-only, then gross/tare/net. Sale includes 18 rows and a long customer name/address, edited multiline clauses and literal HTML-looking text. Mixed/bank payments include a receiving account, due date, two installments, contractual deposit and separately recorded paid amount. These values are contract text and have no stock/cash effects.

## Independent expected values

Expectations are literal constants in the fixture module. Test assertions compare the product to those constants and separately cross-check with Python Decimal equations; expectations are never populated by calling product `totals()` inside an assertion.

| Value | Purchase | Sale |
|---|---|---|
| Quantity kg | `350.130` | `173.250` |
| Entered-price subtotal VND | `23771988.03` | `18711000.00` |
| Net before tax VND | `23771988.03` | `17325000.00` |
| Tax VND | `1901759.04` | `1386000.00` |
| Grand total VND | `25673747.07` | `18711000.00` |
| Tax choice | Exclusive 8% | Inclusive 8% |
| Contractual deposit VND | `500000.50` | `1000000.00` |
| Separately recorded paid VND | `0.00` | `250000.25` |

Purchase arithmetic: `100.005 × 100.50 → 10050.50`; `250.125 × 95000.25 → 23761937.53`, each rounded half up to cents. Subtotal `23771988.03`; 8% tax rounded once is `1901759.04`. Sale quantity is `sum(n + 0.125, n=1..18) = 173.250`; entered price `108000.00` includes 8%, so the total is `18711000.00` and net is `17325000.00`. Deposits/paid amounts do not alter either grand total.

Canonical base payload SHA-256 uses `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`. Document SHA-256 uses core `DocumentSnapshot.canonical_bytes()` with the default version-one template. These hashes freeze the manual fixture only, not runtime IDs, timestamps or rendered file bytes.

| Kind | Canonical base payload SHA-256 | Default base document SHA-256 |
|---|---|---|
| Purchase | `9ccd30936a82c19932771b7be5d5a85810309faf6af210cb8601faf826abf270` | `76ab9934f5bf3cf5e9bf6ce9114f00553b5778c6ee6689fdee7b280c5626bd73` |
| Sale | `e18618205f82f31b5596a594d42dd19e88cee71d15d61a89161d99219906ccbf` | `4c998c2220279435d0f6ada4d744424c7c65d4da9d9c4aabe8f25e6d69a26ef5` |

The base document hashes above include the parent's narrow presentation repair for known quantity-source labels. Raw payload hashes, raw source/input values and all independent expected totals remain unchanged. The repair was reviewed: known `direct`/`direct_net` and `gross_minus_tare`/`gross_tare` labels change only visible wording; unknown freeform values remain literal, and visible original source kg now uses the existing number formatter. The manual base fixtures have no original source snapshot, so their changed document hashes come only from the known visible labels.

## Source fixture checks

PASS on the new worktree's locked Python environment:

```powershell
.venv/Scripts/python.exe -m pytest tests/contracts/test_desktop_fixtures.py -q
# 14 passed in 0.41s
```

Coverage includes schema/JSON validity, UUIDs/date, deterministic hashes, independent expected totals and money words, Decimal arithmetic, mutable-copy isolation, manual net-only/full weighing distinction, literal multiline terms, separate deposit/paid meaning and all long-sale content before signatures. These checks do not prove native desktop behavior or visual layout.

## Document QA status

Updated documents/pdf skills `26.1104.22356` were applied. A4 is the requested product page size. The parent ran each format's authoring marker once before actual HTTP exports, with expected count three DOCX/two PDF; this subtask only reads and rasterizes those outputs and did not repeat markers. No product documents were authored through a substitute renderer.

The final source HTTP output directory is:

`C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-desktop-source-20261108-efa2d9ee67-output`

Its `manifest.json` SHA-256 is `31d44e9c4e20a393b2ccc2843f3cda4100384757357d0decc7615866b0fa6307`. It supersedes intermediate output `88a1001d7d` (less complete seeded parties) and pre-fix output `3576bf944d` (retained only for the presentation repro below). The final runner seeds rich farm/company parties through actual Records APIs and preserves their long names, addresses, contacts, accounts and representatives through typed auto-fill. It records raw source weighing kg `999.999` separately from user-selected contract kg, displaying the original kg as `999,999`. Runtime source IDs differ from the deterministic base fixtures and have their own recorded snapshot hashes.

The parent harness manifest reports a real authenticated loopback HTTP run using this worktree's locked Python 3.12.16 executable and committed backend `682861deae950de5cb4ebfb8cab7666439fd2903`, the narrow contracts presentation repair after the exact assigned baseline. It is explicitly `source_python`, not frozen, GUI or clean Windows evidence. Its checks cover source copy/quantity override, manual contracts without sources/attachments, preview/snapshot, byte hashes/replay/idempotency, historical bytes after source/draft/template edits, unchanged public side effects and restart persistence. This render subtask independently read the exported files and compared their actual hashes/sizes with that manifest.

| Source HTTP file | Bytes | Actual SHA-256 | Pages / visual scope |
|---|---:|---|---|
| `manual.docx` | 38749 | `546e5fc09b12a4006836fff5fd4b95022181e4eb34fde1f7be058c7430f014f5` | Visual NOT RUN |
| `purchase.docx` | 38820 | `00c955a78a1214c5aff58cce38592dff151b5782ec45ac6f54ade0c4e507b3bd` | Visual NOT RUN |
| `purchase.pdf` | 38493 | `51a39dee762f460c9b2b6b32a3df6a16cba1d6d3ea397530426a16a385ab090c` | 2, every page inspected |
| `sale.docx` | 39463 | `0ea8245b819fad160183144b1926a4f4e892b514b6911dcdadc59e240084c422` | Visual NOT RUN |
| `sale.pdf` | 42481 | `9a12c29dbd827b7ffa269cb96330e282808f4b98a4c9b28f233a9ba609c888b0` | 6, every page inspected |

### Structural checks — PASS, source files only

Every actual byte hash/size agrees with the source HTTP manifest. The document SHA-256 is `f6bb6b38920f58e4a9852fd012e8c301b1f5e32779b3bd4965ec5bf62d5f631d` for manual, `1b2e650b7901cc62faf6d93d03e28655ab6167fbdb350fa078c64ca2cf8cb666` for purchase, and `2701c0c3f85e855180956cf357b020d9a0dcc50e0b1750f399116691e1ec63ba` for sale. Each DOCX identifier and each PDF subject points to its corresponding canonical document hash. This hash describes the document scalar content, distinct from the service's larger export snapshot hash.

All eight PDF pages are A4, `595.2756 × 841.8898 pt`. Both text fonts actually used in PDF text-showing operators are embedded subsets of NotoSans Regular/Bold. These checks inspect the used fonts, not an unused default font resource. Each DOCX section is approximately `21.00086 × 29.70036 cm`, the normal OOXML twip approximation of A4. Text contains the literal `<script>`/ampersand examples and no unresolved template tokens. These structural checks are separate from the visual conclusions below.

### PDF visual review — legibility PASS with bounded findings

Bundled Poppler rendered the actual exported PDFs to 1500-pixel page images, opened individually at original image resolution using `view_image`: `purchase-page-1.png`, `purchase-page-2.png`, and `sale-page-1.png` through `sale-page-6.png`. Every representative page was inspected.

- Purchase page 1: full company/farm details, both weight modes, edited source quantity, prices, totals and Vietnamese amount words are readable. Page 2: remainder of the amount words, edited delivery/payment schedule, farm/area/plot text, literal HTML-looking clause and both signature blocks are visible.
- Sale page 1: the long customer name, 351-character address with Vietnamese glyph probes, contact/bank/representative fields and source/first goods rows wrap inside A4 margins. Pages 2–4 show all remaining goods through row 18 and the inclusive totals. Page 5 contains bank payment, separate deposit/paid values, both installments and the complete long edited clause. Page 6 contains both signature blocks after the clause; the long buyer name wraps without touching the other content.
- No missing Vietnamese glyphs, overlap, text clipping or lost goods/clauses were observed. Literal `<b>`/`<script>` text remains visible as text. Signature blocks are clear of the long clauses in this representative export. This is not an unqualified statement of final layout polish; the bounded findings below remain.

### Resolved adapter findings and remaining shared pagination limitation

1. **Source kg display inconsistency — resolved by parent commit `682861d`.** On superseded pre-fix `3576bf944d/purchase.pdf` page 1, selected quantity reads `100,005 kg`, while original source reads `tịnh (kg): 999.999`; the same difference appears beside selected `1,125 kg` on pre-fix sale page 1. The value was the correct original source Decimal string, not a changed selected amount or arithmetic error. Repro: select source `net_kg="999.999"`, override contract quantity, preview/export. At baseline, the contracts adapter `backend/cafe_fin/contracts/rendering.py:228`–235 concatenated `getattr(weight,key)` directly; other kg used `_display`. The parent's repair now formats only the visible source weight with `_display`, preserving the raw snapshot value. Final `efa2d9ee67` purchase/sale page 1 both visibly show `999,999`, matching the surrounding decimal convention. This was an adapter presentation finding, not a core numeric-storage defect.
2. **Known quantity-source codes shown literally — resolved by parent commit `682861d`.** Pre-fix purchase page 1 and sale pages 1–4 showed `direct`/`gross_minus_tare` from adapter baseline lines 214–215. Final purchase/sale page 1 and sale pages 2–4 display `Nhập kg tịnh trực tiếp` / `Cân đầy trừ cân rỗng`. The repair maps only known codes and leaves arbitrary freeform input unchanged. Actual final `manual.docx` text was separately checked to contain `Cách ghi lượng: Người dùng ghi nhận kg theo sổ tổng hợp riêng` exactly; this is structural, not DOCX visual proof. The two adapter fixes were made by the parent; this subtask changed no product source.
3. **Paragraph continuation is not grouping.** Purchase amount words begin on page 1 and finish with `phần trăm đồng.` on page 2. Sale row 9 starts on page 2 and continues on page 3; row 15 spans pages 3–4. Nothing is clipped, but isolated continuation lines reduce readability. Core `backend/cafe_fin/core/renderers.py:207` creates independent flowable paragraphs without document-block grouping. An ordered immutable grouping/keep-together interface would require a separately reviewed shared change and both-encoder tests. This subtask changed neither core nor the domain adapter.

### DOCX visual review — NOT RUN

All three files were attempted with the updated bundled `render_docx.py`, `--output_dir`, `--emit_pdf`, and `--verbose`. To obey the skill's bundled-only LibreOffice rule, the subprocess PATH was restricted to bundled Python/Poppler/override directories. Every attempt exited 1 with `FileNotFoundError: LibreOffice soffice.exe was not found on PATH`. The bundle inventory contains no soffice executable. Installed desktop LibreOffice, installed Office and online conversion were not used. Logs are `manual-docx-render.log`, `purchase-docx-render.log`, and `sale-docx-render.log` beside the final HTTP manifest. No DOCX page count or visual PASS is claimed.

### Reproduction tools and evidence scope

Workspace dependency loader resolved:

- Python: `C:/Users/NC/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`
- Poppler: `C:/Users/NC/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe`
- DOCX helper: `C:/Users/NC/.codex/plugins/cache/openai-primary-runtime/documents/26.1104.22356/skills/documents/render_docx.py`

Read-only QA helper and its complete command arguments remain outside Git at `%TEMP%/cafe-fin-contracts-desktop-render-qa-20261108/inspect_http_outputs.py`. Its output is `render-qa-metadata.json` beside the final manifest. It verifies actual files, inspects PDF font operators/embedded fonts/A4 and DOCX section size/identifier, rasterizes PDFs and captures each bundled-only DOCX attempt.

```powershell
& '<bundled-python>' -X utf8 "$env:TEMP/cafe-fin-contracts-desktop-render-qa-20261108/inspect_http_outputs.py" "$env:TEMP/cafe-fin-contracts-desktop-source-20261108-efa2d9ee67-output"
# PASS metadata/hash/font/A4 checks and PDF rasterization; DOCX attempt status NOT RUN.
```

Frozen source-matched sidecar, native GUI/WebView2, physical WAN-off and a clean Windows client are **NOT RUN by this subtask**. A loopback source process plus PDF raster review does not replace those acceptance gates. Collector-disabled configuration is not claimed as a physical Internet-disconnection test.
