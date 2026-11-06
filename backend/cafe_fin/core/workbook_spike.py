"""Bounded, synthetic workbook proof. Accounting owns production staging/import."""

import io
import threading
import zipfile
from datetime import datetime
from xml.etree import ElementTree

from openpyxl import Workbook, load_workbook

from .errors import CoreError

SHEET, ROWS = "Tổng hợp", 10000
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def synthetic_workbook(*, rows: int = ROWS, opaque_macro_marker: bool = False) -> bytes:
    if not 1 <= rows <= ROWS:
        raise ValueError("synthetic spike is limited to 10,000 rows")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET
    sheet.append(["Mã", "Mô tả", "Ngày", "Số tiền dạng text", "Công thức chưa tính"])
    for index in range(rows):
        source_row = index + 2
        sheet.append(
            [
                f"{index + 1:08d}",
                "Cà phê tổng hợp — dữ liệu thử",
                datetime(2026, 11, 6),
                "92233720368547758.07",
                f"=SUM(D{source_row}:D{source_row + 1})",
            ]
        )
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    # Stable source hash across restarts; ZIP and modified timestamps are normalized.
    normalized = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(output.getvalue())) as source,
        zipfile.ZipFile(normalized, "w") as target,
    ):
        for name in sorted(source.namelist()):
            content = source.read(name)
            if name == "docProps/core.xml":
                root = ElementTree.fromstring(content)
                for node in root:
                    if node.tag.rsplit("}", 1)[-1] in {"created", "modified"}:
                        node.text = "2026-11-06T00:00:00Z"
                content = ElementTree.tostring(root, encoding="utf-8")
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 6, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, content)
        if opaque_macro_marker:
            # Deliberately not executable VBA: only an opaque synthetic archive member.
            target.writestr("xl/vbaProject.bin", b"CAFE_FIN_SYNTHETIC_NON_EXECUTABLE_MARKER")
            target.writestr(
                "xl/externalLinks/externalLink1.xml",
                '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
            )
    return normalized.getvalue()


def preview_workbook(content: bytes, *, page: int, page_size: int) -> dict:
    if page < 1 or not 1 <= page_size <= 500 or len(content) > 4 * 1024**2:
        raise CoreError("SPIKE_LIMIT", "Bản thử chỉ hỗ trợ trang tối đa 500 dòng và tệp 4 MiB.")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 32 * 1024**2:
            raise CoreError(
                "WORKBOOK_EXPANSION_LIMIT", "Workbook vượt giới hạn giải nén của bản thử."
            )
        if len(archive.infolist()) > 100:
            raise CoreError("WORKBOOK_ENTRY_LIMIT", "Workbook có quá nhiều thành phần cho bản thử.")
    # No formula evaluation, VBA execution, external link resolution or source save.
    workbook = load_workbook(
        io.BytesIO(content), read_only=True, data_only=False, keep_links=False, keep_vba=False
    )
    try:
        sheet = workbook[SHEET]
        if sheet.max_row > ROWS + 1 or sheet.max_column != 5:
            raise CoreError("SPIKE_LIMIT", "Bản thử chỉ hỗ trợ mẫu tổng hợp 10.000 dòng, 5 cột.")
        total, items = sheet.max_row - 1, []
        start, end = (page - 1) * page_size + 2, min(page * page_size + 1, sheet.max_row)
        if start <= end:
            for cells in sheet.iter_rows(min_row=start, max_row=end, max_col=5):
                code, description, occurred, amount, formula = cells
                issues = [
                    {
                        "sheet": SHEET,
                        "row": formula.row,
                        "column": "E",
                        "cell": formula.coordinate,
                        "code": "FORMULA_NOT_EVALUATED",
                        "message": "Công thức nguồn được giữ dạng text; bản thử không tính kết quả cache.",
                    }
                ]
                if amount.row == 2:
                    issues.append(
                        {
                            "sheet": SHEET,
                            "row": 2,
                            "column": "D",
                            "cell": "D2",
                            "code": "EXACT_TEXT_AMOUNT",
                            "message": "Số lớn được giữ nguyên dạng text trong mẫu tổng hợp.",
                        }
                    )
                items.append(
                    {
                        "id": str(code.row - 1),
                        "source_sheet": SHEET,
                        "source_row": code.row,
                        "code": str(code.value),
                        "description": description.value,
                        "occurred_on": occurred.value.date().isoformat(),
                        "amount": amount.value,
                        "formula": formula.value,
                        "issues": issues,
                    }
                )
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        workbook.close()


class WorkbookSpike:
    def __init__(self, files):
        self.files = files
        self._content = None
        self._lock = threading.Lock()

    def page(self, *, actor: str, page: int, page_size: int, authorize=None):
        with self._lock:
            if self._content is None:
                self._content = synthetic_workbook()
            content = self._content
        stored = self.files.put(
            io.BytesIO(content),
            category="workbooks",
            original_name="foundation-synthetic.xlsx",
            media_type=MIME,
            actor=actor,
            request_key="foundation-grid-source-v1",
            authorize=authorize,
        )
        result = preview_workbook(content, page=page, page_size=page_size)
        return result | {
            "source_file_id": stored.id,
            "source_sha256": stored.sha256,
            "projection_note": "Bản thử 10.000 dòng; không phải benchmark import lớn.",
        }
