# Read bridge v3 display-name consumer

Approved root `206a7e30ce702d8064084c90296aed3634ef28b7` was cherry-picked as
`057b613`; root already owns the original and should skip the local duplicate.
Stable patch ID is identical (`72128dd75bead7dfc204dfb755688b2bd8cdecd1`). No
additional shared edits were made. The lane's older API_CONTRACT parent lacks
root's separate inclusive-date prose line; only the approved v3 delta was applied,
not an unapproved wholesale copy of root's shared document. Root keeps its parent.

## Frozen display metadata

New captures use CONTRACT_VERSION 3 and keep schema_version 2 / the existing
inclusive business-date contract. Source DTO serialization already freezes the
new optional product_name, warehouse_name and book_name. Consumers render only
those explicitly typed name fields; no contact/bank/note/private descriptions are
added or queried. Missing names use existing ordinals in outgoing files/text;
local UI may show its pre-existing source-ID fallback. A movement DTO's name can
supply a missing inventory-line name from the same saved snapshot.

Names never form grouping keys: inventory is still scoped by warehouse/product
IDs, books by book ID. Outgoing labels retain stable ordinals alongside names so
equal names cannot collapse or visually identify two scopes as a single one.
Exact aggregate arithmetic, stock components, deposit subsets, mapping warnings,
independent books, cutoff and versions are unchanged.

PDF passes plain strings to the approved core renderer, which XML-escapes every
Paragraph. HTML preview uses React text, not raw markup. XLSX continues forcing
all cells to explicit text, including formula-like names. Display labels flatten
Unicode control/format characters and whitespace. TXT uses bounded name labels,
at most three named stock groups and five books, then the existing 1800-character
cap/fallback; exact financial amounts are not chopped into different numbers.

Old snapshots are read as their original JSON, never live-name-enriched or
upcast through a new DTO dump. No-name rendering retains its previous ordinal
text/paragraphs. Existing stored exports skip rendering on replay: canonical
file ID/hash/bytes and human-copy receipts remain unchanged. Name changes in a
provider affect a later explicit capture/version, not a saved report or outbox.
No migration, saved-content rewrite, filename/path or sender change is introduced.

## Validation and evidence

PASS **193 cases, 48.21s**, one baseline Starlette/httpx warning, one intentionally
deselected existing 60-second production-timer case (no timer code changed):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting tests/core/test_summary_display_labels.py tests/core/test_read_bridge_v2.py -q -k 'not real_production_60_second_timer'
.\.venv\Scripts\python.exe tests/reporting/generate_evidence.py --named --output "$env:TEMP/cafe-fin-reporting-v3-evidence"
```

The v2-style DTO consumer now expects bridge revision 3 but still exercises the
old no-name representation. New regressions cover ID-distinct scopes with equal
names, movement-only names, real PDF/XLSX/TXT literals such as `<b>&` and formula
text, Unicode control/newline flattening, cap1800, unmapped-data warnings,
provider rename after save, genuine v2 JSON without new name keys, and immutable
old snapshot/hash/export bytes with the renderer deliberately blocked on replay.

The generated three-page Vietnamese PDF was rendered with bundled Poppler and all
three pages visually inspected: literal markup, readable names, no clipping or
missing Vietnamese glyphs. Synthetic files/images remain outside Git. Evidence:

| File | SHA-256 | Bytes |
|---|---|---|
| reporting-demo.pdf | `9914063c558e536d255ac4860b33ec249af71fb50bb897c0a851fca86175cee7` | 37422 |
| reporting-demo.xlsx | `f65232a5c1bb41d5f23ef82ef56945745437bc7064ffca935cc098da5106b18b` | 6548 |
| reporting-demo.txt | `8764528d603e4ac7cd86a5a8e33310a0132fc11d00d6f7d000cd9fff09ff63d9` | 839 |

Frontend names/escaping and picker integration are covered by the companion UI
handoffs. Root still binds real same-transaction producer implementations; these
synthetic consumer tests do not prove production records/accounting coverage.
Live Zalo/native/installer gates remain NOT RUN. No push, merge or READY tag.
