"""Small local document renderer spike, deliberately free of contract domain rules."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .errors import CoreError

ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class DocumentSnapshot:
    """Frozen scalar content. A module saves this snapshot before rendering either format."""

    title: str
    subtitle: str = ""
    fields: tuple[tuple[str, str], ...] = ()
    paragraphs: tuple[str, ...] = ()
    column_headers: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self):
        # Reject mutable containers rather than promise immutability of a frozen
        # dataclass that still holds a caller-owned list.
        if (
            not isinstance(self.title, str)
            or not self.title.strip()
            or not isinstance(self.subtitle, str)
        ):
            raise CoreError("RENDER_SNAPSHOT_INVALID", "Chứng từ cần có tiêu đề.")
        for values in (self.fields, self.paragraphs, self.column_headers, self.rows):
            if not isinstance(values, tuple):
                raise CoreError("RENDER_SNAPSHOT_INVALID", "Snapshot phải bất biến.")
        if any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or any(not isinstance(x, str) for x in pair)
            for pair in self.fields
        ):
            raise CoreError("RENDER_SNAPSHOT_INVALID", "Trường chứng từ không hợp lệ.")
        if any(
            not isinstance(row, tuple)
            or len(row) != len(self.column_headers)
            or any(not isinstance(x, str) for x in row)
            for row in self.rows
        ):
            raise CoreError("RENDER_SNAPSHOT_INVALID", "Số cột trong snapshot không nhất quán.")
        if any(not isinstance(x, str) for x in (*self.paragraphs, *self.column_headers)):
            raise CoreError("RENDER_SNAPSHOT_INVALID", "Nội dung chứng từ không hợp lệ.")
        if (
            len(self.rows) > 5000
            or len(self.column_headers) > 12
            or len(self.canonical_bytes()) > 2 * 1024 * 1024
        ):
            raise CoreError(
                "RENDER_SNAPSHOT_TOO_LARGE",
                "Chứng từ vượt giới hạn render. Hãy chia nhỏ nội dung.",
                status=413,
            )

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class RenderedDocument:
    format: str
    content: bytes
    content_sha256: str
    snapshot_sha256: str


class DocumentRenderer:
    """No shell, Office automation, network, HTML template execution or formula evaluator."""

    def __init__(self):
        for name, file in (
            ("CafeFinNoto", "NotoSans-Regular.ttf"),
            ("CafeFinNotoBold", "NotoSans-Bold.ttf"),
        ):
            if not (ASSETS / file).is_file():
                raise CoreError(
                    "RENDER_FONT_MISSING", "Bộ cài thiếu phông chữ chứng từ.", status=503
                )
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(ASSETS / file)))
        pdfmetrics.registerFontFamily(
            "CafeFinNoto",
            normal="CafeFinNoto",
            bold="CafeFinNotoBold",
            italic="CafeFinNoto",
            boldItalic="CafeFinNotoBold",
        )

    @staticmethod
    def _result(format: str, content: bytes, snapshot: DocumentSnapshot) -> RenderedDocument:
        return RenderedDocument(
            format, content, hashlib.sha256(content).hexdigest(), snapshot.sha256
        )

    def docx(self, snapshot: DocumentSnapshot) -> RenderedDocument:
        document = Document()
        section = document.sections[0]
        section.page_width, section.page_height = Cm(21), Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2)
        section.left_margin = section.right_margin = Cm(2)
        for style_name in ("Normal", "Title", "Subtitle", "Heading 1", "Heading 2"):
            style = document.styles[style_name]
            style.font.name = "Noto Sans"
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.font.size = Pt(
                10 if style_name == "Normal" else 18 if style_name == "Title" else 11
            )
        document.styles["Normal"].paragraph_format.space_after = Pt(7)
        document.core_properties.title = snapshot.title
        document.core_properties.identifier = snapshot.sha256
        document.core_properties.author = "Cafe Fin"
        document.add_paragraph(snapshot.title, style="Title")
        if snapshot.subtitle:
            document.add_paragraph(snapshot.subtitle, style="Subtitle")
        for label, value in snapshot.fields:
            paragraph = document.add_paragraph()
            paragraph.add_run(label + ": ").bold = True
            paragraph.add_run(value)
        for text in snapshot.paragraphs:
            document.add_paragraph(text)
        if snapshot.column_headers:
            table = document.add_table(rows=1, cols=len(snapshot.column_headers))
            table.autofit = False
            for cell, title in zip(table.rows[0].cells, snapshot.column_headers):
                cell.text = title
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            properties = table.rows[0]._tr.get_or_add_trPr()
            properties.append(OxmlElement("w:tblHeader"))
            for row in snapshot.rows:
                for cell, value in zip(table.add_row().cells, row):
                    cell.text = value
            table_properties = table._tbl.tblPr
            borders = OxmlElement("w:tblBorders")
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                element = OxmlElement("w:" + edge)
                for key, value in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    element.set(qn("w:" + key), value)
                borders.append(element)
            table_properties.append(borders)
        stream = io.BytesIO()
        document.save(stream)
        return self._result("docx", stream.getvalue(), snapshot)

    def pdf(self, snapshot: DocumentSnapshot) -> RenderedDocument:
        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
            title=snapshot.title,
            author="Cafe Fin",
            subject="snapshot-sha256:" + snapshot.sha256,
        )
        normal = ParagraphStyle(
            "Body", fontName="CafeFinNoto", fontSize=10, leading=15, spaceAfter=7
        )
        heading = ParagraphStyle(
            "Title",
            parent=normal,
            fontName="CafeFinNotoBold",
            fontSize=18,
            leading=24,
            spaceAfter=12,
        )

        def paragraph(text, style=normal):
            return Paragraph(escape(text).replace("\n", "<br/>"), style)

        flowables = [paragraph(snapshot.title, heading)]
        if snapshot.subtitle:
            flowables.append(paragraph(snapshot.subtitle))
        flowables.extend(paragraph(label + ": " + value) for label, value in snapshot.fields)
        flowables.extend(paragraph(text) for text in snapshot.paragraphs)
        if snapshot.column_headers:
            flowables.append(Spacer(1, 4 * mm))
            header = ParagraphStyle(
                "TableHeader", parent=normal, fontName="CafeFinNotoBold", textColor=colors.black
            )
            values = [[paragraph(value, header) for value in snapshot.column_headers]]
            values.extend([paragraph(value) for value in row] for row in snapshot.rows)
            table = Table(
                values,
                colWidths=[170 * mm / len(snapshot.column_headers)] * len(snapshot.column_headers),
                repeatRows=1,
                hAlign="LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D9D9")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            flowables.append(table)
        try:
            doc.build(flowables)
        except Exception:
            raise CoreError(
                "RENDER_FAILED",
                "Không thể dàn trang PDF. Kiểm tra độ dài nội dung hoặc chia nhỏ bảng.",
                status=422,
            ) from None
        return self._result("pdf", output.getvalue(), snapshot)


def synthetic_snapshot() -> DocumentSnapshot:
    return DocumentSnapshot(
        title="Phiếu thử chứng từ tiếng Việt",
        subtitle="Cafe Fin  •  Ngày 06/11/2026",
        fields=(
            ("Đơn vị", "Công ty Cà phê Đắk Lắk"),
            ("Địa điểm", "Buôn Ma Thuột"),
            ("Mã tham chiếu", "0000123"),
        ),
        paragraphs=(
            "Tài liệu thử khả năng xuất tiếng Việt từ một snapshot bất biến.",
            "Nội dung nhập: Cà phê nhân, độ ẩm và khối lượng. Các ký tự cần kiểm tra: ă â đ ê ô ơ ư Á Ế Ỡ Ự.",
        ),
        column_headers=("Mặt hàng", "Khối lượng kg", "Số tiền VND"),
        rows=(
            ("Cà phê Robusta", "1.234,567", "123.456.789,01"),
            ("Cà phê Arabica", "25,000", "2.500.000"),
        ),
    )
