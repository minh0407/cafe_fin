"""Public read bridges. These types do not imply module implementation."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .amounts import parse_kg

NonEmpty = Annotated[str, StringConstraints(min_length=1)]
SummaryDisplayName = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=256, pattern=r"\S")
]


def _aggregate_decimal(value: str, scale: int) -> str:
    """Summary totals can exceed int64; retain exact decimal text without float conversion."""
    if (
        len(value) > 256
        or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)
        or ("." in value and len(value.split(".", 1)[1]) > scale)
    ):
        raise ValueError("Tổng phải là chuỗi số thập phân chính xác đúng scale.")
    return value


def _aggregate_scaled(value: str, scale: int) -> int:
    """Exact unbounded summary arithmetic; the text was validated separately."""
    whole, _, fraction = value.partition(".")
    sign = -1 if whole.startswith("-") else 1
    return sign * (int(whole.lstrip("-")) * 10**scale + int(fraction.ljust(scale, "0")))


class FrozenDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ContactDTO(FrozenDTO):
    kind: NonEmpty
    value: NonEmpty
    label: str | None = None


class BankAccountDTO(FrozenDTO):
    bank_name: NonEmpty
    account_number: NonEmpty
    account_holder: str | None = None
    branch: str | None = None


class RepresentativeDTO(FrozenDTO):
    name: NonEmpty
    title: str | None = None
    authorization_reference: str | None = None


class PartyInput(FrozenDTO):
    # type remains an owner-defined classification; roles are independent, multiple.
    type: NonEmpty
    roles: tuple[NonEmpty, ...] = ()
    name: NonEmpty
    tax_code: str | None = None
    address: str | None = None
    contacts: tuple[ContactDTO, ...] = ()
    bank_details: tuple[BankAccountDTO, ...] = ()
    representative: RepresentativeDTO | None = None

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Vai trò đối tác không được lặp.")
        return value


class PartyDTO(PartyInput):
    id: NonEmpty
    version: Annotated[int, Field(ge=1)]


class WeightLineInput(FrozenDTO):
    product_id: str | None = None
    description: str | None = None
    gross_kg: str | None = None
    tare_kg: str | None = None
    net_kg: str | None = None
    quantity_source: str | None = None
    note: str | None = None

    @field_validator("gross_kg", "tare_kg", "net_kg")
    @classmethod
    def exact_kg(cls, value: str | None) -> str | None:
        if value is not None:
            parse_kg(value)
        return value


class WeighingDTO(FrozenDTO):
    id: NonEmpty
    version: Annotated[int, Field(ge=1)]
    code: NonEmpty
    occurred_on: date
    party_id: str | None = None
    lines: tuple[WeightLineInput, ...] = ()


class SourceReference(FrozenDTO):
    type: NonEmpty
    id: NonEmpty
    version: Annotated[int, Field(ge=1)]


class CutoffDTO(FrozenDTO):
    coverage: Literal["entered_records_only"] = "entered_records_only"
    cutoff: datetime

    @field_validator("cutoff")
    @classmethod
    def utc_cutoff(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Cutoff phải có múi giờ UTC.")
        return value.astimezone(timezone.utc)


class InventoryLineDTO(FrozenDTO):
    product_id: NonEmpty
    warehouse_id: NonEmpty
    product_name: SummaryDisplayName | None = None
    warehouse_name: SummaryDisplayName | None = None
    opening_kg: str
    received_kg: str
    issued_kg: str
    closing_kg: str

    @field_validator("opening_kg", "received_kg", "issued_kg", "closing_kg")
    @classmethod
    def exact_kg(cls, value: str) -> str:
        return _aggregate_decimal(value, 3)


class InventoryMovementSummaryDTO(FrozenDTO):
    product_id: NonEmpty
    warehouse_id: NonEmpty
    product_name: SummaryDisplayName | None = None
    warehouse_name: SummaryDisplayName | None = None
    purchased_kg: str
    sold_kg: str
    production_input_kg: str
    production_output_kg: str
    transfer_in_kg: str
    transfer_out_kg: str
    adjustment_in_kg: str
    adjustment_out_kg: str

    @field_validator(
        "purchased_kg",
        "sold_kg",
        "production_input_kg",
        "production_output_kg",
        "transfer_in_kg",
        "transfer_out_kg",
        "adjustment_in_kg",
        "adjustment_out_kg",
    )
    @classmethod
    def nonnegative_kg(cls, value: str) -> str:
        value = _aggregate_decimal(value, 3)
        if _aggregate_scaled(value, 3) < 0:
            raise ValueError("Thành phần biến động kho phải không âm.")
        return value


class InventorySummaryDTO(CutoffDTO):
    from_on: date
    through_on: date
    items: tuple[InventoryLineDTO, ...] = ()
    validation_flags: tuple[str, ...] = ()
    breakdown_version: Literal[1] | None = None
    movement_breakdown: tuple[InventoryMovementSummaryDTO, ...] | None = None

    @field_validator("breakdown_version", mode="before")
    @classmethod
    def exact_breakdown_version(cls, value: int | None) -> int | None:
        if value is not None and (type(value) is not int or value != 1):
            raise ValueError("Phiên bản phân loại biến động kho chưa được hỗ trợ.")
        return value

    @model_validator(mode="after")
    def reconcile_breakdown(self) -> InventorySummaryDTO:
        if (self.breakdown_version is None) != (self.movement_breakdown is None):
            raise ValueError(
                "Phiên bản và dữ liệu phân loại biến động phải cùng có hoặc cùng thiếu."
            )
        if self.movement_breakdown is None:
            return self
        totals = {(line.warehouse_id, line.product_id): line for line in self.items}
        detail = {(line.warehouse_id, line.product_id): line for line in self.movement_breakdown}
        if (
            len(totals) != len(self.items)
            or len(detail) != len(self.movement_breakdown)
            or totals.keys() != detail.keys()
        ):
            raise ValueError("Phân loại phải khớp đúng một dòng cho mỗi phạm vi kho/hàng tổng hợp.")
        for scope, line in totals.items():
            part = detail[scope]
            received = sum(
                _aggregate_scaled(getattr(part, field), 3)
                for field in (
                    "purchased_kg",
                    "production_output_kg",
                    "transfer_in_kg",
                    "adjustment_in_kg",
                )
            )
            issued = sum(
                _aggregate_scaled(getattr(part, field), 3)
                for field in (
                    "sold_kg",
                    "production_input_kg",
                    "transfer_out_kg",
                    "adjustment_out_kg",
                )
            )
            if (
                received != _aggregate_scaled(line.received_kg, 3)
                or issued != _aggregate_scaled(line.issued_kg, 3)
                or _aggregate_scaled(line.opening_kg, 3) + received - issued
                != _aggregate_scaled(line.closing_kg, 3)
            ):
                raise ValueError(
                    "Phân loại biến động không khớp nhập/xuất/tồn của phạm vi kho/hàng."
                )
        return self


class ReceivableLineDTO(FrozenDTO):
    party_id: NonEmpty
    amount_vnd: str

    @field_validator("amount_vnd")
    @classmethod
    def exact_money(cls, value: str) -> str:
        return _aggregate_decimal(value, 2)


class ReceivableSummaryDTO(CutoffDTO):
    as_of: date
    items: tuple[ReceivableLineDTO, ...] = ()
    validation_flags: tuple[str, ...] = ()


class MappedBookMetricDTO(FrozenDTO):
    key: NonEmpty
    amount_vnd: str
    mapping_revision: Annotated[int, Field(ge=1)]
    meaning: (
        Literal[
            "cash_receipts",
            "cash_payments",
            "cash_receipt_deposits",
            "cash_payment_deposits",
            "noncash_offsets",
            "other",
        ]
        | None
    ) = None

    @field_validator("amount_vnd")
    @classmethod
    def exact_money(cls, value: str) -> str:
        return _aggregate_decimal(value, 2)

    @model_validator(mode="after")
    def nonnegative_known_metric(self) -> MappedBookMetricDTO:
        if self.meaning not in (None, "other") and _aggregate_scaled(self.amount_vnd, 2) < 0:
            raise ValueError("Tổng thu/chi, tập con tiền cọc và đối trừ phải không âm.")
        return self


class BookSummaryDTO(CutoffDTO):
    book_id: NonEmpty
    book_name: SummaryDisplayName | None = None
    from_on: date
    through_on: date
    has_valid_money_mapping: bool
    metrics: tuple[MappedBookMetricDTO, ...] = ()
    validation_flags: tuple[str, ...] = ()

    @field_validator("metrics")
    @classmethod
    def mapped_only(
        cls, value: tuple[MappedBookMetricDTO, ...], info: ValidationInfo
    ) -> tuple[MappedBookMetricDTO, ...]:
        # Field order ensures mapping is known before any money is exposed.
        if value and not info.data.get("has_valid_money_mapping"):
            raise ValueError("Không tổng hợp tiền khi sổ chưa có mapping hợp lệ.")
        return value

    @model_validator(mode="after")
    def semantic_totals(self) -> BookSummaryDTO:
        known = [metric for metric in self.metrics if metric.meaning not in (None, "other")]
        totals = {metric.meaning: metric for metric in known}
        if len(totals) != len(known):
            raise ValueError("Mỗi ý nghĩa tổng hợp đã xác định chỉ có một tổng trong một sổ.")
        for subset, total in (
            ("cash_receipt_deposits", "cash_receipts"),
            ("cash_payment_deposits", "cash_payments"),
        ):
            if (
                subset in totals
                and total in totals
                and (
                    _aggregate_scaled(totals[subset].amount_vnd, 2)
                    > _aggregate_scaled(totals[total].amount_vnd, 2)
                )
            ):
                raise ValueError("Tiền cọc là tập con, không được vượt tổng thu/chi cùng sổ.")
        return self


class RecordsReadBridge(Protocol):
    def lookup_party(self, identity: str) -> PartyDTO | None: ...
    def get_weighing(self, identity: str) -> WeighingDTO | None: ...
    def inventory_summary(
        self, from_on: date, through_on: date, *, cutoff: datetime
    ) -> InventorySummaryDTO: ...
    def receivable_summary(self, as_of: date, *, cutoff: datetime) -> ReceivableSummaryDTO: ...


class AccountingReadBridge(Protocol):
    def book_summary(
        self, book_id: str, from_on: date, through_on: date, *, cutoff: datetime
    ) -> BookSummaryDTO: ...


ImportJobState = Literal[
    "UPLOADED",
    "PARSING",
    "READY_FOR_MAPPING",
    "VALIDATING",
    "READY_FOR_CONFIRM",
    "COMMITTING",
    "PARTIALLY_COMMITTED",
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "RECOVERABLE",
]


class ImportIssueDTO(FrozenDTO):
    sheet: NonEmpty
    row: Annotated[int, Field(ge=1)]
    column: NonEmpty
    cell: NonEmpty
    code: NonEmpty
    severity: Literal["error", "warning"]
    message: NonEmpty
    suggestion: str | None = None


class ImportCountsDTO(FrozenDTO):
    source_rows: Annotated[int, Field(ge=0)]
    validated: Annotated[int, Field(ge=0)]
    valid: Annotated[int, Field(ge=0)]
    invalid: Annotated[int, Field(ge=0)]
    potential_duplicates: Annotated[int, Field(ge=0)]
    conflicts: Annotated[int, Field(ge=0)]
    excluded: Annotated[int, Field(ge=0)]
    staged_committed_rows: Annotated[int, Field(ge=0)]
    published_rows: Annotated[int, Field(ge=0)]
    pending: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def coherent_counts(self) -> ImportCountsDTO:
        if (
            self.validated > self.source_rows
            or self.valid + self.invalid > self.validated
            or not self.published_rows <= self.staged_committed_rows <= self.source_rows
            or self.pending != self.staged_committed_rows - self.published_rows
            or any(
                value > self.source_rows
                for value in (self.potential_duplicates, self.conflicts, self.excluded)
            )
        ):
            raise ValueError("Counts import không nhất quán; cờ trùng/xung đột có thể chồng lấn.")
        return self


CONTRACT_VERSION = 3
