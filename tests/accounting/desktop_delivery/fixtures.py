"""Streaming, synthetic desktop sources; generated files always live outside Git.

XLSM carries an opaque inert sentinel, not a valid VBA project or execution test.
Run: python tests/accounting/desktop_delivery/fixtures.py --root <fresh-temp-path>
"""

import argparse
import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

VERSION = "accounting-desktop-fixtures-v1"
MAX_ROWS = 1_048_573  # Header is worksheet row 3.
SENTINEL = b"CAFE_FIN_OPAQUE_INERT_SENTINEL_V1\nNOT_A_VALID_VBA_PROJECT\n"
IDS = ("code", "day", "amount", "quantity", "category", "note", "currency", "reference")
HEADERS = ("Mã", "Ngày", "Thu", "Khối lượng", "Loại", "Ghi chú", "Tiền tệ", "Tham chiếu")
MAPPING = dict(zip(IDS, "ABCDEFGH", strict=True))
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
BOOK = {
    "name": "Sổ cà phê tổng hợp desktop",
    "columns": [
        {"id": "code", "name": HEADERS[0], "kind": "text", "required": True},
        {"id": "day", "name": HEADERS[1], "kind": "date", "required": True},
        {"id": "amount", "name": HEADERS[2], "kind": "money", "precision": 19, "required": True},
        {"id": "quantity", "name": HEADERS[3], "kind": "decimal", "scale": 3, "required": True},
        {
            "id": "category",
            "name": HEADERS[4],
            "kind": "choice",
            "choices": ["Robusta", "Arabica"],
            "required": True,
        },
        {"id": "note", "name": HEADERS[5], "kind": "text"},
        {
            "id": "currency",
            "name": HEADERS[6],
            "kind": "choice",
            "choices": ["VND"],
            "required": True,
        },
        {"id": "reference", "name": HEADERS[7], "kind": "text"},
    ],
    "semantics": {
        "date_column": "day",
        "income_column": "amount",
        "currency_column": "currency",
        "duplicate_columns": ["code", "day"],
    },
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _amount(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def _record(index):
    origin = index - 1 if index % 100 == 2 else index
    cents = 10000 + origin % 100000
    day = (date(2026, 1, 1) + timedelta(days=origin % 28)).isoformat()
    milli = 1000 + origin % 1000
    note = f'Cà phê Việt Nam, lô "{origin}"'
    if origin % 17 == 0:
        note += "\nDòng ghi chú thứ hai"
    if origin % 113 == 0:
        note = "=literal harmless desktop text"
    values = [
        f"{origin:012d}",
        day,
        _amount(cents),
        f"{milli // 1000}.{milli % 1000:03d}",
        "Robusta" if origin % 2 else "Arabica",
        note,
        "VND",
        f"REF-{origin:012d}",
    ]
    fault, repair = None, {}
    if index % 100 == 0:
        fault, repair = "amount", {"amount": values[2]}
        values[2] = "NOT_A_NUMBER"
    elif index % 200 == 150:
        fault, repair = "date", {"day": values[1]}
        values[1] = "2026-02-30"
    elif index % 1000 in (25, 75):
        fault = "unsupported" if index % 1000 == 25 else "external"
        repair = {"amount": values[2]}
        values[2] = (
            "=UNSUPPORTED_DESKTOP(1)" if fault == "unsupported" else "='[outside.xlsx]External'!C4"
        )
    return values, fault, repair, cents


def _artifact(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _entry(name):
    info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _text_cell(column, row, value):
    return f'<c r="{column}{row}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def _workbook(path, rows, macro=False):
    """Write one row at a time; no shared-string table or in-memory row list."""
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:

        def put(name, text):
            archive.writestr(_entry(name), text.encode("utf-8"))

        workbook_type = (
            "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
            if macro
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        )
        types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        for part, kind in (
            ("workbook.xml", workbook_type),
            (
                "styles.xml",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
            ),
            (
                "worksheets/sheet1.xml",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            ),
            (
                "worksheets/sheet2.xml",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
            ),
        ):
            types += f'<Override PartName="/xl/{part}" ContentType="{kind}"/>'
        if macro:
            types += '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
        put("[Content_Types].xml", types + "</Types>")
        put(
            "_rels/.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        put(
            "xl/workbook.xml",
            f'<workbook xmlns="{NS}" xmlns:r="{REL}"><workbookPr date1904="0"/><sheets><sheet name="Hướng dẫn" sheetId="1" r:id="rId1"/><sheet name="Sổ cà phê" sheetId="2" r:id="rId2"/></sheets></workbook>',
        )
        relationships = f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="{REL}/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="{REL}/styles" Target="styles.xml"/>'
        if macro:
            relationships += '<Relationship Id="rId4" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="vbaProject.bin"/>'
        put("xl/_rels/workbook.xml.rels", relationships + "</Relationships>")
        put(
            "xl/styles.xml",
            f'<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="1"><fill><patternFill patternType="none"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" applyNumberFormat="1"/></cellXfs></styleSheet>',
        )
        put(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{NS}"><dimension ref="A1:A2"/><sheetData><row r="1">{_text_cell("A", 1, "DỮ LIỆU TỔNG HỢP — chọn sheet 2, tiêu đề dòng 3")}</row><row r="2">{_text_cell("A", 2, "XLSM chỉ chứa sentinel vô hại; không phải dự án VBA hợp lệ.")}</row></sheetData></worksheet>',
        )
        with archive.open(_entry("xl/worksheets/sheet2.xml"), "w", force_zip64=True) as target:

            def write(text):
                target.write(text.encode("utf-8"))

            write(
                f'<worksheet xmlns="{NS}"><dimension ref="A1:H{rows + 3}"/><sheetData><row r="1">{_text_cell("A", 1, "DỮ LIỆU TỔNG HỢP DESKTOP")}</row><row r="2"/><row r="3">'
            )
            write(
                "".join(_text_cell(c, 3, h) for c, h in zip("ABCDEFGH", HEADERS, strict=True))
                + "</row>"
            )
            for index in range(1, rows + 1):
                values, fault, _, _ = _record(index)
                row = index + 3
                write(f'<row r="{row}">')
                for column, value in zip("ABCDEFGH", values, strict=True):
                    if column == "C" and fault in ("unsupported", "external"):
                        write(f'<c r="C{row}"><f>{escape(value[1:])}</f><v>999999.99</v></c>')
                    elif column == "B" and fault != "date":
                        serial = (date.fromisoformat(value) - date(1899, 12, 30)).days
                        write(f'<c r="B{row}" s="1"><v>{serial}</v></c>')
                    elif column == "D" or (column == "C" and fault != "amount"):
                        write(f'<c r="{column}{row}"><v>{value}</v></c>')
                    else:
                        write(_text_cell(column, row, value))
                write("</row>")
            write("</sheetData></worksheet>")
        if macro:
            archive.writestr(_entry("xl/vbaProject.bin"), SENTINEL)


def generate_fixture_kit(root: Path, rows: int = 1000) -> dict:
    """Create a fresh external kit; JSONL repair values use stable column IDs.

    Returned manifest_artifact hashes manifest.json; that field is deliberately
    absent from the on-disk manifest to avoid a self-referential checksum.
    """
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise ValueError(f"rows must be an integer from 1 through {MAX_ROWS}")
    root = Path(root).expanduser().resolve()
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise ValueError("fixture root must be outside every Git worktree")
    if root.exists():
        raise ValueError("fixture root must be fresh and nonexistent")
    root.mkdir(parents=True)
    profiles = {
        kind: {
            "sheet_id": "csv" if kind == "csv" else "2",
            "header_row": 3,
            "start_row": 4,
            "encoding": "utf-8-sig",
            "delimiter": ",",
            "date_format": "%Y-%m-%d",
            "decimal_separator": ".",
            "thousands_separator": "",
            "skip_blank": True,
            "hidden_rows": "include",
            "merged_cells": "reject",
        }
        for kind in ("csv", "xlsx", "xlsm")
    }
    previews = {"csv": [], "xlsx": []}
    duplicate_preview, counts = (
        [],
        {"invalid": 0, "duplicates": 0, "valid_cents": 0, "all_cents": 0},
    )
    sidecars = {}
    from contextlib import ExitStack

    with ExitStack() as stack:
        handles = {}
        for kind in ("csv", "xlsx"):
            for purpose in ("issues", "repairs"):
                path = root / f"{kind}-{purpose}.jsonl"
                sidecars[kind, purpose] = path
                handles[kind, purpose] = stack.enter_context(
                    path.open("w", encoding="utf-8", newline="\n")
                )
        groups_path = root / "duplicate-groups.jsonl"
        groups = stack.enter_context(groups_path.open("w", encoding="utf-8", newline="\n"))
        source = stack.enter_context(
            (root / "desktop-source.csv").open("w", encoding="utf-8-sig", newline="")
        )
        writer = csv.writer(source, lineterminator="\r\n")
        writer.writerow(["DỮ LIỆU TỔNG HỢP DESKTOP"])
        writer.writerow([])
        writer.writerow(HEADERS)
        for index in range(1, rows + 1):
            values, fault, repair, cents = _record(index)
            writer.writerow(values)
            counts["all_cents"] += cents
            if index % 100 == 2:
                counts["duplicates"] += 1
                group = {"source_rows": [index + 2, index + 3], "code": values[0]}
                groups.write(_json(group) + "\n")
                if len(duplicate_preview) < 16:
                    duplicate_preview.append(group)
            if fault:
                counts["invalid"] += 1
                column = "B" if fault == "date" else "C"
                for kind in ("csv", "xlsx"):
                    code = {
                        "amount": "INVALID_DECIMAL",
                        "date": "DATE_INVALID",
                        "unsupported": "FORMULA_UNSUPPORTED",
                        "external": "FORMULA_EXTERNAL_REFERENCE",
                    }[fault]
                    if kind == "csv" and fault in ("unsupported", "external"):
                        code = "INVALID_DECIMAL"
                    sheet = "csv" if kind == "csv" else "2"
                    issue = {
                        "source_sheet": sheet,
                        "source_row": index + 3,
                        "source_column": column,
                        "column_id": "day" if fault == "date" else "amount",
                        "cell": f"{column}{index + 3}",
                        "code": code,
                        "severity": "error",
                    }
                    handles[kind, "issues"].write(_json(issue) + "\n")
                    handles[kind, "repairs"].write(
                        _json({"source_sheet": sheet, "source_row": index + 3, "values": repair})
                        + "\n"
                    )
                    if len(previews[kind]) < 32:
                        previews[kind].append(issue)
            else:
                counts["valid_cents"] += cents
    _workbook(root / "desktop-source.xlsx", rows)
    _workbook(root / "desktop-source.xlsm", rows, macro=True)
    valid = rows - counts["invalid"]
    expected = {
        "source_rows": rows,
        "invalid": counts["invalid"],
        "valid": valid,
        "duplicate_groups": counts["duplicates"],
        "duplicate_warning_rows": counts["duplicates"] * 2,
        "eligible_before_decisions": valid - counts["duplicates"] * 2,
    }
    files = {}
    for kind in ("csv", "xlsx", "xlsm"):
        sidecar_kind = "csv" if kind == "csv" else "xlsx"
        scenarios = {
            "keep_all": {
                "first_published": valid,
                "final_published": rows,
                "excluded": 0,
                "first_income": _amount(counts["valid_cents"]),
                "final_income": _amount(counts["all_cents"]),
            }
        }
        if rows >= 2:
            scenarios["skip_first_duplicate"] = {
                "duplicate_source_row": 5,
                "first_published": valid - 1,
                "final_published": rows - 1,
                "excluded": 1,
                "first_income": _amount(counts["valid_cents"] - 10001),
                "final_income": _amount(counts["all_cents"] - 10001),
            }
        files[kind] = _artifact(root / f"desktop-source.{kind}") | {
            "file_type": kind,
            "profile": profiles[kind],
            "mapping": MAPPING,
            "sheet_name": "csv" if kind == "csv" else "Sổ cà phê",
            "expected": expected,
            "scenarios": scenarios,
            "expected_issues": previews[sidecar_kind],
            "expected_issues_preview_complete": counts["invalid"] <= 32,
            "issue_jsonl": _artifact(sidecars[sidecar_kind, "issues"]),
            "repair_jsonl": _artifact(sidecars[sidecar_kind, "repairs"]),
        }
    files["xlsm"]["macro_fixture"] = {
        "kind": "opaque inert vbaProject sentinel",
        "valid_vba_project": False,
        "execution_claim": False,
        "entry": "xl/vbaProject.bin",
        "sha256": hashlib.sha256(SENTINEL).hexdigest(),
    }
    manifest_path = root / "manifest.json"
    manifest = {
        "kit_version": VERSION,
        "synthetic_only": True,
        "rows": rows,
        "book": BOOK,
        "files": files,
        "duplicate_groups": _artifact(groups_path),
        "duplicate_groups_preview": duplicate_preview,
        "manifest_path": str(manifest_path),
        "scope": "Streaming synthetic mini kit. No macro execution or packaged desktop performance claim.",
    }
    manifest_path.write_text(_json(manifest) + "\n", encoding="utf-8", newline="\n")
    return manifest | {"manifest_artifact": _artifact(manifest_path)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=1000)
    args = parser.parse_args()
    result = generate_fixture_kit(args.root, args.rows)
    print(
        _json(
            {
                "kit_version": result["kit_version"],
                "manifest_artifact": result["manifest_artifact"],
                "rows": result["rows"],
            }
        )
    )
