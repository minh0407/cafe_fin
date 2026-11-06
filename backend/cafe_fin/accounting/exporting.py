"""Streaming derived XLSX, exact numeric XML, never an original-workbook resave."""

from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _letter(index):
    text = ""
    while index:
        index, rem = divmod(index - 1, 26)
        text = chr(65 + rem) + text
    return text


def _text(value):
    return '<is><t xml:space="preserve">' + escape(str(value)) + "</t></is>"


def _cell(coordinate, value, column=None):
    if value is None:
        return f'<c r="{coordinate}"/>'
    kind = column["kind"] if column else "text"
    if kind == "date":
        day = date.fromisoformat(value)
        serial = (day - date(1899, 12, 31)).days + (1 if day >= date(1900, 3, 1) else 0)
        if serial >= 1:
            return f'<c r="{coordinate}" s="1"><v>{serial}</v></c>'
    if kind in ("integer", "decimal", "money", "formula"):
        number = Decimal(value)
        # Excel applies a 15-digit precision model. Higher precision is exact text,
        # clearly disclosed in the derived workbook, not silently truncated.
        digits = len(str(value).lstrip("-").replace(".", "").lstrip("0"))
        if digits <= 15:
            scale = column.get("scale", 0)
            return f'<c r="{coordinate}" s="{scale + 2}"><v>{format(number, "f")}</v></c>'
    # Inline strings cannot become formulas, even when starting =,+,-,@.
    return f'<c r="{coordinate}" t="inlineStr">{_text(value)}</c>'


def write_xlsx(path, columns, rows, check_cancelled=lambda: None):
    """rows yields mappings; no full dataset or shared-string dictionary in RAM."""
    names = []
    count = 0
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        stream = None
        sheet_row = 0
        try:
            for values in rows:
                if stream is None or sheet_row == 1_048_576:
                    if stream:
                        stream.write(b"</sheetData></worksheet>")
                        stream.close()
                    names.append("Dữ liệu " + str(len(names) + 1))
                    stream = archive.open(
                        f"xl/worksheets/sheet{len(names)}.xml", "w", force_zip64=True
                    )
                    stream.write(
                        f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{MAIN}"><sheetData>'.encode()
                    )
                    header = (
                        '<row r="1">'
                        + "".join(
                            _cell(_letter(i) + "1", c["name"]) for i, c in enumerate(columns, 1)
                        )
                        + "</row>"
                    )
                    stream.write(header.encode("utf-8"))
                    sheet_row = 1
                sheet_row += 1
                row = (
                    f'<row r="{sheet_row}">'
                    + "".join(
                        _cell(_letter(i) + str(sheet_row), values.get(c["id"]), c)
                        for i, c in enumerate(columns, 1)
                    )
                    + "</row>"
                )
                stream.write(row.encode("utf-8"))
                count += 1
                if count % 500 == 0:
                    check_cancelled()
            if stream:
                stream.write(b"</sheetData></worksheet>")
                stream.close()
                stream = None
        finally:
            if stream:
                stream.close()
        # Always include explicit fidelity/precision scope, even for an empty dataset.
        names.append("Phạm vi xuất")
        note = "Tệp dẫn xuất từ dữ liệu đã công bố. Không giữ macro, chart, pivot hoặc style nguồn. Số vượt 15 chữ số được xuất dạng text để giữ chính xác. Ngày trước 1900 xuất ISO text. Công thức xuất giá trị đã tính, không chứa nội dung thực thi."
        archive.writestr(
            f"xl/worksheets/sheet{len(names)}.xml",
            f'<worksheet xmlns="{MAIN}"><sheetData><row r="1">{_cell("A1", note)}</row></sheetData></worksheet>',
        )
        sheets = "".join(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, 1)
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{sheets}</sheets></workbook>',
        )
        relationships = "".join(
            f'<Relationship Id="rId{i}" Type="{REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(names) + 1)
        )
        relationships += f'<Relationship Id="styles" Type="{REL}/styles" Target="styles.xml"/>'
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + relationships
            + "</Relationships>",
        )
        archive.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        formats = ["yyyy-mm-dd"] + [
            "0" if scale == 0 else "0." + "0" * scale for scale in range(10)
        ]
        numfmts = "".join(
            f'<numFmt numFmtId="{164 + i}" formatCode="{fmt}"/>' for i, fmt in enumerate(formats)
        )
        xfs = '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' + "".join(
            f'<xf numFmtId="{164 + i}" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
            for i in range(len(formats))
        )
        archive.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{MAIN}"><numFmts count="{len(formats)}">{numfmts}</numFmts><fonts count="1"><font><name val="Calibri"/><sz val="11"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="{len(formats) + 1}">{xfs}</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        )
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(names) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + overrides
            + "</Types>",
        )
    return count
