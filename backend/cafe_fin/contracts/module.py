"""Public registration and HTTP boundary for the contracts lane.

Coordinator binds an optional RecordsReadBridge at registration; manual entry always works.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from cafe_fin.core.api import require
from cafe_fin.core.auth import Principal
from cafe_fin.core.contracts import PartyDTO, RecordsReadBridge, WeighingDTO
from cafe_fin.core.errors import CoreError
from cafe_fin.core.http_types import ResponseDTO
from cafe_fin.core.modules import ModuleManifest
from cafe_fin.core.runtime import Runtime

from .migrations import MIGRATIONS
from .schemas import ContractData
from .service import ContractService


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[!-~]+$")


class SaveCommand(Command):
    data: ContractData


class EditCommand(SaveCommand):
    expected_version: int = Field(ge=1)


class VersionCommand(Command):
    expected_version: int = Field(ge=1)


class FormatCommand(Command):
    formats: list[Literal["docx", "pdf"]] = Field(min_length=1, max_length=2)


class ExportCommand(FormatCommand):
    expected_version: int = Field(ge=1)


class PreviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    data: ContractData


class TemplateCommand(VersionCommand):
    title: str = Field(min_length=1, max_length=1000)
    body: str = Field(min_length=1, max_length=200000)


class AttachmentCommand(Command):
    file_id: str
    version_id: str | None = None
    note: str = Field(default="", max_length=5000)
    status: Literal["uploaded", "user_recorded_signed"] = "uploaded"


class TotalsDTO(ResponseDTO):
    quantity_kg: str
    line_amounts: list[str]
    subtotal: str
    net_amount: str | None
    tax_amount: str | None
    grand_total: str | None
    tax_mode: Literal["unspecified", "none", "exclusive", "inclusive"]
    tax_rate: str | None
    rounding_policy: str
    amount_in_words: str | None


class DocumentDTO(ResponseDTO):
    title: str
    subtitle: str
    fields: list[list[str]]
    paragraphs: list[str]
    column_headers: list[str]
    rows: list[list[str]]


class TemplateDTO(ResponseDTO):
    id: str
    kind: Literal["purchase", "sale"]
    version: int
    title: str
    body: str
    sha256: str


class TemplatesDTO(ResponseDTO):
    items: list[TemplateDTO]


class PreviewDTO(ResponseDTO):
    document: DocumentDTO
    totals: TotalsDTO
    template: TemplateDTO
    snapshot_sha256: str


class SnapshotDTO(ResponseDTO):
    data: ContractData
    totals: TotalsDTO
    template: TemplateDTO
    document: DocumentDTO


class ContractDTO(ResponseDTO):
    id: str
    version: int
    number: str
    kind: Literal["purchase", "sale"]
    occurred_on: str
    party_name: str
    data: ContractData
    totals: TotalsDTO
    created_at: str
    updated_at: str
    created_by: str
    updated_by: str
    deleted_at: str | None


class ContractPage(ResponseDTO):
    items: list[ContractDTO]
    total: int
    page: int
    page_size: int


class FileStateDTO(ResponseDTO):
    status: Literal["pending", "rendered", "succeeded", "failed"]
    file_id: str | None
    sha256: str | None
    size: int | None
    error_code: str | None
    error_message: str | None
    updated_at: str


class VersionDTO(ResponseDTO):
    id: str
    contract_id: str
    sequence: int
    contract_version: int
    snapshot_sha256: str
    template_id: str
    template_version: int
    template_sha256: str
    created_at: str
    created_by: str
    snapshot: SnapshotDTO
    files: dict[Literal["docx", "pdf"], FileStateDTO]


class VersionPage(ResponseDTO):
    items: list[VersionDTO]
    total: int
    page: int
    page_size: int


class AttachmentDTO(ResponseDTO):
    id: str
    contract_id: str
    version_id: str | None
    file_id: str
    sha256: str
    original_name: str
    note: str
    status: Literal["uploaded", "user_recorded_signed"]
    created_at: str
    created_by: str
    signature_verification: Literal["not_performed"]


class AttachmentPage(ResponseDTO):
    items: list[AttachmentDTO]
    total: int
    page: int
    page_size: int


def module_manifest(
    records: RecordsReadBridge | None = None,
    *,
    records_factory: Callable[[Runtime, Principal], RecordsReadBridge] | None = None,
) -> ModuleManifest:
    if records is not None and records_factory is not None:
        raise ValueError("Chọn records hoặc records_factory; không cấu hình đồng thời.")
    router = APIRouter(tags=["Hợp đồng local"])

    def service(request, *, with_records=False):
        runtime = request.app.state.runtime
        bridge = records
        if with_records and records_factory is not None:
            # Construct a fresh provider with this request's current principal.
            # Manual workflows never initialize an optional records dependency.
            bridge = records_factory(runtime, request.state.principal)
        return ContractService(runtime, bridge)

    @router.get("", response_model=ContractPage)
    def list_contracts(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=500),
        search: str = Query("", max_length=200),
        sort: str = "-occurred_on",
        kind: Literal["purchase", "sale"] | None = None,
        include_deleted: bool = False,
    ):
        return service(request).page(
            page=page,
            page_size=page_size,
            search=search,
            sort=sort,
            kind=kind,
            include_deleted=include_deleted,
        )

    @router.get("/templates", response_model=TemplatesDTO)
    def list_templates(request: Request):
        return service(request).templates()

    @router.patch("/templates/{template_id}", response_model=TemplateDTO)
    def edit_template(template_id: str, request: Request, payload: TemplateCommand):
        actor = require(request, "contracts.templates")
        return service(request).edit_template(
            actor,
            payload.request_key,
            template_id,
            payload.expected_version,
            payload.title,
            payload.body,
        )

    @router.get("/sources/parties/{source_id}", response_model=PartyDTO)
    def source_party(source_id: str, request: Request):
        require(request, "records.read")
        return PartyDTO.model_validate_json(
            json.dumps(service(request, with_records=True).source_party(source_id))
        )

    @router.get("/sources/weighings/{source_id}", response_model=WeighingDTO)
    def source_weighing(source_id: str, request: Request):
        require(request, "records.read")
        return WeighingDTO.model_validate_json(
            json.dumps(service(request, with_records=True).source_weighing(source_id))
        )

    @router.post("/preview", response_model=PreviewDTO)
    def preview(request: Request, payload: PreviewCommand):
        return service(request).preview(payload.data)

    @router.post("", response_model=ContractDTO)
    def create_contract(request: Request, payload: SaveCommand):
        return service(request).save(request.state.principal, payload.request_key, payload.data)

    @router.get("/{contract_id}", response_model=ContractDTO)
    def read_contract(contract_id: str, request: Request):
        return service(request).read(contract_id)

    @router.patch("/{contract_id}", response_model=ContractDTO)
    def edit_contract(contract_id: str, request: Request, payload: EditCommand):
        return service(request).save(
            request.state.principal,
            payload.request_key,
            payload.data,
            identity=contract_id,
            expected_version=payload.expected_version,
        )

    @router.delete("/{contract_id}", response_model=ContractDTO)
    def delete_contract(contract_id: str, request: Request, payload: VersionCommand):
        return service(request).delete_or_restore(
            request.state.principal, payload.request_key, contract_id, payload.expected_version
        )

    @router.post("/{contract_id}/restore", response_model=ContractDTO)
    def restore_contract(contract_id: str, request: Request, payload: VersionCommand):
        return service(request).delete_or_restore(
            request.state.principal,
            payload.request_key,
            contract_id,
            payload.expected_version,
            restore=True,
        )

    @router.post("/{contract_id}/exports", response_model=VersionDTO)
    def export_contract(contract_id: str, request: Request, payload: ExportCommand):
        return service(request).export(
            request.state.principal,
            payload.request_key,
            contract_id,
            payload.expected_version,
            payload.formats,
        )

    @router.get("/{contract_id}/versions", response_model=VersionPage)
    def versions(
        contract_id: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=500),
    ):
        return service(request).versions(contract_id, page, page_size)

    @router.get("/{contract_id}/versions/{version_id}", response_model=VersionDTO)
    def version(contract_id: str, version_id: str, request: Request):
        return service(request).version(contract_id, version_id)

    @router.post("/{contract_id}/versions/{version_id}/files", response_model=VersionDTO)
    def add_format(contract_id: str, version_id: str, request: Request, payload: FormatCommand):
        return service(request).add_formats(
            request.state.principal, payload.request_key, contract_id, version_id, payload.formats
        )

    @router.get("/{contract_id}/versions/{version_id}/files/{format}")
    def download(contract_id: str, version_id: str, format: str, request: Request):
        runtime = request.app.state.runtime
        stored = service(request).file_for_version(contract_id, version_id, format)
        # Read+hash verification finishes before any success headers are sent.
        with runtime.files.read(stored.id) as source:
            content = source.read()
        return Response(
            content,
            media_type=stored.media_type,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(stored.original_name),
                "X-Content-SHA256": stored.sha256,
            },
        )

    @router.get("/{contract_id}/attachments", response_model=AttachmentPage)
    def attachments(
        contract_id: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=500),
    ):
        return service(request).attachments(contract_id, page, page_size)

    @router.post("/{contract_id}/attachments", response_model=AttachmentDTO)
    def add_attachment(contract_id: str, request: Request, payload: AttachmentCommand):
        return service(request).add_attachment(
            request.state.principal,
            payload.request_key,
            contract_id,
            payload.file_id,
            payload.version_id,
            payload.note,
            payload.status,
        )

    @router.get("/{contract_id}/attachments/{attachment_id}/content")
    def attachment_content(contract_id: str, attachment_id: str, request: Request):
        runtime, actor = request.app.state.runtime, request.state.principal
        contracts = service(request)
        stored = contracts.attachment_file(actor, contract_id, attachment_id)
        # No read transaction is held while verifying/reading the bounded document.
        with runtime.files.read(stored.id) as source:
            content = source.read()
        # A permission/reference change while hashing must fail before HTTP 200.
        if contracts.attachment_file(actor, contract_id, attachment_id) != stored:
            raise CoreError(
                "ATTACHMENT_FILE_CHANGED", "Thông tin chứng từ đã thay đổi; hãy thử tải lại.", 409
            )
        return Response(
            content,
            media_type=stored.media_type,
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(stored.original_name),
                "X-Content-SHA256": stored.sha256,
            },
        )

    @router.get("/{contract_id}/history")
    def history(
        contract_id: str,
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=500),
    ):
        from sqlalchemy import func, select

        from cafe_fin.core.audit import AuditService
        from cafe_fin.core.db import AUDIT

        runtime = request.app.state.runtime
        contract_id = service(request).read(contract_id)["id"]
        with runtime.reader() as conn:
            rows = AuditService.page(conn, "contracts.draft", contract_id, page, page_size)
            count = conn.execute(
                select(func.count())
                .select_from(AUDIT)
                .where(AUDIT.c.entity == "contracts.draft", AUDIT.c.entity_id == contract_id)
            ).scalar_one()
        return {
            "items": [dict(row) for row in rows],
            "total": count,
            "page": page,
            "page_size": page_size,
        }

    return ModuleManifest(
        "contracts",
        "/contracts",
        permissions=("contracts.read", "contracts.write", "contracts.templates"),
        migrations=MIGRATIONS,
        router=router,
    )
