import hashlib
import tracemalloc
import zipfile
from datetime import datetime

import pytest
from cafe_fin.accounting import parsers
from cafe_fin.accounting.parsers import ParserError, iter_rows, manifest
from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def workbook(tmp_path, rows, *, epoch="1900", suffix=".xlsx", extra=None, tail=""):
    path = tmp_path / ("source" + suffix)
    parts = {
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}">'
            f'<workbookPr date1904="{int(epoch == "1904")}"/>'
            '<sheets><sheet name="Sổ thu chi" sheetId="7" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            f'<worksheet xmlns="{MAIN}"><dimension ref="A1:A1"/>'
            f"<sheetData>{rows}</sheetData>{tail}</worksheet>"
        ),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{MAIN}"><cellXfs count="2">'
            '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
        ),
    }
    parts.update(extra or {})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return path


def test_csv_bom_vietnamese_quotes_newlines_and_leading_zero(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes(
        '\ufeffMã,Ghi chú,Số tiền\r\n000123,"Cà phê, Đắk Lắk\nđợt 2",9007199254740993.01\r\n'.encode()
    )
    result = list(iter_rows(path, path.name, {}))
    assert result[0].source_row == 2
    assert result[0].values == {
        "A": "000123",
        "B": "Cà phê, Đắk Lắk\nđợt 2",
        "C": "9007199254740993.01",
    }
    assert manifest(path, path.name)["csv_defaults"] == {"encoding": "utf-8-sig", "delimiter": ","}


def test_csv_explicit_encoding_delimiter_ranges_and_blank(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes("code;amount\n001;12,50\n;\n002;0\n".encode("utf-16"))
    with pytest.raises(ParserError, match="encoding") as failure:
        list(iter_rows(path, path.name, {}))
    assert failure.value.code == "CSV_ENCODING_REQUIRED"
    rows = list(iter_rows(path, path.name, {"encoding": "utf-16", "delimiter": ";", "end_row": 4}))
    assert [(row.source_row, row.values["A"]) for row in rows] == [(2, "001"), (4, "002")]
    rows = list(
        iter_rows(path, path.name, {"encoding": "utf-16", "delimiter": ";", "skip_blank": False})
    )
    assert rows[1].source_row == 3
    with pytest.raises(ParserError) as failure:
        list(iter_rows(path, path.name, {"encoding": None}))
    assert failure.value.code == "INVALID_PROFILE"


@pytest.mark.parametrize("epoch", ["1900", "1904"])
def test_xlsx_exact_raw_numbers_dates_formula_caches_and_source_hash(tmp_path, epoch):
    path = workbook(
        tmp_path,
        """<row r="1"><c r="A1" t="inlineStr"><is><t>Mã</t></is></c></row>
        <row r="2"><c r="A2" t="inlineStr"><is><t>0009</t></is></c>
        <c r="B2"><v>9007199254740993.0100</v></c>
        <c r="C2" s="1"><v>60.5000000000000001</v></c>
        <c r="D2"><f>SUM(B2,1)</f><v>9007199254740994.0100</v></c>
        <c r="E2"><f>1+1</f><v/></c>
        <c r="F2"><f>'[outside.xlsx]Sheet1'!A1</f><v>42</v></c>
        <c r="G2" t="b"><v>0</v></c></row>""",
        epoch=epoch,
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    info = manifest(path, path.name)
    assert info["sheets"][0]["max_row"] == 2
    assert info["sheets"][0]["max_column"] == 7  # Ignore fraudulent cached dimensions.
    row = next(iter_rows(path, path.name, {"sheet_id": "7"}))
    assert row.values["A"] == "0009"
    assert row.values["B"] == "9007199254740993.0100"
    assert row.values["C"] == "60.5000000000000001"
    assert row.metadata["date_cells"]["C"] == {
        "epoch": epoch,
        "excel_serial": "60.5000000000000001",
    }
    assert row.formulas["D"]["cached_value"] == "9007199254740994.0100"
    assert row.formulas["D"]["calculation_status"] == "cache_only"
    assert row.formulas["E"]["cached_value"] is None
    assert row.formulas["E"]["calculation_status"] == "missing_cache"
    assert row.formulas["F"]["calculation_status"] == "external_reference"
    assert row.values["G"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_xlsm_shared_strings_macros_and_external_relationship_are_inert(tmp_path):
    marker = tmp_path / "macro_was_executed"
    path = workbook(
        tmp_path,
        '<row r="2"><c r="A2" t="s"><v>0</v></c></row>',
        suffix=".xlsm",
        extra={
            "xl/vbaProject.bin": f'CreateObject("WScript.Shell").Run "echo hacked > {marker}"',
            "xl/externalLinks/externalLink1.xml": "<!DOCTYPE x SYSTEM 'https://not-contacted.invalid'><x/>",
            "xl/sharedStrings.xml": f'<sst xmlns="{MAIN}"><si><r><t>000</t></r><r><t>7</t></r><rPh><t>phonetic</t></rPh></si></sst>',
        },
    )
    before = hashlib.sha256(path.read_bytes()).digest()
    assert manifest(path, path.name)["file_type"] == "xlsm"
    assert next(iter_rows(path, path.name, {})).values == {"A": "0007"}
    assert not marker.exists()
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_hidden_blank_ranges_and_merged_cells_policy(tmp_path):
    path = workbook(
        tmp_path,
        """<row r="1"><c r="A1"><v>1</v></c></row>
      <row r="2" hidden="1"><c r="A2"><v>2</v></c></row><row r="3"/>
      <row r="4"><c r="A4"><v>4</v></c></row>""",
        tail='<mergeCells count="1"><mergeCell ref="A4:B4"/></mergeCells>',
    )
    with pytest.raises(ParserError) as failure:
        list(iter_rows(path, path.name, {}))
    assert failure.value.code == "MERGED_CELLS"
    rows = list(iter_rows(path, path.name, {"merged_cells": "top_left", "hidden_rows": "exclude"}))
    assert [(row.source_row, row.values) for row in rows] == [(4, {"A": "4"})]
    rows = list(
        iter_rows(path, path.name, {"merged_cells": "top_left", "skip_blank": False, "end_row": 3})
    )
    assert [row.source_row for row in rows] == [2, 3]


@pytest.mark.parametrize(
    "payload",
    [
        '<!DOCTYPE worksheet [<!ENTITY x "bad">]><worksheet>&x;</worksheet>',
        '<!DOCTYPE worksheet SYSTEM "file:///not-read"><worksheet/>',
        "<worksheet><unclosed></worksheet>",
    ],
)
def test_unsafe_xml_is_rejected(tmp_path, payload):
    path = workbook(tmp_path, "", extra={"xl/worksheets/sheet1.xml": payload})
    with pytest.raises(ParserError) as failure:
        manifest(path, path.name)
    assert failure.value.code == "UNSAFE_XML"


@pytest.mark.parametrize(
    "constant,value,code",
    [
        ("MAX_ZIP_ENTRIES", 1, "ZIP_ENTRY_LIMIT"),
        ("MAX_UNPACKED_BYTES", 1, "ZIP_SIZE_LIMIT"),
        ("MAX_COMPRESSION_RATIO", 1, "ZIP_RATIO_LIMIT"),
    ],
)
def test_zip_limits(tmp_path, monkeypatch, constant, value, code):
    path = workbook(tmp_path, '<row r="2"><c r="A2"><v>10</v></c></row>')
    monkeypatch.setattr(parsers, constant, value)
    with pytest.raises(ParserError) as failure:
        manifest(path, path.name)
    assert failure.value.code == code


@pytest.mark.parametrize("coordinate", ["IW2", "A1048577", "A0"])
def test_coordinate_limits(tmp_path, coordinate):
    path = workbook(tmp_path, f'<row r="2"><c r="{coordinate}"><v>1</v></c></row>')
    with pytest.raises(ParserError):
        list(iter_rows(path, path.name, {}))


def test_xml_string_limit_is_applied_during_parsing(tmp_path):
    path = workbook(
        tmp_path, '<row r="2"><c r="A2" t="inlineStr"><is><t>' + "x" * 32768 + "</t></is></c></row>"
    )
    with pytest.raises(ParserError) as failure:
        list(iter_rows(path, path.name, {}))
    assert failure.value.code == "CELL_LIMIT"


def test_csv_rejects_column_overflow_and_keeps_formula_like_text(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text('code,expression\n0001,=WEBSERVICE("https://no.invalid")\n', encoding="utf-8")
    assert next(iter_rows(path, path.name, {})).values["B"] == '=WEBSERVICE("https://no.invalid")'
    path.write_text(",".join(["x"] * 257), encoding="utf-8")
    with pytest.raises(ParserError) as failure:
        list(iter_rows(path, path.name, {"header_row": 0}))
    assert failure.value.code == "WORKSHEET_LIMIT"


def test_zip_traversal_and_duplicate_entry_are_rejected(tmp_path):
    path = tmp_path / "bad.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../outside", "inert")
    with pytest.raises(ParserError) as failure:
        manifest(path, path.name)
    assert failure.value.code == "ZIP_STRUCTURE"


def test_shared_formula_follower_never_invents_formula_or_zero(tmp_path):
    path = workbook(
        tmp_path,
        """<row r="2"><c r="A2"><f t="shared" si="0" ref="A2:A3">B2+1</f><v>2</v></c></row>
       <row r="3"><c r="A3"><f t="shared" si="0"/><v/></c></row>""",
    )
    rows = list(iter_rows(path, path.name, {}))
    assert rows[1].values["A"] is None
    assert rows[1].formulas["A"] == {
        "formula_text": None,
        "cached_value": None,
        "calculation_status": "missing_cache",
        "formula_type": "shared",
        "shared_index": "0",
    }


def test_real_openpyxl_workbook_is_compatible_without_float_conversion(tmp_path):
    path = tmp_path / "real.xlsx"
    book = Workbook()
    book.epoch = CALENDAR_MAC_1904
    sheet = book.active
    sheet.append(["Mã", "Ngày", "Công thức"])
    sheet.append(["0000009", datetime(2026, 2, 1), "=SUM(1,2)"])
    book.save(path)
    book.close()
    row = next(iter_rows(path, path.name, {}))
    assert row.values["A"] == "0000009"
    assert row.metadata["date_cells"]["B"]["epoch"] == "1904"
    assert isinstance(row.values["B"], str)
    assert row.formulas["C"]["calculation_status"] == "missing_cache"


def test_merged_top_left_omits_non_anchor_cells_without_filling(tmp_path):
    path = workbook(
        tmp_path,
        '<row r="2"><c r="A2"><v>12</v></c><c r="B2"><v>999</v></c></row>'
        '<row r="3"><c r="A3"><v>888</v></c><c r="C3"><v>3</v></c></row>',
        tail='<mergeCells><mergeCell ref="A2:B3"/></mergeCells>',
    )
    rows = list(iter_rows(path, path.name, {"merged_cells": "top_left"}))
    assert [row.values for row in rows] == [{"A": "12"}, {"C": "3"}]


def test_streaming_does_not_retain_xml_rows(tmp_path):
    path = workbook(
        tmp_path,
        "".join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, 20_001)),
    )
    tracemalloc.start()
    try:
        count = sum(1 for _ in iter_rows(path, path.name, {"header_row": 0}))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 20_000
    assert peak < 8 * 1024**2


def test_excess_cells_are_rejected_before_allocating_entire_row(tmp_path):
    path = workbook(
        tmp_path,
        '<row r="2">' + '<c r="A2"><v>1</v></c>' * 257 + "</row>",
    )
    with pytest.raises(ParserError) as failure:
        list(iter_rows(path, path.name, {}))
    assert failure.value.code == "WORKSHEET_LIMIT"


def test_native_numeric_metadata_preserves_exponents_and_date_serials(tmp_path):
    path = workbook(
        tmp_path,
        '<row r="2"><c r="A2"><v>1E-05</v></c>'
        '<c r="B2" t="inlineStr"><is><t>1E-05</t></is></c>'
        '<c r="C2" s="1"><v>45000.000</v></c>'
        '<c r="D2"><f>1/100000</f><v>1E-05</v></c></row>',
        epoch="1904",
    )
    row = next(iter_rows(path, path.name, {}))
    assert row.values == {"A": "1E-05", "B": "1E-05", "C": "45000.000", "D": "1E-05"}
    assert row.metadata["numeric_cells"] == {"A": "1E-05", "C": "45000.000", "D": "1E-05"}
    assert row.metadata["date_cells"]["C"] == {"epoch": "1904", "excel_serial": "45000.000"}
    assert row.formulas["D"]["calculation_status"] == "cache_only"
    assert row.formulas["D"]["cached_value"] == "1E-05"
