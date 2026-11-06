"""Registration example only: a synthetic scratch note, not a domain record."""

import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select

from .audit import AuditService, require_version
from .errors import CoreError
from .modules import Migration, ModuleManifest, schema_checksum
from .time import utc_now

metadata = MetaData()
NOTES = Table(
    "example_notes",
    metadata,
    Column("id", String, primary_key=True),
    Column("text", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
)


class NoteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=200)
    request_key: str = Field(min_length=1, max_length=128)


class EditNote(NoteCommand):
    expected_version: int = Field(ge=1)


class NoteDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str
    text: str
    version: int
    created_at: str
    updated_at: str


def module_manifest() -> ModuleManifest:
    router = APIRouter(tags=["Foundation sample only"])

    @router.get("/notes/{note_id}", response_model=NoteDTO)
    def read_note(note_id: str, request: Request):
        with request.app.state.runtime.database.read() as conn:
            row = conn.execute(select(NOTES).where(NOTES.c.id == note_id)).mappings().first()
        if row is None:
            raise CoreError("NOT_FOUND", "Không tìm thấy ghi chú thử.", 404)
        return dict(row)

    @router.post("/notes", response_model=NoteDTO)
    def create_note(payload: NoteCommand, request: Request):
        runtime, actor = request.app.state.runtime, request.state.principal

        def operation(conn):
            now = utc_now()
            result = {
                "id": str(uuid.uuid4()),
                "text": payload.text,
                "version": 1,
                "created_at": now,
                "updated_at": now,
            }
            conn.execute(insert(NOTES).values(**result))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="example_note",
                entity_id=result["id"],
                action="create",
                after=result,
            )
            return result

        return runtime.writer.execute(
            actor.id,
            "example.notes.create",
            payload.request_key,
            {"text": payload.text},
            operation,
            authorize=lambda conn: runtime.auth.authorize(conn, actor, "example.write"),
        )

    @router.patch("/notes/{note_id}", response_model=NoteDTO)
    def update_note(note_id: str, payload: EditNote, request: Request):
        runtime, actor = request.app.state.runtime, request.state.principal

        def operation(conn):
            row = conn.execute(select(NOTES).where(NOTES.c.id == note_id)).mappings().first()
            if row is None:
                raise CoreError("NOT_FOUND", "Không tìm thấy ghi chú thử.", 404)
            version = require_version(row.version, payload.expected_version)
            result = dict(row) | {"text": payload.text, "version": version, "updated_at": utc_now()}
            conn.execute(NOTES.update().where(NOTES.c.id == note_id).values(**result))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="example_note",
                entity_id=note_id,
                action="update",
                before=dict(row),
                after=result,
            )
            return result

        return runtime.writer.execute(
            actor.id,
            "example.notes.update",
            payload.request_key,
            {"id": note_id, "text": payload.text, "expected_version": payload.expected_version},
            operation,
            authorize=lambda conn: runtime.auth.authorize(conn, actor, "example.write"),
        )

    return ModuleManifest(
        "example",
        "/example",
        permissions=("example.read", "example.write"),
        migrations=(
            Migration(
                "example",
                1,
                "synthetic_notes",
                metadata.create_all,
                checksum=schema_checksum(metadata),
            ),
        ),
        router=router,
    )
