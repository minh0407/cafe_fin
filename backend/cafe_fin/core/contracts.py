"""Version-one public read bridges. These types do not imply module implementation."""

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


def _aggregate_decimal(value: str, scale: int) -> str:
    """Summary totals can exceed int64; retain exact decimal text without float conversion."""
    if (
        len(value) > 256
        or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value)
        or ("." in value and len(value.split(".", 1)[1]) > scale)
    ):
        raise ValueError("Tổng phải là chuỗi số thập phân chính xác đúng scale.")
    return value


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
    opening_kg: str
    received_kg: str
    issued_kg: str
    closing_kg: str

    @field_validator("opening_kg", "received_kg", "issued_kg", "closing_kg")
    @classmethod
    def exact_kg(cls, value: str) -> str:
        return _aggregate_decimal(value, 3)


class InventorySummaryDTO(CutoffDTO):
    from_on: date
    through_on: date
    items: tuple[InventoryLineDTO, ...] = ()
    validation_flags: tuple[str, ...] = ()


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

    @field_validator("amount_vnd")
    @classmethod
    def exact_money(cls, value: str) -> str:
        return _aggregate_decimal(value, 2)


class BookSummaryDTO(CutoffDTO):
    book_id: NonEmpty
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


CONTRACT_VERSION = 1
