"""Core HTTP response schema v1; domain bridge DTOs live in contracts.py."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResponseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldErrorDTO(ResponseDTO):
    field: str
    code: str
    message: str


class ErrorBodyDTO(ResponseDTO):
    code: str
    message: str
    field_errors: list[FieldErrorDTO]
    details: dict[str, Any]


class ErrorEnvelopeDTO(ResponseDTO):
    error: ErrorBodyDTO
    request_id: str


class HealthDTO(ResponseDTO):
    status: Literal["ok"]
    protocol_version: Literal[1]
    setup_required: bool


class UserDTO(ResponseDTO):
    id: str
    username: str
    role: Literal["admin", "operator"]
    permissions: list[str]
    version: int = Field(default=1, ge=1)


class AuthDTO(ResponseDTO):
    access_token: str
    user: UserDTO


class UserDetailDTO(ResponseDTO):
    id: str
    username: str
    role: Literal["admin", "operator"]
    version: int = Field(ge=1)
    active: bool


class LogoutDTO(ResponseDTO):
    logged_out: bool


class DataRootDTO(ResponseDTO):
    root_id: str
    format: Literal[1]
    available: bool


class FileDTO(ResponseDTO):
    id: str
    sha256: str
    size: int = Field(ge=0)
    category: Literal["workbooks", "documents", "imports", "reports"]
    original_name: str
    media_type: str
    created_at: str


class JobSubmittedDTO(ResponseDTO):
    job_id: str
    state: Literal["WAITING"]


class JobDTO(ResponseDTO):
    id: str
    kind: str
    actor: str
    state: Literal["WAITING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "RECOVERABLE"]
    phase: str
    attempts: int = Field(ge=0)
    generation: int = Field(ge=0)
    counts: dict[str, int]
    checkpoint: dict[str, Any]
    cancel_requested: bool
    error_code: str | None
    created_at: str
    updated_at: str


class GridIssueDTO(ResponseDTO):
    sheet: str
    row: int
    column: str
    cell: str
    code: str
    message: str


class GridRowDTO(ResponseDTO):
    id: str
    source_sheet: str
    source_row: int
    code: str
    description: str
    occurred_on: str
    amount: str
    formula: str
    issues: list[GridIssueDTO]


class GridPageDTO(ResponseDTO):
    items: list[GridRowDTO]
    total: int
    page: int
    page_size: int
    source_file_id: str
    source_sha256: str
    projection_note: str


class DocumentFileDTO(ResponseDTO):
    format: Literal["docx", "pdf"]
    file_id: str
    sha256: str
    size: int


class DocumentErrorDTO(ResponseDTO):
    format: Literal["docx", "pdf"]
    code: str
    message: str


class DocumentExportsDTO(ResponseDTO):
    snapshot_sha256: str
    documents: list[DocumentFileDTO]
    errors: list[DocumentErrorDTO]
