"""Module-owned command schemas. All quantities remain decimal text."""

import re
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def identity(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("ID phải là UUID canonical.")
    return value


def day(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Ngày phải có dạng YYYY-MM-DD.")
    date.fromisoformat(value)
    return value


Identity = Annotated[str, AfterValidator(identity)]
Day = Annotated[str, AfterValidator(day)]
Code = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^\S(?:.*\S)?$")]
Text = Annotated[str, Field(max_length=10000)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Command(Input):
    request_key: str = Field(min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)


class VersionCommand(Input):
    request_key: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1)


class Master(Command):
    code: Code
    name: str = Field(min_length=1, max_length=300)
    active: bool = True
    note: Text | None = None


class Contact(Input):
    kind: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=300)
    label: str | None = None


class Bank(Input):
    bank_name: str = Field(min_length=1, max_length=300)
    account_number: str = Field(min_length=1, max_length=100)
    account_holder: str | None = None
    branch: str | None = None


class Representative(Input):
    name: str = Field(min_length=1, max_length=300)
    title: str | None = None
    authorization_reference: str | None = None


class FarmPlot(Input):
    plot_code: str | None = Field(default=None, max_length=60)
    variety: str | None = Field(default=None, max_length=160)
    area_ha: str | None = None
    tree_count: int | None = Field(default=None, ge=0)
    tree_age: int | None = Field(default=None, ge=0)


class FarmSurvey(Input):
    season_year: int = Field(ge=1900, le=9999)
    grade: int = Field(ge=1, le=5)
    ripeness_pct: str | None = None
    notes: Text | None = None


class FarmProfile(Input):
    owner_name: str | None = Field(default=None, max_length=160)
    owner_id_card: str | None = Field(default=None, max_length=50)
    official_area_code: str | None = Field(default=None, max_length=100)
    internal_area_code: str | None = Field(default=None, max_length=100)
    plots: list[FarmPlot] = Field(default_factory=list, max_length=500)
    surveys: list[FarmSurvey] = Field(default_factory=list, max_length=500)


class Party(Master):
    # Farm normalization occurs inside the writer before uniqueness/immutability;
    # general party codes retain the Master whitespace constraint in the service.
    code: str = Field(min_length=1, max_length=80)
    type: str = Field(default="organization", min_length=1, max_length=80)
    roles: list[str] = Field(default_factory=list, max_length=20)
    tax_code: str | None = None
    address: str | None = None
    contacts: list[Contact] = Field(default_factory=list, max_length=50)
    bank_details: list[Bank] = Field(default_factory=list, max_length=20)
    representative: Representative | None = None
    profile_kind: Literal["general", "farm", "customer_company"] = "general"
    business_license: str | None = Field(default=None, max_length=100)
    farm: FarmProfile | None = None


class Product(Master):
    unit_id: Identity | None = None


class WeightLine(Input):
    product_id: Identity | None = None
    description: Text | None = None
    quantity_source: Literal["gross_tare", "direct_net"]
    gross_kg: str | None = None
    tare_kg: str | None = None
    net_kg: str | None = None
    note: Text | None = None


class Document(Command):
    code: Code
    occurred_on: Day
    # Optional descriptive time; chronological stock order is the frozen core day/order_key.
    occurred_at: str | None = None
    party_id: Identity | None = None
    physical_actor: str | None = None
    note: Text | None = None


class Weighing(Document):
    input_source: Literal["manual"] = "manual"
    vehicle_plate: str | None = None
    lines: list[WeightLine] = Field(min_length=1, max_length=500)


class EntryLine(Input):
    product_id: Identity | None = None
    warehouse_id: Identity | None = None
    quantity_kg: str | None = None
    direction: Literal["in", "out"] = "in"
    note: Text | None = None


class Entry(Document):
    entry_type: Literal["receipt", "issue", "production", "transfer", "opening", "adjustment"]
    status: Literal["draft", "posted", "cancelled"] = "draft"
    weighing_id: Identity | None = None
    trade_id: Identity | None = None
    commercial_amount_vnd: str | None = None
    lines: list[EntryLine] = Field(default_factory=list, max_length=500)


PriceKind = Literal["purchase_fresh", "purchase_processed", "sale"]


class PricePreview(Input):
    pricing_method: Literal["flat", "grade"]
    flat_price_vnd: str | None = None
    grade5_price_vnd: str | None = None


class PriceBoard(Command, PricePreview):
    code: Code | None = None
    name: str | None = Field(default=None, max_length=300)
    price_date: Day
    price_kind: PriceKind
    product_id: Identity | None = None
    active: bool = True
    note: Text | None = None


class PriceSnapshot(Input):
    price_board_id: Identity
    price_board_version: int = Field(ge=1)
    price_kind: PriceKind
    price_date: Day
    product_id: Identity | None
    grade: int | None = Field(ge=1, le=5)
    unit_price_vnd: str
    formula_version: Literal[1] = 1


class TradeLine(Input):
    farm_id: Identity | None = None
    product_id: Identity | None = None
    quantity_kg: str
    unit_price_vnd: str | None = None
    bag_count: int = Field(default=0, ge=0)
    grade: int | None = Field(default=None, ge=1, le=5)
    note: Text | None = None
    pricing_mode: Literal["manual", "daily"] = "manual"
    price_kind: PriceKind | None = None
    price_date: Day | None = None
    price_snapshot: PriceSnapshot | None = None


class Trade(Document):
    direction: Literal["inbound", "outbound"]
    status: Literal["recorded", "cancelled"] = "recorded"
    vehicle_plate: str | None = None
    weighing_id: Identity | None = None
    lines: list[TradeLine] = Field(min_length=1, max_length=500)


class TradePayment(Document):
    trade_id: Identity
    amount_vnd: str
    method: Literal["cash", "bank_transfer", "mixed", "other"]
    reference: Text | None = None


MODELS = {
    "parties": Party,
    "products": Product,
    "units": Master,
    "warehouses": Master,
    "weighings": Weighing,
    "entries": Entry,
    "trades": Trade,
    "trade-payments": TradePayment,
    "price-boards": PriceBoard,
}


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Thời điểm phải có múi giờ.")
    return parsed
