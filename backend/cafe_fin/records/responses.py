"""Typed additive HTTP schemas; shared read bridge DTOs remain unchanged."""

from datetime import date, datetime
from typing import Literal

from pydantic import Field, create_model

from cafe_fin.core.contracts import FrozenDTO, InventorySummaryDTO

from .models import MODELS, Identity, Input


class SavedMetadata(Input):
    id: Identity
    version: int = Field(ge=1)
    created_at: str
    updated_at: str
    recorded_at: str
    created_by: Identity
    updated_by: Identity
    deleted_at: str | None
    order_key: str


class PageMetadata(Input):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)


RECORDS, PAGES, HISTORIES = {}, {}, {}
for kind, model in MODELS.items():
    saved = create_model(
        f"Records{kind.title()}DTO",
        __base__=SavedMetadata,
        **{
            key: (field.annotation, field)
            for key, field in model.model_fields.items()
            if key not in {"request_key", "expected_version"}
        },
    )
    RECORDS[kind] = saved
    PAGES[kind] = create_model(
        f"Records{kind.title()}PageDTO", __base__=PageMetadata, items=(list[saved], ...)
    )
    history = create_model(
        f"Records{kind.title()}RevisionDTO",
        __base__=Input,
        version=(int, ...),
        action=(str, ...),
        recorded_at=(str, ...),
        actor=(Identity, ...),
        data=(saved, ...),
    )
    HISTORIES[kind] = create_model(
        f"Records{kind.title()}HistoryDTO", __base__=PageMetadata, items=(list[history], ...)
    )


class InventoryMovementKindDTO(FrozenDTO):
    product_id: str
    warehouse_id: str
    entry_type: str
    in_kg: str
    out_kg: str


class InventoryBreakdownDTO(InventorySummaryDTO):
    breakdown: tuple[InventoryMovementKindDTO, ...] = ()


class MovementDTO(Input):
    id: Identity
    entry_id: Identity
    version: int
    product_id: Identity
    warehouse_id: Identity
    occurred_on: str
    order_key: str
    entry_type: str
    direction: str
    delta_kg: str
    line_numbers: list[int]


class MovementPageDTO(PageMetadata):
    items: list[MovementDTO]


class DashboardCounts(Input):
    farms: int
    farm_surveys: int
    customer_companies: int
    inbound_trades: int
    outbound_trades: int


class DashboardMetrics(Input):
    inbound_kg: str
    outbound_kg: str
    cash_in_vnd: str
    cash_out_vnd: str
    sales_order_value_vnd: str
    unpriced_sales_orders: int


class DashboardDay(DashboardMetrics):
    occurred_on: date


class RecordsDashboardDTO(Input):
    coverage: Literal["entered_records_only"]
    cutoff: datetime
    from_on: date
    through_on: date
    counts: DashboardCounts
    inventory: InventorySummaryDTO
    period: DashboardMetrics
    daily: list[DashboardDay]
