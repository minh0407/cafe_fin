"""Original contract text templates adapted to the foundation's literal-text renderer."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from cafe_fin.core.amounts import kg_string, money_string, parse_money
from cafe_fin.core.contracts import PartyInput
from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentSnapshot

from .schemas import ROUNDING_POLICY, TEMPLATE_IDS, ContractData, computed_units

TOKENS = frozenset(
    (
        "number",
        "occurred_on",
        "place",
        "company",
        "counterparty",
        "goods",
        "totals",
        "delivery",
        "packaging",
        "quality",
        "deadline",
        "responsibilities",
        "additional",
        "payment",
        "signatures",
    )
)
_TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")


def _under_thousand(value: int, full: bool = False) -> str:
    hundred, rest = divmod(value, 100)
    ten, one = divmod(rest, 10)
    words = []
    if hundred or full:
        words.extend((_DIGITS[hundred], "trăm"))
    if ten >= 2:
        words.extend((_DIGITS[ten], "mươi"))
    elif ten == 1:
        words.append("mười")
    elif one and (hundred or full):
        words.append("lẻ")
    if one:
        words.append("mốt" if one == 1 and ten > 1 else "lăm" if one == 5 and ten else _DIGITS[one])
    return " ".join(words)


def _integer_words(value: int) -> str:
    if value == 0:
        return _DIGITS[0]
    groups = []
    while value:
        value, group = divmod(value, 1000)
        groups.append(group)
    words = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        unit = ("", "nghìn", "triệu")[index % 3]
        if index >= 3:
            unit = (unit + " " + " ".join(["tỷ"] * (index // 3))).strip()
        words.append((_under_thousand(group, bool(words) and group < 100) + " " + unit).strip())
    return " ".join(words)


def money_in_words(value: str) -> str:
    """Read the exact 0.01 VND amount; do not silently discard fractional đồng."""
    cents = parse_money(value)
    sign = "Âm " if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    result = sign + _integer_words(whole) + " đồng"
    if fraction:
        result += " và " + _integer_words(fraction) + " phần trăm đồng"
    return result[0].upper() + result[1:]


def totals(data: ContractData) -> dict:
    units = computed_units(data)
    result = {
        key: (
            [money_string(amount) for amount in value]
            if key == "line_amounts"
            else kg_string(value)
            if key == "quantity_kg"
            else money_string(value)
            if value is not None
            else None
        )
        for key, value in units.items()
    }
    result.update(
        tax_mode=data.tax.mode,
        tax_rate=data.tax.rate,
        rounding_policy=ROUNDING_POLICY,
        amount_in_words=money_in_words(result["grand_total"])
        if result["grand_total"] is not None
        else None,
    )
    return result


def validate_template(payload: Mapping) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != {"title", "body"}:
        raise CoreError("CONTRACT_TEMPLATE_INVALID", "Mẫu cần đúng hai trường title và body.")
    for key, limit in (("title", 1000), ("body", 200000)):
        value = payload[key]
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise CoreError("CONTRACT_TEMPLATE_INVALID", "Tiêu đề hoặc nội dung mẫu không hợp lệ.")
        if any(
            ord(c) < 32
            and c not in "\t\n\r"
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) in (0xFFFE, 0xFFFF)
            for c in value
        ):
            raise CoreError("CONTRACT_TEMPLATE_INVALID", "Mẫu có ký tự điều khiển không hỗ trợ.")
        stripped = _TOKEN.sub("", value)
        if "{{" in stripped or "}}" in stripped:
            raise CoreError("CONTRACT_TEMPLATE_INVALID", "Token mẫu không hợp lệ.")
        if set(_TOKEN.findall(value)) - TOKENS:
            raise CoreError("CONTRACT_TEMPLATE_INVALID", "Mẫu có token không được hỗ trợ.")
    present = set(_TOKEN.findall(payload["title"] + "\n" + payload["body"]))
    if TOKENS - present:
        raise CoreError(
            "CONTRACT_TEMPLATE_INVALID",
            "Mẫu cần giữ các token thông tin hợp đồng.",
            details={"missing_tokens": sorted(TOKENS - present)},
        )
    return {"title": payload["title"], "body": payload["body"]}


def template_hash(payload: Mapping) -> str:
    validated = validate_template(payload)
    return hashlib.sha256(
        json.dumps(validated, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _default(kind: str) -> dict:
    payload = json.loads((Path(__file__).parent / "templates" / f"{kind}.json").read_text("utf-8"))
    return {
        "id": TEMPLATE_IDS[kind],
        "kind": kind,
        "version": 1,
        "title": payload["title"],
        "body": payload["body"],
        "hash": template_hash(payload),
    }


def _display(value: str) -> str:
    whole, _, fraction = value.partition(".")
    grouped = f"{int(whole):,}".replace(",", ".")
    fraction = fraction.rstrip("0")
    return grouped + ("," + fraction if fraction else "")


def _party(party: PartyInput, role: str) -> str:
    pieces = [role + ": " + party.name]
    for label, value in (("Địa chỉ", party.address), ("Mã số thuế/định danh", party.tax_code)):
        if value is not None:
            pieces.append(label + ": " + value)
    if party.representative:
        representative = party.representative
        pieces.append("Đại diện: " + representative.name)
        if representative.title is not None:
            pieces.append("Chức vụ: " + representative.title)
        if representative.authorization_reference is not None:
            pieces.append("Căn cứ đại diện: " + representative.authorization_reference)
    for contact in party.contacts:
        pieces.append(f"Liên hệ ({contact.label or contact.kind}): {contact.value}")
    for account in party.bank_details:
        pieces.append(_account(account))
    return "\n".join(pieces)


def _account(account) -> str:
    parts = ["Tài khoản: " + account.account_number, "Ngân hàng: " + account.bank_name]
    if account.account_holder is not None:
        parts.append("Chủ tài khoản: " + account.account_holder)
    if account.branch is not None:
        parts.append("Chi nhánh: " + account.branch)
    return "; ".join(parts)


def _goods(data: ContractData, computed: dict) -> str:
    blocks = []
    for index, (line, amount) in enumerate(zip(data.lines, computed["line_amounts"]), 1):
        pieces = [
            f"{index}. {line.description}",
            f"Lượng hợp đồng: {_display(line.quantity_kg)} kg; đơn giá: "
            f"{_display(line.unit_price)} VND/kg; thành tiền: {_display(amount)} VND.",
        ]
        for label, value in (
            ("Cân đầy", line.gross_kg),
            ("Cân rỗng", line.tare_kg),
            ("Cân tịnh", line.net_kg),
        ):
            if value is not None:
                pieces.append(f"{label}: {_display(value)} kg.")
        if line.quantity_source is not None:
            quantity_label = {
                "direct": "Nhập kg tịnh trực tiếp",
                "direct_net": "Nhập kg tịnh trực tiếp",
                "gross_minus_tare": "Cân đầy trừ cân rỗng",
                "gross_tare": "Cân đầy trừ cân rỗng",
            }.get(line.quantity_source, line.quantity_source)
            pieces.append("Cách ghi lượng: " + quantity_label)
        if line.note is not None:
            pieces.append("Ghi chú: " + line.note)
        if line.source:
            source = line.source
            pieces.append(
                f"Nguồn phiếu cân: {source.code or source.id}; phiên bản {source.version}; "
                f"dòng {source.line_index + 1}"
                + (f"; ngày {source.occurred_on}" if source.occurred_on else "")
                + "."
            )
        if line.source_snapshot:
            weight = line.source_snapshot
            original = [
                (label + ": " + _display(getattr(weight, key)))
                for label, key in (
                    ("đầy (kg)", "gross_kg"),
                    ("rỗng (kg)", "tare_kg"),
                    ("tịnh (kg)", "net_kg"),
                )
                if getattr(weight, key) is not None
            ]
            if original:
                pieces.append("Số cân nguồn (bản chụp): " + "; ".join(original) + ".")
        blocks.append("\n".join(pieces))
    return "\n\n".join(blocks)


def _totals(computed: dict) -> str:
    pieces = ["Tổng khối lượng: " + _display(computed["quantity_kg"]) + " kg."]
    mode = computed["tax_mode"]
    subtotal_label = (
        "Tiền hàng theo giá đã gồm thuế" if mode == "inclusive" else "Tiền hàng theo đơn giá"
    )
    pieces.append(subtotal_label + ": " + _display(computed["subtotal"]) + " VND.")
    if mode == "unspecified":
        pieces.extend(
            ("Thuế: chưa xác định.", "Tổng thanh toán: chưa xác định do chưa chọn cách tính thuế.")
        )
    else:
        if mode == "none":
            pieces.append("Thuế: không áp dụng (0 VND).")
        else:
            pieces.extend(
                (
                    "Giá trị trước thuế: " + _display(computed["net_amount"]) + " VND.",
                    f"Thuế suất: {_display(computed['tax_rate'])}%; "
                    f"tiền thuế: {_display(computed['tax_amount'])} VND "
                    + ("(đã nằm trong giá)." if mode == "inclusive" else "(cộng ngoài giá)."),
                )
            )
        pieces.extend(
            (
                "Tổng thanh toán: " + _display(computed["grand_total"]) + " VND.",
                "Bằng chữ: " + computed["amount_in_words"] + ".",
            )
        )
    pieces.append(
        "Làm tròn: từng dòng đến 0,01 VND theo quy tắc nửa lên; "
        "sau đó tính và làm tròn thuế một lần trên tổng tiền hàng."
    )
    return "\n".join(pieces)


def _payment(data: ContractData) -> str:
    payment = data.payment
    method = {
        "cash": "Tiền mặt",
        "bank": "Chuyển khoản",
        "mixed": "Kết hợp tiền mặt và chuyển khoản",
        "other": "Khác",
    }[payment.method]
    pieces = ["Phương thức: " + method + "."]
    if payment.description:
        pieces.append(payment.description)
    if payment.receiving_account is not None:
        pieces.append("Tài khoản nhận theo điều khoản — " + _account(payment.receiving_account))
    if payment.due_on is not None:
        pieces.append("Hạn thanh toán: " + payment.due_on + ".")
    if payment.deposit_amount is not None:
        pieces.append("Tiền cọc theo điều khoản: " + _display(payment.deposit_amount) + " VND.")
    if payment.recorded_paid_amount is not None:
        pieces.append(
            "Số đã trả do người dùng ghi nhận: " + _display(payment.recorded_paid_amount) + " VND."
        )
    for index, installment in enumerate(payment.schedule, 1):
        pieces.append(
            f"Đợt {index}: {installment.due_on}; {_display(installment.amount)} VND"
            + ("; " + installment.note if installment.note else "")
            + "."
        )
    pieces.append(
        "Nội dung thanh toán là thông tin hợp đồng do người dùng ghi; "
        "việc xuất hợp đồng không xác nhận đã thu hoặc chi tiền."
    )
    return "\n".join(pieces)


def build_document(
    data: ContractData, computed_totals: dict, template_payload: Mapping
) -> DocumentSnapshot:
    payload = validate_template(template_payload)
    computed = totals(data)
    if computed_totals != computed:
        raise CoreError("CONTRACT_TOTALS_MISMATCH", "Tổng tiền không khớp dữ liệu hợp đồng.")
    company_role = "Bên mua" if data.kind == "purchase" else "Bên bán"
    counterparty_role = "Bên bán" if data.kind == "purchase" else "Bên mua"
    values = {
        "number": data.number,
        "occurred_on": data.occurred_on,
        "place": data.place,
        "company": _party(data.company, company_role),
        "counterparty": _party(data.counterparty, counterparty_role),
        "goods": _goods(data, computed),
        "totals": _totals(computed),
        "payment": _payment(data),
        "signatures": f"ĐẠI DIỆN {company_role.upper()}\n{data.company.name}\n"
        f"(Ký, ghi rõ họ tên)\n\nĐẠI DIỆN {counterparty_role.upper()}\n{data.counterparty.name}\n"
        "(Ký, ghi rõ họ tên)",
    }
    values.update(data.terms.model_dump())

    def substitute(match):
        return values[match.group(1)]

    title = _TOKEN.sub(substitute, payload["title"])
    body = _TOKEN.sub(substitute, payload["body"])
    # Paragraph blocks maintain template order. The shared renderer puts a single
    # table after all paragraphs, so goods use readable numbered text here.
    return DocumentSnapshot(title=title, paragraphs=tuple(body.split("\n\n")))


DEFAULT_TEMPLATES = (_default("purchase"), _default("sale"))
