"""Summary-only rendering shared by local files and explicitly chosen attachments."""

import io
import re
import zipfile

from openpyxl import Workbook
from reportlab import rl_config

from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentRenderer, DocumentSnapshot

from .models import DATE_RANGE_CONTRACT
from .sources import NOTICE

MONEY_LABELS = {
    "cash_receipts": "Tổng thu tiền",
    "cash_payments": "Tổng chi tiền",
    "noncash_offsets": "Đối trừ không tiền",
    "cash_receipt_deposits": "Cọc thu (trong thu)",
    "cash_payment_deposits": "Cọc chi (trong chi)",
}
MOVEMENT_LABELS = {
    "purchased_kg": "Mua",
    "sold_kg": "Bán",
    "production_input_kg": "Đưa vào sản xuất",
    "production_output_kg": "Sản xuất ra",
    "transfer_in_kg": "Chuyển vào",
    "transfer_out_kg": "Chuyển ra",
    "adjustment_in_kg": "Điều chỉnh tăng",
    "adjustment_out_kg": "Điều chỉnh giảm",
}


def scaled(value: str, places: int) -> int:
    # DTO aggregates may exceed int64; Python ints preserve every digit.
    if not isinstance(value, str) or not re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value):
        raise CoreError("REPORT_AMOUNT_INVALID", "Số liệu báo cáo không hợp lệ.")
    negative = value.startswith("-")
    whole, _, fraction = value.lstrip("-").partition(".")
    if len(fraction) > places or len(value) > 256:
        raise CoreError("REPORT_AMOUNT_INVALID", "Độ chính xác số liệu không hợp lệ.")
    result = int(whole) * 10**places + int(fraction.ljust(places, "0") or "0")
    return -result if negative else result


def decimal_text(value: int, places: int) -> str:
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 10**places)
    return f"{sign}{whole}.{fraction:0{places}d}"


def summary_rows(snapshot: dict) -> tuple[tuple[str, str, str], ...]:
    # No arbitrary provider labels, notes, names, IDs, flags or paths go to attachments.
    rows = []
    inventory = snapshot["sources"]["inventory"]["items"]
    warehouses = {x: i + 1 for i, x in enumerate(sorted({r["warehouse_id"] for r in inventory}))}
    products = {x: i + 1 for i, x in enumerate(sorted({r["product_id"] for r in inventory}))}
    breakdown = snapshot["sources"]["inventory"].get("movement_breakdown")
    components = {(x["warehouse_id"], x["product_id"]): x for x in (breakdown or [])}
    for item in inventory:
        group = f"Kho {warehouses[item['warehouse_id']]} / Loại {products[item['product_id']]}"
        for key, label in (
            ("opening_kg", "Đầu kỳ"),
            ("received_kg", "Nhập tổng"),
            ("issued_kg", "Xuất tổng"),
            ("closing_kg", "Cuối kỳ"),
        ):
            rows.append((group, label + " (kg)", decimal_text(scaled(item[key], 3), 3)))
        movement = components.get((item["warehouse_id"], item["product_id"]))
        if movement:
            for key, label in MOVEMENT_LABELS.items():
                rows.append((group, label + " (kg)", decimal_text(scaled(movement[key], 3), 3)))
    if not inventory:
        rows.append(("Kho", "Tồn kho", "Chưa đủ dữ liệu"))
    if breakdown is None:
        rows.append(("Kho", "Sản xuất", "Chưa đủ dữ liệu tách riêng"))
    for index, book in enumerate(snapshot["sources"]["books"], 1):
        known = [x for x in book["metrics"] if x.get("meaning") in MONEY_LABELS]
        if not book["has_valid_money_mapping"] or not known:
            rows.append((f"Sổ {index}", "Tiền (VND)", "Chưa đủ dữ liệu"))
        for metric in known:
            rows.append(
                (
                    f"Sổ {index}",
                    MONEY_LABELS[metric["meaning"]] + " (VND)",
                    decimal_text(scaled(metric["amount_vnd"], 2), 2),
                )
            )
    if not snapshot["sources"]["books"]:
        rows.append(("Tiền", "Sổ kế toán", "Chưa chọn sổ"))
    return tuple(rows)


def period_text(snapshot: dict) -> str:
    period = snapshot["period"]
    if period.get("date_range_contract") == DATE_RANGE_CONTRACT:
        return f"{period['from_on']} đến hết {period['through_on']}"
    return f"{period['from_on']} / {period['through_on']} (kỳ cũ chưa định danh cách chọn ngày)"


def short_message(snapshot: dict, version: int, digest: str) -> str:
    lines = [f"Cafe Fin {period_text(snapshot)} - bản {version}"]
    inventory = snapshot["sources"]["inventory"]["items"]
    if inventory:
        for field, label in (
            ("received_kg", "Nhập tổng"),
            ("issued_kg", "Xuất tổng"),
            ("closing_kg", "Tồn tổng"),
        ):
            total = sum(scaled(x[field], 3) for x in inventory)
            lines.append(f"{label}: {decimal_text(total, 3)} kg")
        breakdown = snapshot["sources"]["inventory"].get("movement_breakdown")
        if breakdown is not None:
            for field, label in (
                ("purchased_kg", "Mua"),
                ("sold_kg", "Bán"),
                ("production_input_kg", "Vào sản xuất"),
                ("production_output_kg", "Sản xuất ra"),
            ):
                total = sum(scaled(x[field], 3) for x in breakdown)
                lines.append(f"{label}: {decimal_text(total, 3)} kg")
    else:
        lines.append("Kho: chưa đủ dữ liệu")
    # Bound the short message rather than accidentally sending a detailed local report.
    for index, book in enumerate(snapshot["sources"]["books"][:5], 1):
        metrics = [x for x in book["metrics"] if x.get("meaning") in MONEY_LABELS]
        values = [
            f"{MONEY_LABELS[x['meaning']]} {decimal_text(scaled(x['amount_vnd'], 2), 2)}"
            for x in metrics
        ]
        lines.append(
            f"Sổ {index}: " + ("; ".join(values) + " VND" if values else "chưa đủ dữ liệu")
        )
    if len(snapshot["sources"]["books"]) > 5:
        lines.append("Các sổ còn lại: xem bản tổng hợp được chọn đính kèm.")
    lines.extend(
        [
            "Sản xuất: "
            + (
                "đã tách riêng."
                if snapshot.get("production") is not None
                else "chưa đủ dữ liệu tách riêng."
            ),
            f"Cảnh báo: {len(snapshot['warnings'])}. Mã bản: {digest[:12]}",
            NOTICE,
        ]
    )
    text = "\n".join(lines)
    if len(text) > 1800:
        # Extremely large exact numbers are retained locally, not truncated into false values.
        text = "\n".join(
            [
                lines[0],
                "Số liệu dài: xem bản tổng hợp được chọn đính kèm.",
                f"Mã bản: {digest[:12]}",
                NOTICE,
            ]
        )
    return text


def render(snapshot: dict, version: int, digest: str, format: str) -> tuple[bytes, str]:
    rows = summary_rows(snapshot)
    if format == "txt":
        return short_message(snapshot, version, digest).encode("utf-8"), "text/plain; charset=utf-8"
    title = "Báo cáo tổng hợp cà phê"
    fields = (
        ("Kỳ Việt Nam", f"{period_text(snapshot)} - bản {version}"),
        ("SHA-256 snapshot", digest),
        ("Cutoff UTC", snapshot["cutoff"] + f" | {len(snapshot['warnings'])} cảnh báo dữ liệu"),
    )
    paragraphs = (
        NOTICE,
        (
            "Nhập/xuất tổng gồm các thành phần tách riêng bên dưới; không cộng hai lần."
            if snapshot.get("production") is not None
            else "Nhập/xuất tổng chưa tách sản xuất, chuyển kho và điều chỉnh."
        ),
        "Sổ tiền độc lập; không cộng các sổ hoặc cộng cọc vào tổng thu/chi. Hóa đơn không phải thu tiền.",
        "Kho/Loại/Sổ được đánh số trong bản này; xem nguồn chi tiết tại ứng dụng local.",
    )
    if format == "pdf":
        document = DocumentSnapshot(
            title=title,
            fields=fields,
            paragraphs=paragraphs,
            column_headers=("Nhóm", "Chỉ tiêu", "Giá trị chính xác"),
            rows=rows,
        )
        # Caller holds core render_lock. Stable metadata makes FileStore retries
        # safe if the process died before registering reporting's export receipt.
        previous = rl_config.invariant
        try:
            rl_config.invariant = 1
            return DocumentRenderer().pdf(document).content, "application/pdf"
        finally:
            rl_config.invariant = previous
    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Tổng hợp"
        for values in (
            (title,),
            *fields,
            *((x,) for x in paragraphs),
            ("Nhóm", "Chỉ tiêu", "Giá trị chính xác"),
            *rows,
        ):
            sheet.append(values)
            # All values are deliberately text. Excel's 15-digit numeric precision
            # must not silently alter money/kg, or execute user text as a formula.
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"
                cell.number_format = "@"
        sheet.column_dimensions["A"].width = 38
        sheet.column_dimensions["B"].width = 40
        sheet.column_dimensions["C"].width = 48
        sheet.freeze_panes = f"A{len(fields) + len(paragraphs) + 3}"
        stream = io.BytesIO()
        workbook.save(stream)
        normalized = io.BytesIO()
        with (
            zipfile.ZipFile(stream) as source,
            zipfile.ZipFile(normalized, "w", zipfile.ZIP_DEFLATED) as target,
        ):
            for name in source.namelist():
                info = zipfile.ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                content = source.read(name)
                if name == "docProps/core.xml":
                    content = re.sub(
                        rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", b"2000-01-01T00:00:00Z", content
                    )
                target.writestr(info, content)
        return (
            normalized.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    raise CoreError("REPORT_FORMAT_INVALID", "Định dạng báo cáo không được hỗ trợ.")
