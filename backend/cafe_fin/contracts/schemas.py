"""Contract inputs and exact, explicitly rounded arithmetic (no stock or cash effects)."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cafe_fin.core.amounts import checked_int64, kg_string, money_string, parse_kg, parse_money
from cafe_fin.core.contracts import BankAccountDTO, PartyInput, SourceReference, WeightLineInput
from cafe_fin.core.errors import CoreError

ROUNDING_POLICY = "line_half_up_0.01_vnd_then_contract_tax_half_up_0.01_vnd"
TEMPLATE_IDS = {
    "purchase": "be33fbce-4a0d-50eb-b203-895a24102ce1",
    "sale": "9be1e97b-8278-55d3-aaba-13f663349ab2",
}
Text = Annotated[str, Field(max_length=50000)]
RequiredText = Annotated[str, Field(min_length=1, max_length=10000)]


def _amount(value: str, *, kg: bool = False, positive: bool = False) -> str:
    try:
        units = (parse_kg if kg else parse_money)(value)
    except CoreError as exc:
        raise ValueError(exc.message) from exc
    if units < 0 or (positive and units == 0):
        raise ValueError("Khối lượng phải dương." if positive else "Giá trị không được âm.")
    return (kg_string if kg else money_string)(units)


def _date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Ngày phải có dạng YYYY-MM-DD.")
    date.fromisoformat(value)
    return value


class ContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def safe_text(cls, value):
        # XML 1.0 text must be representable identically in DOCX and PDF.
        if isinstance(value, BaseModel):
            cls.safe_text(value.model_dump())
        elif isinstance(value, dict):
            for key, item in value.items():
                cls.safe_text(key)
                cls.safe_text(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                cls.safe_text(item)
        elif isinstance(value, str) and any(
            ord(c) < 32
            and c not in "\t\n\r"
            or 0xD800 <= ord(c) <= 0xDFFF
            or ord(c) in (0xFFFE, 0xFFFF)
            for c in value
        ):
            raise ValueError("Nội dung chứa ký tự điều khiển không hỗ trợ.")
        return value


class WeighingSource(ContractInput):
    type: Literal["weighing"] = "weighing"
    id: RequiredText
    version: int = Field(ge=1)
    line_index: int = Field(ge=0)
    code: str | None = None
    occurred_on: str | None = None

    @field_validator("id")
    @classmethod
    def uuid_identity(cls, value):
        return str(UUID(value))

    @field_validator("occurred_on")
    @classmethod
    def valid_date(cls, value):
        return _date(value) if value is not None else None


class ContractLine(ContractInput):
    description: RequiredText
    quantity_kg: str
    unit_price: str
    gross_kg: str | None = None
    tare_kg: str | None = None
    net_kg: str | None = None
    quantity_source: str | None = None
    note: Text | None = None
    product_id: str | None = None
    source: WeighingSource | None = None
    source_snapshot: WeightLineInput | None = None

    @field_validator("source_snapshot", mode="before")
    @classmethod
    def source_weights(cls, value):
        raw = value.model_dump() if isinstance(value, WeightLineInput) else value
        if isinstance(raw, dict):
            for key in ("gross_kg", "tare_kg", "net_kg"):
                if raw.get(key) is not None:
                    _amount(raw[key], kg=True)
        return value

    @field_validator("quantity_kg")
    @classmethod
    def quantity(cls, value):
        return _amount(value, kg=True, positive=True)

    @field_validator("unit_price")
    @classmethod
    def price(cls, value):
        return _amount(value)

    @field_validator("gross_kg", "tare_kg", "net_kg")
    @classmethod
    def weights(cls, value):
        return _amount(value, kg=True) if value is not None else None

    @model_validator(mode="after")
    def check_weights(self):
        if self.gross_kg is not None and self.tare_kg is not None:
            if parse_kg(self.tare_kg) > parse_kg(self.gross_kg):
                raise ValueError("Cân rỗng không được lớn hơn cân đầy.")
        return self


class ContractTax(ContractInput):
    mode: Literal["unspecified", "none", "exclusive", "inclusive"] = "unspecified"
    rate: str | None = None

    @field_validator("rate")
    @classmethod
    def valid_rate(cls, value):
        if value is None:
            return None
        value = _amount(value)
        if parse_money(value) > 10000:
            raise ValueError("Thuế suất phải trong khoảng 0 đến 100 phần trăm.")
        return value

    @model_validator(mode="after")
    def rate_for_mode(self):
        if self.mode in ("exclusive", "inclusive") and self.rate is None:
            raise ValueError("Cần nhập thuế suất cho cách tính thuế đã chọn.")
        if self.mode in ("unspecified", "none") and self.rate is not None:
            raise ValueError("Không nhập thuế suất khi chưa xác định hoặc không áp dụng thuế.")
        return self


class ContractTerms(ContractInput):
    delivery: Text = ""
    packaging: Text = ""
    quality: Text = ""
    deadline: Text = ""
    responsibilities: Text = ""
    additional: Text = ""


class PaymentInstallment(ContractInput):
    due_on: str
    amount: str
    note: Text = ""

    @field_validator("due_on")
    @classmethod
    def valid_date(cls, value):
        return _date(value)

    @field_validator("amount")
    @classmethod
    def valid_amount(cls, value):
        return _amount(value)


class ContractPayment(ContractInput):
    method: Literal["cash", "bank", "mixed", "other"] = "cash"
    description: Text = ""
    receiving_account: BankAccountDTO | None = None
    due_on: str | None = None
    deposit_amount: str | None = None
    recorded_paid_amount: str | None = None
    schedule: list[PaymentInstallment] = Field(default_factory=list, max_length=500)

    @field_validator("due_on")
    @classmethod
    def valid_date(cls, value):
        return _date(value) if value is not None else None

    @field_validator("deposit_amount", "recorded_paid_amount")
    @classmethod
    def valid_amount(cls, value):
        return _amount(value) if value is not None else None


class ContractData(ContractInput):
    kind: Literal["purchase", "sale"]
    number: RequiredText
    occurred_on: str
    place: Text = ""
    template_id: Literal[
        "be33fbce-4a0d-50eb-b203-895a24102ce1", "9be1e97b-8278-55d3-aaba-13f663349ab2"
    ]
    company: PartyInput
    counterparty: PartyInput
    lines: list[ContractLine] = Field(min_length=1, max_length=5000)
    tax: ContractTax = Field(default_factory=ContractTax)
    terms: ContractTerms = Field(default_factory=ContractTerms)
    payment: ContractPayment = Field(default_factory=ContractPayment)
    source_refs: list[SourceReference] = Field(default_factory=list, max_length=10000)

    @field_validator("occurred_on")
    @classmethod
    def valid_date(cls, value):
        return _date(value)

    @field_validator("number")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Cần nhập số hợp đồng.")
        return value

    @field_validator("company", "counterparty", mode="before")
    @classmethod
    def embedded_party(cls, value):
        # Public core DTO uses tuples. JSON arrays from FastAPI body dictionaries
        # must retain the same accepted meaning as model_validate_json.
        if isinstance(value, dict):
            return PartyInput.model_validate_json(json.dumps(value, ensure_ascii=False))
        return value

    @model_validator(mode="after")
    def coherent_contract(self):
        if self.template_id != TEMPLATE_IDS[self.kind]:
            raise ValueError("Mẫu không phù hợp loại hợp đồng.")
        identities = [
            (line.source.id, line.source.line_index) for line in self.lines if line.source
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Một dòng phiếu cân nguồn chỉ được chọn một lần trong hợp đồng.")
        try:
            computed_units(self)
        except CoreError as exc:
            raise ValueError(exc.message) from exc
        return self


def _half_up(numerator: int, denominator: int) -> int:
    """Exact ROUND_HALF_UP for nonnegative integer units, without Decimal context limits."""
    return (numerator * 2 + denominator) // (denominator * 2)


def computed_units(data: ContractData) -> dict:
    amounts = [
        checked_int64(_half_up(parse_kg(line.quantity_kg) * parse_money(line.unit_price), 1000))
        for line in data.lines
    ]
    subtotal = checked_int64(sum(amounts))
    quantity = checked_int64(sum(parse_kg(line.quantity_kg) for line in data.lines))
    rate = parse_money(data.tax.rate) if data.tax.rate is not None else None
    if data.tax.mode == "unspecified":
        net, tax, grand = None, None, None
    elif data.tax.mode == "none":
        net, tax, grand = subtotal, 0, subtotal
    elif data.tax.mode == "exclusive":
        net = subtotal
        tax = checked_int64(_half_up(subtotal * rate, 10000))
        grand = checked_int64(net + tax)
    else:
        grand = subtotal
        tax = checked_int64(_half_up(subtotal * rate, 10000 + rate))
        net = checked_int64(grand - tax)
    return {
        "line_amounts": amounts,
        "quantity_kg": quantity,
        "subtotal": subtotal,
        "net_amount": net,
        "tax_amount": tax,
        "grand_total": grand,
    }
