"""Bounded, read-only source projections. No formulas or workbook code are executed.

Numeric OOXML tokens are strings, never binary floats. CSV defaults are the explicit
UTF-8-with-optional-BOM/comma profile, not a guessed encoding or delimiter.
"""

from __future__ import annotations

import csv
import posixpath
import re
import sqlite3
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Callable, Iterator
from xml.etree.ElementTree import TreeBuilder

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format

MAX_UNPACKED_BYTES = 4 * 1024**3
MAX_ZIP_ENTRIES = 20_000
MAX_COMPRESSION_RATIO = 1000
MAX_CELL_CHARS = 32_767
MAX_ROW_BYTES = 256 * 1024
MAX_COLUMNS = 256
MAX_XLSX_ROWS = 1_048_576
MAX_METADATA_BYTES = 8 * 1024**2
MAX_STYLES = 65_536
MAX_SHEETS = 1024
MAX_CSV_RECORD_CHARS = MAX_COLUMNS * (MAX_CELL_CHARS + 3)
MAX_XML_DEPTH = 64
MAX_CELL_XML_NODES = 4096
MAX_ROW_XML_NODES = 16_384
MAX_MERGED_RANGES = 65_536
CANCEL_CHECK_INTERVAL = 1024
_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?\Z")
_CELL = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})\Z")
_EXTERNAL = re.compile(r"\[|\||(?:WEBSERVICE|HYPERLINK|RTD|DDE|CALL|REGISTER)\s*\(", re.I)


class ParserError(ValueError):
    """Stable, safe error without source contents or filesystem paths."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SourceRow:
    sheet_id: str
    sheet_name: str
    source_row: int
    values: dict[str, object]
    formulas: dict[str, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


def _fail(code: str, message: str) -> None:
    raise ParserError(code, message)


def _checked_text(value: str | None) -> str:
    value = value or ""
    if len(value) > MAX_CELL_CHARS:
        _fail("CELL_LIMIT", "Nội dung ô vượt giới hạn 32767 ký tự.")
    return value


def _check_row_size(values, formulas=None):
    """Bound combined UTF-8 cell values and source expressions before yielding.

    Cached numeric tokens already occur in values; their provenance metadata is
    not counted a second time. Chunk/storage overhead has its own job budget.
    """
    size = 0
    for value in values.values():
        if value is not None:
            size += len(str(value).encode("utf-8"))
            if size > MAX_ROW_BYTES:
                _fail("ROW_LIMIT", "Tổng nội dung dòng vượt giới hạn 256 KiB UTF-8.")
    for formula in (formulas or {}).values():
        text = formula.get("formula_text")
        if text:
            size += len(text.encode("utf-8"))
            if size > MAX_ROW_BYTES:
                _fail("ROW_LIMIT", "Tổng nội dung dòng vượt giới hạn 256 KiB UTF-8.")


def _letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _coordinate(value: str) -> tuple[str, int, int]:
    match = _CELL.fullmatch(value)
    if not match:
        _fail("WORKBOOK_STRUCTURE", "Tọa độ ô không hợp lệ.")
    letter, row_text = match.groups()
    column = 0
    for char in letter:
        column = column * 26 + ord(char) - 64
    row = int(row_text)
    if column > MAX_COLUMNS or row > MAX_XLSX_ROWS:
        _fail("WORKSHEET_LIMIT", "Vùng dữ liệu vượt giới hạn dòng hoặc 256 cột.")
    return letter, row, column


class _BoundedTreeBuilder(TreeBuilder):
    def __init__(self):
        super().__init__()
        self.stack = []

    def start(self, tag, attrs):
        if self.stack and self.stack[-1][0] not in ("c", "si", "row"):
            self.stack[-1][1] = 0
        if len(self.stack) >= MAX_XML_DEPTH or len(attrs) > 64:
            _fail("XML_RESOURCE_LIMIT", "XML vượt giới hạn độ sâu hoặc thuộc tính.")
        for value in attrs.values():
            _checked_text(value)
        for scope in self.stack:
            if scope[0] in ("c", "si", "row"):
                scope[2] += 1
                limit = MAX_ROW_XML_NODES if scope[0] == "row" else MAX_CELL_XML_NODES
                if scope[2] > limit:
                    _fail("XML_RESOURCE_LIMIT", "Ô XML có quá nhiều thành phần.")
                if tag.rsplit("}", 1)[-1] == "c" and scope[0] == "row":
                    scope[3] += 1
                    if scope[3] > MAX_COLUMNS:
                        _fail("WORKSHEET_LIMIT", "Dòng worksheet vượt giới hạn 256 ô.")
        self.stack.append([tag.rsplit("}", 1)[-1], 0, 0, 0])
        return super().start(tag, attrs)

    def data(self, data):
        for scope in self.stack:
            if scope is self.stack[-1] or scope[0] in ("c", "si", "row"):
                scope[1] += len(data)
                limit = MAX_CSV_RECORD_CHARS if scope[0] == "row" else MAX_CELL_CHARS
                if scope[1] > limit:
                    _fail("CELL_LIMIT", "Nội dung XML vượt giới hạn ô.")
        return super().data(data)

    def end(self, tag):
        self.stack.pop()
        return super().end(tag)


def _xml_parser():
    return SafeXML.DefusedXMLParser(
        target=_BoundedTreeBuilder(),
        forbid_dtd=True,
        forbid_entities=True,
        forbid_external=True,
    )


def _checkpoint(check_cancelled):
    if check_cancelled is not None:
        check_cancelled()


def _xml_events(stream, *, check_cancelled=None):
    _checkpoint(check_cancelled)
    try:
        stack = []
        events = SafeXML.iterparse(stream, events=("start", "end"), parser=_xml_parser())
        for count, (event, element) in enumerate(events, 1):
            if count % CANCEL_CHECK_INTERVAL == 0:
                _checkpoint(check_cancelled)
            if event == "start":
                stack.append(element)
            yield event, element
            if event == "end":
                stack.pop()
                # Preserve each complete row/string until its consumer reads it;
                # discard arbitrary extensions too, so inert XML cannot accumulate.
                if not any(node.tag.rsplit("}", 1)[-1] in ("row", "si") for node in stack):
                    element.clear()
                    if stack:
                        try:
                            stack[-1].remove(element)
                        except ValueError:
                            pass  # The row consumer may already have cleared its parent.
        _checkpoint(check_cancelled)
    except (DefusedXmlException, SafeXML.ParseError) as exc:
        raise ParserError("UNSAFE_XML", "XML không hợp lệ hoặc có nội dung bị cấm.") from exc


def _metadata(archive: zipfile.ZipFile, name: str):
    if name not in archive.namelist():
        _fail("WORKBOOK_STRUCTURE", "Thiếu thành phần workbook bắt buộc.")
    if archive.getinfo(name).file_size > MAX_METADATA_BYTES:
        _fail("METADATA_LIMIT", "Metadata workbook vượt giới hạn.")
    with archive.open(name) as stream:
        try:
            return SafeXML.parse(stream, parser=_xml_parser()).getroot()
        except (DefusedXmlException, SafeXML.ParseError) as exc:
            raise ParserError("UNSAFE_XML", "XML metadata không an toàn.") from exc


@contextmanager
def _archive(path):
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                _fail("ZIP_ENTRY_LIMIT", "Tệp có quá nhiều thành phần ZIP.")
            names = set()
            total = 0
            for entry in entries:
                name = entry.filename
                if (
                    name in names
                    or "\\" in name
                    or name.startswith("/")
                    or any(part == ".." for part in name.split("/"))
                ):
                    _fail("ZIP_STRUCTURE", "Tên thành phần ZIP không hợp lệ hoặc trùng lặp.")
                names.add(name)
                total += entry.file_size
                if total > MAX_UNPACKED_BYTES:
                    _fail("ZIP_SIZE_LIMIT", "Tổng dung lượng giải nén vượt 4 GiB.")
                if entry.file_size > max(entry.compress_size, 1) * MAX_COMPRESSION_RATIO:
                    _fail("ZIP_RATIO_LIMIT", "Tỉ lệ nén ZIP vượt giới hạn an toàn.")
                if entry.flag_bits & 1:
                    _fail("ZIP_ENCRYPTED", "Không hỗ trợ workbook mã hóa.")
            yield archive
    except (zipfile.BadZipFile, KeyError, EOFError, RuntimeError) as exc:
        raise ParserError("INVALID_WORKBOOK", "Không đọc được cấu trúc workbook.") from exc


def _book(archive):
    workbook = _metadata(archive, "xl/workbook.xml")
    relationships = _metadata(archive, "xl/_rels/workbook.xml.rels")
    targets = {}
    for relation in relationships:
        if relation.get("TargetMode", "Internal") == "External":
            continue
        target = relation.get("Target", "")
        if "\\" in target or ":" in target:
            _fail("WORKBOOK_STRUCTURE", "Đường dẫn worksheet không hợp lệ.")
        target = posixpath.normpath(
            target.lstrip("/") if target.startswith("/") else "xl/" + target
        )
        if not target.startswith("xl/") or target not in archive.namelist():
            _fail("WORKBOOK_STRUCTURE", "Worksheet không nằm trong workbook.")
        targets[relation.get("Id")] = (target, relation.get("Type", ""))
    props = workbook.find(f"{{{_MAIN}}}workbookPr")
    epoch = "1904" if props is not None and props.get("date1904") in ("1", "true") else "1900"
    sheets = []
    seen_ids = set()
    for sheet in workbook.findall(f"{{{_MAIN}}}sheets/{{{_MAIN}}}sheet"):
        identifier = sheet.get("sheetId", "")
        relation = targets.get(sheet.get(f"{{{_REL}}}id"))
        if not identifier or identifier in seen_ids or relation is None:
            _fail("WORKBOOK_STRUCTURE", "Định danh worksheet không hợp lệ.")
        seen_ids.add(identifier)
        if not relation[1].endswith("/worksheet"):
            continue  # Chartsheets are inert and are not importable sheets.
        sheets.append(
            {
                "id": identifier,
                "name": _checked_text(sheet.get("name")),
                "epoch": epoch,
                "state": sheet.get("state", "visible"),
                "path": relation[0],
            }
        )
    if not sheets or len(sheets) > MAX_SHEETS:
        _fail("WORKBOOK_STRUCTURE", "Số worksheet không hợp lệ.")
    return sheets


def _scan_sheet(archive, sheet, *, include_merges=False, check_cancelled=None):
    max_row = max_column = merged_count = row_count = 0
    last_row = 0
    sheet_data = merge_cells = None
    merges = []
    with archive.open(sheet["path"]) as stream:
        for event, element in _xml_events(stream, check_cancelled=check_cancelled):
            if event == "start" and element.tag == f"{{{_MAIN}}}sheetData":
                sheet_data = element
            if event == "start" and element.tag == f"{{{_MAIN}}}mergeCells":
                merge_cells = element
            if event != "end":
                continue
            local = element.tag.rsplit("}", 1)[-1]
            if local == "row":
                try:
                    row = int(element.get("r", "0"))
                except ValueError:
                    _fail("WORKBOOK_STRUCTURE", "Số dòng worksheet không hợp lệ.")
                if row <= last_row or row > MAX_XLSX_ROWS:
                    _fail("WORKSHEET_LIMIT", "Dòng worksheet trùng hoặc vượt giới hạn.")
                last_row = row
                row_count += 1
                max_row = max(max_row, row)
                previous_column = 0
                for cell in element.findall(f"{{{_MAIN}}}c"):
                    _, cell_row, column = _coordinate(cell.get("r", ""))
                    if cell_row != row or column <= previous_column:
                        _fail("WORKBOOK_STRUCTURE", "Ô worksheet sai dòng hoặc trùng cột.")
                    previous_column = column
                    max_column = max(max_column, column)
                element.clear()
                if sheet_data is not None:
                    sheet_data.clear()
            elif local == "mergeCell":
                endpoints = element.get("ref", "").split(":")
                if len(endpoints) != 2:
                    _fail("WORKBOOK_STRUCTURE", "Vùng ô gộp không hợp lệ.")
                _, first_row, first_column = _coordinate(endpoints[0])
                _, last_merged_row, last_column = _coordinate(endpoints[1])
                if first_row > last_merged_row or first_column > last_column:
                    _fail("WORKBOOK_STRUCTURE", "Vùng ô gộp bị đảo ngược.")
                merged_count += 1
                if merged_count > MAX_MERGED_RANGES:
                    _fail("MERGED_CELL_LIMIT", "Worksheet có quá nhiều vùng ô gộp.")
                if include_merges:
                    merges.append((first_row, last_merged_row, first_column, last_column))
                element.clear()
                if merge_cells is not None:
                    merge_cells.clear()
            elif local == "sheetData":
                element.clear()
    result = {
        **{k: v for k, v in sheet.items() if k != "path"},
        "max_row": max_row,
        "max_column": max_column,
        "stored_row_count": row_count,
        "merged_cell_ranges": merged_count,
        "dimensions_verified": True,
    }
    if include_merges:
        result["_merges"] = sorted(merges)
    return result


def _file_type(filename):
    extension = Path(filename).suffix.lower()
    if extension not in (".csv", ".xlsx", ".xlsm"):
        _fail("UNSUPPORTED_FILE_TYPE", "Chỉ hỗ trợ CSV, XLSX và XLSM.")
    return extension[1:]


def manifest(path, filename, *, check_cancelled: Callable[[], None] | None = None) -> dict:
    """Inspect actual worksheet positions, never trusting a cached dimension attribute."""
    _checkpoint(check_cancelled)
    file_type = _file_type(filename)
    if file_type == "csv":
        _checkpoint(check_cancelled)
        return {
            "file_type": "csv",
            "sheets": [
                {
                    "id": "csv",
                    "name": "CSV",
                    "max_row": None,
                    "max_column": None,
                    "epoch": None,
                    "dimensions_verified": False,
                }
            ],
            "csv_defaults": {"encoding": "utf-8-sig", "delimiter": ","},
        }
    with _archive(path) as archive:
        result = {
            "file_type": file_type,
            "sheets": [
                _scan_sheet(archive, sheet, check_cancelled=check_cancelled)
                for sheet in _book(archive)
            ],
        }
    _checkpoint(check_cancelled)
    return result


def _profile(profile):
    def integer(name, default, minimum):
        value = profile.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            _fail("INVALID_PROFILE", "Phạm vi dòng trong hồ sơ không hợp lệ.")
        return value

    header = integer("header_row", 1, 0)
    start = integer("start_row", header + 1, 1)
    end = profile.get("end_row")
    if end is not None:
        end = integer("end_row", end, start)
    hidden = profile.get("hidden_rows", "include")
    merged = profile.get("merged_cells", "reject")
    if hidden not in ("include", "exclude") or merged not in ("reject", "top_left"):
        _fail("INVALID_PROFILE", "Chính sách dòng ẩn hoặc ô gộp không hợp lệ.")
    skip_blank = profile.get("skip_blank", True)
    if not isinstance(skip_blank, bool):
        _fail("INVALID_PROFILE", "Chính sách dòng trống không hợp lệ.")
    return start, end, hidden, merged, skip_blank


class _CSVLines:
    """Bound physical line allocation and the total record consumed by csv.reader."""

    def __init__(self, stream, *, check_cancelled=None):
        self.stream = stream
        self.record_chars = 0
        self.physical_lines = 0
        self.check_cancelled = check_cancelled

    def __iter__(self):
        return self

    def __next__(self):
        self.physical_lines += 1
        if self.physical_lines % CANCEL_CHECK_INTERVAL == 0:
            _checkpoint(self.check_cancelled)
        line = self.stream.readline(MAX_CSV_RECORD_CHARS + 1)
        if not line:
            raise StopIteration
        self.record_chars += len(line)
        if self.record_chars > MAX_CSV_RECORD_CHARS:
            _fail("CSV_RECORD_LIMIT", "Dòng CSV vượt giới hạn tài nguyên.")
        return line


def _csv_rows(path, profile, settings, *, check_cancelled=None):
    _checkpoint(check_cancelled)
    start, end, _, _, skip_blank = settings
    encoding = profile.get("encoding", "utf-8-sig")
    delimiter = profile.get("delimiter", ",")
    if not isinstance(encoding, str) or not encoding:
        _fail("INVALID_PROFILE", "Encoding CSV phải được chọn rõ ràng.")
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in '\r\n\0"':
        _fail("INVALID_PROFILE", "Ký tự phân cột CSV không hợp lệ.")
    if profile.get("sheet_id", "csv") not in ("csv", "1"):
        _fail("SHEET_NOT_FOUND", "Không tìm thấy sheet CSV.")
    try:
        with open(path, "r", encoding=encoding, errors="strict", newline="") as stream:
            lines = _CSVLines(stream, check_cancelled=check_cancelled)
            reader = csv.reader(lines, delimiter=delimiter, strict=True)
            selected_records = reader if end is None else islice(reader, end)
            for row_number, row in enumerate(selected_records, 1):
                if row_number % CANCEL_CHECK_INTERVAL == 0:
                    _checkpoint(check_cancelled)
                lines.record_chars = 0
                if len(row) > MAX_COLUMNS:
                    _fail("WORKSHEET_LIMIT", "CSV vượt giới hạn 256 cột.")
                values = {_letter(i): _checked_text(value) for i, value in enumerate(row, 1)}
                _check_row_size(values)
                if end is not None and row_number > end:
                    break
                if row_number < start or (skip_blank and not any(v != "" for v in values.values())):
                    continue
                yield SourceRow(
                    "csv",
                    "CSV",
                    row_number,
                    values,
                    metadata={"encoding": encoding, "delimiter": delimiter},
                )
        _checkpoint(check_cancelled)
    except (UnicodeError, LookupError) as exc:
        raise ParserError(
            "CSV_ENCODING_REQUIRED", "Chọn encoding CSV phù hợp; không tự đoán mã hóa."
        ) from exc
    except csv.Error as exc:
        raise ParserError(
            "INVALID_CSV", "CSV có ô quá dài hoặc cấu trúc quote không hợp lệ."
        ) from exc


@contextmanager
def _shared_strings(archive, *, temp_dir=None, check_cancelled=None):
    _checkpoint(check_cancelled)
    # A disk-backed index keeps millions of unique shared strings out of process memory.
    with tempfile.TemporaryDirectory(dir=temp_dir, prefix="accounting-xlsx-strings-") as directory:
        connection = sqlite3.connect(str(Path(directory) / "strings.sqlite"))
        try:
            connection.execute("PRAGMA cache_size=-2048")
            connection.execute("CREATE TABLE strings (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
            if "xl/sharedStrings.xml" in archive.namelist():
                index = 0
                with archive.open("xl/sharedStrings.xml") as stream:
                    root = None
                    for event, element in _xml_events(stream, check_cancelled=check_cancelled):
                        if root is None:
                            root = element
                        if event == "end" and element.tag == f"{{{_MAIN}}}si":
                            value = _rich_text(element)
                            connection.execute("INSERT INTO strings VALUES (?, ?)", (index, value))
                            index += 1
                            root.clear()
                _checkpoint(check_cancelled)
                connection.commit()
                _checkpoint(check_cancelled)
            yield connection
        finally:
            connection.close()
    _checkpoint(check_cancelled)


def _rich_text(element):
    parts = []
    total = 0
    # Exclude phonetic guides (rPh) from cell text.
    for child in element:
        texts = (
            [child]
            if child.tag == f"{{{_MAIN}}}t"
            else (child.findall(f"{{{_MAIN}}}t") if child.tag == f"{{{_MAIN}}}r" else [])
        )
        for text in texts:
            value = text.text or ""
            total += len(value)
            if total > MAX_CELL_CHARS:
                _fail("CELL_LIMIT", "Chuỗi workbook vượt giới hạn 32767 ký tự.")
            parts.append(value)
    return "".join(parts)


def _date_styles(archive):
    if "xl/styles.xml" not in archive.namelist():
        return set()
    root = _metadata(archive, "xl/styles.xml")
    custom = {}
    for element in root.findall(f"{{{_MAIN}}}numFmts/{{{_MAIN}}}numFmt"):
        custom[element.get("numFmtId")] = _checked_text(element.get("formatCode"))
    styles = root.findall(f"{{{_MAIN}}}cellXfs/{{{_MAIN}}}xf")
    if len(styles) > MAX_STYLES:
        _fail("STYLE_LIMIT", "Workbook có quá nhiều định dạng ô.")
    result = set()
    for index, style in enumerate(styles):
        identifier = style.get("numFmtId", "0")
        try:
            code = custom.get(identifier, BUILTIN_FORMATS.get(int(identifier), ""))
        except ValueError:
            _fail("WORKBOOK_STRUCTURE", "Mã định dạng ô không hợp lệ.")
        if is_date_format(code):
            result.add(str(index))
    return result


def _cell_value(cell, strings):
    kind = cell.get("t", "n")
    value = cell.find(f"{{{_MAIN}}}v")
    raw = _checked_text(value.text) if value is not None and value.text is not None else None
    if kind == "inlineStr":
        inline = cell.find(f"{{{_MAIN}}}is")
        return _rich_text(inline) if inline is not None else ""
    if raw is None:
        return None
    if kind == "s":
        if not raw.isdecimal() or len(raw) > 12:
            _fail("WORKBOOK_STRUCTURE", "Chỉ mục chuỗi dùng chung không hợp lệ.")
        match = strings.execute("SELECT value FROM strings WHERE id=?", (int(raw),)).fetchone()
        if match is None:
            _fail("WORKBOOK_STRUCTURE", "Không tìm thấy chuỗi dùng chung.")
        return match[0]
    if kind == "b":
        if raw not in ("0", "1"):
            _fail("WORKBOOK_STRUCTURE", "Giá trị boolean workbook không hợp lệ.")
        return raw == "1"
    if kind in ("str", "e", "d"):
        return raw
    if kind not in ("n", "") or not _NUMBER.fullmatch(raw):
        _fail("WORKBOOK_STRUCTURE", "Kiểu hoặc token số workbook không hợp lệ.")
    return raw


def _xlsx_rows(archive, sheet, profile, settings, *, temp_dir=None, check_cancelled=None):
    _checkpoint(check_cancelled)
    start, end, hidden, merged, skip_blank = settings
    info = _scan_sheet(
        archive, sheet, include_merges=merged == "top_left", check_cancelled=check_cancelled
    )
    if merged == "reject" and info["merged_cell_ranges"]:
        _fail("MERGED_CELLS", "Sheet có ô gộp; chọn chính sách chỉ lấy ô góc trên trái.")
    date_styles = _date_styles(archive)
    merges = iter(info.get("_merges", []))
    next_merge = next(merges, None)
    active_merges = []
    with (
        _shared_strings(archive, temp_dir=temp_dir, check_cancelled=check_cancelled) as strings,
        archive.open(sheet["path"]) as stream,
    ):
        sheet_data = None
        for event, element in _xml_events(stream, check_cancelled=check_cancelled):
            if event == "start" and element.tag == f"{{{_MAIN}}}sheetData":
                sheet_data = element
            if event != "end" or element.tag != f"{{{_MAIN}}}row":
                continue
            row_number = int(element.get("r"))
            if end is not None and row_number > end:
                break
            if row_number < start or (
                hidden == "exclude" and element.get("hidden") in ("1", "true")
            ):
                element.clear()
                if sheet_data is not None:
                    sheet_data.clear()
                continue
            values, formulas, dates, errors, numbers = {}, {}, {}, {}, {}
            active_merges = [region for region in active_merges if region[1] >= row_number]
            while next_merge is not None and next_merge[0] <= row_number:
                if next_merge[1] >= row_number:
                    active_merges.append(next_merge)
                next_merge = next(merges, None)
            blocked_columns = set()
            for first_row, _, first_column, last_column in active_merges:
                blocked_columns.update(
                    range(first_column + (row_number == first_row), last_column + 1)
                )
            for cell in element.findall(f"{{{_MAIN}}}c"):
                column, _, column_index = _coordinate(cell.get("r", ""))
                if column_index in blocked_columns:
                    continue
                value = _cell_value(cell, strings)
                values[column] = value
                if cell.get("t", "n") in ("n", "") and isinstance(value, str):
                    numbers[column] = value
                if (
                    cell.get("s", "0") in date_styles
                    and value is not None
                    and cell.get("t", "n") == "n"
                ):
                    dates[column] = {"epoch": sheet["epoch"], "excel_serial": value}
                if cell.get("t") == "d" and value is not None:
                    dates[column] = {"epoch": sheet["epoch"], "iso_date": value}
                if cell.get("t") == "e":
                    errors[column] = value
                formula = cell.find(f"{{{_MAIN}}}f")
                if formula is not None:
                    text = _checked_text(formula.text)
                    status = (
                        "external_reference"
                        if _EXTERNAL.search(text)
                        else ("missing_cache" if value is None else "cache_only")
                    )
                    formulas[column] = {
                        "formula_text": "=" + text if text else None,
                        "cached_value": value,
                        "calculation_status": status,
                        "formula_type": formula.get("t", "normal"),
                        "shared_index": formula.get("si"),
                    }
            _check_row_size(values, formulas)
            should_yield = (
                bool(formulas)
                or not skip_blank
                or any(value is not None and value != "" for value in values.values())
            )
            element.clear()
            if sheet_data is not None:
                sheet_data.clear()
            if should_yield:
                yield SourceRow(
                    sheet["id"],
                    sheet["name"],
                    row_number,
                    values,
                    formulas,
                    {
                        "epoch": sheet["epoch"],
                        "date_cells": dates,
                        "numeric_cells": numbers,
                        "error_cells": errors,
                        "merged_cells": merged,
                    },
                )


def iter_rows(
    path,
    filename,
    profile: dict,
    *,
    temp_dir=None,
    check_cancelled: Callable[[], None] | None = None,
) -> Iterator[SourceRow]:
    """Yield selected stored rows. Header is excluded by default; text dates stay raw.

    Profile date_format is carried by the caller to schema validation: parsing never
    guesses day/month order. OOXML sparse absent rows are not synthesized.
    temp_dir is a trusted internal temporary-storage location, never taken from
    the user-supplied profile. The application passes its imports directory.
    check_cancelled is a trusted cooperative callback. Its exceptions propagate
    unchanged; neither trusted argument is ever read from the user profile.
    """
    _checkpoint(check_cancelled)
    settings = _profile(profile)
    if _file_type(filename) == "csv":
        yield from _csv_rows(path, profile, settings, check_cancelled=check_cancelled)
        _checkpoint(check_cancelled)
        return
    with _archive(path) as archive:
        sheets = _book(archive)
        identifier = str(profile.get("sheet_id", sheets[0]["id"]))
        selected = next((sheet for sheet in sheets if sheet["id"] == identifier), None)
        if selected is None:
            _fail("SHEET_NOT_FOUND", "Không tìm thấy worksheet đã chọn.")
        yield from _xlsx_rows(
            archive, selected, profile, settings, temp_dir=temp_dir, check_cancelled=check_cancelled
        )
    _checkpoint(check_cancelled)
