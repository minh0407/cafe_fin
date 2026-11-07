"""Records public registration and provider exports. Coordinator owns root wiring."""

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from cafe_fin.core.contracts import ReceivableSummaryDTO
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleManifest

from .bridge import RecordsReadProvider
from .dashboard import dashboard
from .migrations import MIGRATIONS
from .models import MODELS, Day, Identity, PriceKind, PricePreview, PriceSnapshot, VersionCommand
from .pricing import preview, quote
from .responses import (
    HISTORIES,
    PAGES,
    RECORDS,
    InventoryBreakdownDTO,
    MovementPageDTO,
    RecordsDashboardDTO,
)
from .service import RecordsService

__all__ = ["module_manifest", "RecordsReadProvider"]


class PageQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)
    search: str = Field(default="", max_length=300)
    sort: str = "code"
    filters: str = "{}"


def parse_filters(value):
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise CoreError("INVALID_FILTERS", "Bộ lọc phải là JSON object hợp lệ.", 422) from None


def _bind_resource(router, kind, path):
    model = MODELS[kind]

    def listing(request: Request, query: PageQuery = Query()):
        return RecordsService(request.app.state.runtime).list(
            kind,
            actor=request.state.principal,
            page=query.page,
            page_size=query.page_size,
            search=query.search,
            sort=query.sort,
            filters=parse_filters(query.filters),
        )

    def detail(document_id: str, request: Request):
        return RecordsService(request.app.state.runtime).get(
            kind, document_id, actor=request.state.principal
        )

    def history(
        document_id: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
    ):
        return RecordsService(request.app.state.runtime).history(
            kind, document_id, actor=request.state.principal, page=page, page_size=page_size
        )

    def create(payload, request: Request):
        data = payload.model_dump(mode="json", exclude={"request_key", "expected_version"})
        return RecordsService(request.app.state.runtime).save(
            kind,
            data,
            actor=request.state.principal,
            request_key=payload.request_key,
            expected_version=payload.expected_version,
        )

    def update(document_id: str, payload, request: Request):
        if payload.expected_version is None:
            raise CoreError("VERSION_REQUIRED", "Sửa hồ sơ cần expected_version dương.", 422)
        data = payload.model_dump(mode="json", exclude={"request_key", "expected_version"})
        return RecordsService(request.app.state.runtime).save(
            kind,
            data,
            actor=request.state.principal,
            request_key=payload.request_key,
            identity=document_id,
            expected_version=payload.expected_version,
        )

    create.__annotations__["payload"] = model
    update.__annotations__["payload"] = model
    router.add_api_route(
        path, listing, methods=["GET"], name=f"records_{kind}_list", response_model=PAGES[kind]
    )
    router.add_api_route(
        path, create, methods=["POST"], name=f"records_{kind}_create", response_model=RECORDS[kind]
    )
    router.add_api_route(
        path + "/{document_id}/history",
        history,
        methods=["GET"],
        name=f"records_{kind}_history",
        response_model=HISTORIES[kind],
    )
    router.add_api_route(
        path + "/{document_id}",
        detail,
        methods=["GET"],
        name=f"records_{kind}_get",
        response_model=RECORDS[kind],
    )
    router.add_api_route(
        path + "/{document_id}",
        update,
        methods=["PUT"],
        name=f"records_{kind}_update",
        response_model=RECORDS[kind],
    )

    def bind_command(command, suffix, method):
        def execute(document_id: str, payload: VersionCommand, request: Request):
            return RecordsService(request.app.state.runtime).command(
                kind,
                document_id,
                command,
                actor=request.state.principal,
                request_key=payload.request_key,
                expected_version=payload.expected_version,
            )

        router.add_api_route(
            path + "/{document_id}" + suffix,
            execute,
            methods=[method],
            name=f"records_{kind}_{command}",
            response_model=RECORDS[kind],
        )

    bind_command("delete", "", "DELETE")
    bind_command("restore", "/restore", "POST")
    if kind == "entries":
        bind_command("post", "/post", "POST")
        bind_command("cancel", "/cancel", "POST")


def module_manifest() -> ModuleManifest:
    router = APIRouter(tags=["Records"])
    # Static children precede /products/{document_id}.
    for kind, path in (
        ("units", "/products/units"),
        ("warehouses", "/products/warehouses"),
        ("parties", "/parties"),
        ("products", "/products"),
        ("weighings", "/weighings"),
        ("entries", "/entries"),
        ("trades", "/trades"),
        ("trade-payments", "/trade-payments"),
        ("price-boards", "/price-boards"),
    ):
        _bind_resource(router, kind, path)

    @router.post("/price-board-preview")
    def price_board_preview(payload: PricePreview, request: Request):
        service = RecordsService(request.app.state.runtime)
        with service._snapshot(request.state.principal) as conn:
            service._authorize(conn, request.state.principal)
            return preview(payload.model_dump(mode="json"))

    @router.get("/price-quote", response_model=PriceSnapshot)
    def price_quote(
        request: Request,
        price_kind: PriceKind,
        price_date: Day,
        product_id: Identity | None = None,
        grade: int | None = Query(None, ge=1, le=5),
    ):
        service = RecordsService(request.app.state.runtime)
        with service._snapshot(request.state.principal) as conn:
            conn.exec_driver_sql("BEGIN")
            service._authorize(conn, request.state.principal)
            return quote(
                conn,
                price_kind=price_kind,
                price_date=price_date,
                product_id=product_id,
                grade=grade,
            )

    @router.get("/records-dashboard", response_model=RecordsDashboardDTO)
    def records_dashboard(request: Request, from_on: date, through_on: date):
        return dashboard(request.app.state.runtime, request.state.principal, from_on, through_on)

    @router.get("/stock-movements", response_model=MovementPageDTO)
    def movements(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=500),
        filters: str = "{}",
    ):
        return RecordsService(request.app.state.runtime).movements(
            actor=request.state.principal,
            page=page,
            page_size=page_size,
            filters=parse_filters(filters),
        )

    @router.get("/stock-balances", response_model=InventoryBreakdownDTO)
    def balances(request: Request, from_on: date, through_on: date, cutoff: datetime | None = None):
        return RecordsReadProvider(
            request.app.state.runtime, request.state.principal
        ).inventory_breakdown(from_on, through_on, cutoff=cutoff or datetime.now(timezone.utc))

    @router.get("/receivables", response_model=ReceivableSummaryDTO)
    def receivables(request: Request, as_of: date, cutoff: datetime | None = None):
        return RecordsReadProvider(
            request.app.state.runtime, request.state.principal
        ).receivable_summary(as_of, cutoff=cutoff or datetime.now(timezone.utc))

    return ModuleManifest(
        "records",
        "/records",
        permissions=("records.read", "records.write"),
        migrations=MIGRATIONS,
        router=router,
    )
