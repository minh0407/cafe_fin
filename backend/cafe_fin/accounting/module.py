"""Explicit lane exports. Coordinator owns the two shared registry edits."""

import json
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, select

from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleManifest
from cafe_fin.core.time import utc_now

from . import schema as s
from .jobs import AccountingJobs
from .service import (
    AccountingService,
    _batch,
    _book,
    _queue,
    check_page,
    identity,
    page_result,
    row_dto,
)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_key: str = Field(min_length=1, max_length=128)


class VersionCommand(Command):
    expected_version: int = Field(ge=1)


class BookCommand(Command):
    name: str = Field(min_length=1, max_length=120)
    columns: list[dict] = Field(default_factory=list, max_length=256)
    semantics: dict = Field(default_factory=dict)


class SchemaCommand(VersionCommand):
    columns: list[dict] = Field(max_length=256)
    semantics: dict = Field(default_factory=dict)


class RowCommand(Command):
    values: dict[str, str | None]


class EditRow(RowCommand):
    expected_version: int = Field(ge=1)


class ImportCommand(Command):
    book_id: str
    file_id: str
    profile: dict = Field(default_factory=dict)
    allow_duplicate_file: bool = False


class MappingCommand(VersionCommand):
    mapping: dict[str, str]
    profile: dict | None = None


class CellPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_id: str
    expected_version: int = Field(ge=1)
    values: dict[str, str | None]


class PatchCommand(VersionCommand):
    patches: list[CellPatch] = Field(min_length=1, max_length=500)


class DuplicateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_id: str = Field(min_length=1, max_length=128)
    decision: Literal["keep", "skip"]


class DecisionsCommand(VersionCommand):
    decisions: list[DuplicateDecision] = Field(default_factory=list, max_length=500)
    all_pending_duplicates: Literal["keep", "skip"] | None = None


class ConfirmCommand(VersionCommand):
    staging_revision: int = Field(ge=1)
    mapping_revision: int = Field(ge=1)
    decision_revision: int = Field(ge=1)
    validation_token: str = Field(min_length=1)
    mode: str = "valid_rows_only"


class ExportCommand(Command):
    format: str = "csv"


class ProfileCommand(Command):
    name: str
    mapping: dict[str, str]
    profile: dict


def module_manifest():
    state = {}
    router = APIRouter(tags=["Independent accounting"])

    def services(request):
        return AccountingService(request.app.state.runtime), request.state.principal

    @router.get("/books")
    def books(request: Request, page: int = 1, page_size: int = 100):
        service, actor = services(request)
        return service.get_books(actor, page, page_size)

    @router.get("/books/{book_id}")
    def book(book_id: str, request: Request):
        service, _ = services(request)
        from .service import book_dto

        with service.rt.reader() as conn:
            return book_dto(_book(conn, book_id))

    @router.post("/books")
    def create_book(payload: BookCommand, request: Request):
        service, actor = services(request)
        return service.create_book(actor, **payload.model_dump())

    @router.patch("/books/{book_id}/schema")
    def schema(book_id: str, payload: SchemaCommand, request: Request):
        service, actor = services(request)
        return service.update_schema(actor, book_id, **payload.model_dump())

    @router.get("/books/{book_id}/rows")
    def rows(
        book_id: str,
        request: Request,
        page: int = 1,
        page_size: int = 200,
        search: str = "",
        sort: str = "",
        filters: str = "[]",
        deleted: bool = False,
    ):
        service, actor = services(request)
        try:
            parsed = json.loads(filters)
            if (
                not isinstance(parsed, list)
                or len(parsed) > 20
                or any(not isinstance(x, dict) for x in parsed)
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise CoreError(
                "FILTER_INVALID", "Bộ lọc phải là danh sách tối đa 20 điều kiện."
            ) from None
        return service.list_rows(actor, book_id, page, page_size, search, sort, parsed, deleted)

    @router.get("/rows/{row_id}")
    def get_row(row_id: str, request: Request):
        service, _ = services(request)
        with service.rt.reader() as conn:
            return row_dto(service._entry(conn, row_id, include_deleted=True))

    @router.post("/books/{book_id}/rows")
    def create_row(book_id: str, payload: RowCommand, request: Request):
        service, actor = services(request)
        return service.create_row(actor, book_id, **payload.model_dump())

    @router.patch("/rows/{row_id}")
    def edit_row(row_id: str, payload: EditRow, request: Request):
        service, actor = services(request)
        return service.mutate_row(actor, row_id, **payload.model_dump())

    @router.post("/rows/{row_id}/delete")
    def delete_row(row_id: str, payload: VersionCommand, request: Request):
        service, actor = services(request)
        return service.mutate_row(actor, row_id, **payload.model_dump(), action="delete")

    @router.post("/rows/{row_id}/restore")
    def restore_row(row_id: str, payload: VersionCommand, request: Request):
        service, actor = services(request)
        return service.mutate_row(actor, row_id, **payload.model_dump(), action="restore")

    @router.get("/import-jobs")
    def batches(book_id: str, request: Request, page: int = 1, page_size: int = 100):
        service, actor = services(request)
        return service.list_batches(actor, book_id, page, page_size)

    @router.post("/import-jobs")
    def upload(payload: ImportCommand, request: Request):
        service, actor = services(request)
        return service.create_batch(actor, **payload.model_dump())

    @router.get("/import-jobs/{batch_id}")
    def batch(batch_id: str, request: Request):
        service, actor = services(request)
        return service.get_batch(actor, batch_id)

    @router.get("/import-jobs/{batch_id}/staging")
    def staging(
        batch_id: str,
        request: Request,
        page: int = 1,
        page_size: int = 200,
        status: str = "",
        search: str = "",
    ):
        service, actor = services(request)
        return service.staging_page(actor, batch_id, page, page_size, status, search)

    @router.post("/import-jobs/{batch_id}/mapping")
    def mapping(batch_id: str, payload: MappingCommand, request: Request):
        service, actor = services(request)
        return service.mapping(actor, batch_id, **payload.model_dump())

    @router.post("/import-jobs/{batch_id}/patches")
    def patches(batch_id: str, payload: PatchCommand, request: Request):
        service, actor = services(request)
        return service.patch_staging(actor, batch_id, **payload.model_dump())

    @router.post("/import-jobs/{batch_id}/decisions")
    def decisions(batch_id: str, payload: DecisionsCommand, request: Request):
        service, actor = services(request)
        return service.decisions(actor, batch_id, **payload.model_dump())

    @router.post("/import-jobs/{batch_id}/validate")
    def validate(batch_id: str, payload: VersionCommand, request: Request):
        service, actor = services(request)
        return service.validate(actor, batch_id, **payload.model_dump())

    @router.post("/import-jobs/{batch_id}/confirm")
    def confirm(batch_id: str, payload: ConfirmCommand, request: Request):
        service, actor = services(request)
        return service.confirm(actor, batch_id, payload.model_dump())

    @router.post("/import-jobs/{batch_id}/cancel")
    def cancel(batch_id: str, payload: Command, request: Request):
        service, actor = services(request)
        return service.cancel_resume(actor, batch_id, "cancel")

    @router.post("/import-jobs/{batch_id}/resume")
    def resume(batch_id: str, payload: Command, request: Request):
        service, actor = services(request)
        return service.cancel_resume(actor, batch_id, "resume")

    @router.get("/import-jobs/{batch_id}/issues")
    def issue_page(batch_id: str, request: Request, page: int = 1, page_size: int = 200):
        service, actor = services(request)
        check_page(page, page_size)
        with service.rt.reader() as conn:
            _batch(conn, batch_id, actor)
            predicate = [s.issues.c.batch_id == batch_id, s.issues.c.resolved == 0]
            total = conn.execute(
                select(func.count()).select_from(s.issues).where(*predicate)
            ).scalar_one()
            rows = conn.execute(
                select(s.issues)
                .where(*predicate)
                .order_by(s.issues.c.row_id, s.issues.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return page_result(
                [json.loads(r.issue_json) | {"row_id": r.row_id} for r in rows],
                total,
                page,
                page_size,
            )

    @router.get("/import-jobs/{batch_id}/duplicates")
    def duplicates(batch_id: str, request: Request, page: int = 1, page_size: int = 100):
        service, actor = services(request)
        result = service.staging_page(actor, batch_id, page, page_size, "duplicates")
        # Detail is bounded; exact matching stays a warning unless explicit business key.
        with service.rt.reader() as conn:
            batch = _batch(conn, batch_id, actor)
            from .duplicate_compatibility import historical_shapes, projected_fingerprints
            from .service import effective_decision, published_target, stage_dto, visible

            old_shapes = historical_shapes(conn, _book(conn, batch["book_id"]))
            for row in result["items"]:
                keys = conn.execute(
                    select(
                        s.stage.c.fingerprint,
                        s.stage.c.candidate_key,
                        s.stage.c.business_key,
                        s.stage.c.typed_json,
                    ).where(s.stage.c.batch_id == batch_id, s.stage.c.row_id == row["row_id"])
                ).one()
                pred = s.entries.c.fingerprint == keys.fingerprint
                old_fps = tuple(projected_fingerprints(json.loads(keys.typed_json), old_shapes))
                if old_fps:
                    pred |= s.entries.c.fingerprint.in_(old_fps)
                if keys.candidate_key:
                    pred |= s.entries.c.candidate_key == keys.candidate_key
                if keys.business_key:
                    pred |= s.entries.c.business_key == keys.business_key
                matches = conn.execute(
                    select(s.entries)
                    .where(
                        s.entries.c.book_id == batch["book_id"],
                        pred,
                        s.entries.c.deleted_at.is_(None),
                        visible(),
                    )
                    .limit(10)
                ).mappings()
                row["matches"] = [row_dto(r) for r in matches]
                file_pred = s.stage.c.fingerprint == keys.fingerprint
                if keys.candidate_key:
                    file_pred |= s.stage.c.candidate_key == keys.candidate_key
                if keys.business_key:
                    file_pred |= s.stage.c.business_key == keys.business_key
                peers = conn.execute(
                    select(
                        *[c for c in s.stage.c if c.name not in ("target_id", "decision")],
                        published_target().label("target_id"),
                        effective_decision().label("decision"),
                    )
                    .where(
                        s.stage.c.batch_id == batch_id, s.stage.c.row_id != row["row_id"], file_pred
                    )
                    .order_by(s.stage.c.source_row, s.stage.c.row_id)
                    .limit(10)
                ).mappings()
                row["file_matches"] = [stage_dto(peer) for peer in peers]
        return result

    @router.get("/books/{book_id}/summary")
    def summary(book_id: str, request: Request, from_on: str, through_on: str):
        service, actor = services(request)
        return service.summary(actor, book_id, from_on, through_on)

    @router.get("/import-jobs/{batch_id}/summary")
    def preview_summary(batch_id: str, request: Request, from_on: str, through_on: str):
        service, actor = services(request)
        return service.preview_summary(actor, batch_id, from_on, through_on)

    @router.post("/import-jobs/{batch_id}/exports")
    def export_errors(batch_id: str, payload: ExportCommand, request: Request):
        service, actor = services(request)
        if payload.format not in ("csv", "xlsx"):
            raise CoreError("EXPORT_FORMAT_INVALID", "Chỉ hỗ trợ CSV hoặc XLSX.")

        def op(conn):
            batch = _batch(conn, batch_id, actor)
            book = _book(conn, batch["book_id"])
            export_id = identity()
            conn.execute(
                insert(s.exports).values(
                    id=export_id,
                    book_id=book["id"],
                    actor_id=actor.id,
                    actor_json=json.dumps(actor.public()),
                    format=payload.format,
                    data_revision=book["data_revision"],
                    schema_revision=book["schema_revision"],
                    created_at=utc_now(),
                )
            )
            _queue(
                conn,
                actor,
                "accounting.export",
                export_id,
                {
                    "dataset": "issues",
                    "batch_id": batch_id,
                    "revision": batch["revision"],
                    "validation_token": batch["validation_token"],
                },
            )
            return {"export_id": export_id}

        result = service.write(
            actor,
            "issues.export",
            payload.request_key,
            {"batch_id": batch_id, "format": payload.format},
            op,
        )
        service.dispatch()
        with service.rt.reader() as conn:
            job_id = conn.execute(
                select(s.exports.c.job_id).where(s.exports.c.id == result["export_id"])
            ).scalar_one()
        return result | {"job_id": job_id}

    @router.post("/books/{book_id}/exports")
    def export(book_id: str, payload: ExportCommand, request: Request):
        service, actor = services(request)
        if payload.format not in ("csv", "xlsx"):
            raise CoreError("EXPORT_FORMAT_INVALID", "Chỉ xuất CSV hoặc XLSX dẫn xuất.")

        def op(conn):
            book = _book(conn, book_id)
            export_id = identity()
            conn.execute(
                insert(s.exports).values(
                    id=export_id,
                    book_id=book_id,
                    actor_id=actor.id,
                    actor_json=json.dumps(actor.public()),
                    format=payload.format,
                    data_revision=book["data_revision"],
                    schema_revision=book["schema_revision"],
                    created_at=utc_now(),
                )
            )
            _queue(conn, actor, "accounting.export", export_id, {})
            return {"export_id": export_id}

        result = service.write(
            actor,
            "export.create",
            payload.request_key,
            {"book_id": book_id, "format": payload.format},
            op,
        )
        service.dispatch()
        with service.rt.reader() as conn:
            job_id = conn.execute(
                select(s.exports.c.job_id).where(s.exports.c.id == result["export_id"])
            ).scalar_one()
        return result | {"job_id": job_id}

    @router.get("/exports/{job_id}")
    def export_status(job_id: str, request: Request):
        service, actor = services(request)
        with service.rt.reader() as conn:
            row = (
                conn.execute(select(s.exports).where(s.exports.c.job_id == job_id))
                .mappings()
                .first()
            )
            if row is None:
                raise CoreError("EXPORT_NOT_FOUND", "Không tìm thấy bản xuất.", 404)
            if row.actor_id != actor.id and actor.role != "admin":
                raise CoreError("PERMISSION_DENIED", "Bản xuất thuộc tài khoản khác.", 403)
            return service.rt.jobs.status(job_id) | {
                "file_id": row.file_id,
                "derived": True,
                "numeric_encoding": "numeric_up_to_15_digits_else_exact_text"
                if row.format == "xlsx"
                else "exact_text",
            }

    @router.get("/books/{book_id}/mapping-profiles")
    def profiles(book_id: str, request: Request):
        service, _ = services(request)
        with service.rt.reader() as conn:
            rows = (
                conn.execute(select(s.profiles).where(s.profiles.c.book_id == book_id).limit(500))
                .mappings()
                .all()
            )
        return {
            "items": [
                {k: v for k, v in dict(r).items() if not k.endswith("_json")}
                | {"mapping": json.loads(r.mapping_json), "profile": json.loads(r.profile_json)}
                for r in rows
            ]
        }

    @router.post("/books/{book_id}/mapping-profiles")
    def save_profile(book_id: str, payload: ProfileCommand, request: Request):
        service, actor = services(request)

        def op(conn):
            book = _book(conn, book_id)
            if len(payload.name) > 120:
                raise CoreError("PROFILE_INVALID", "Tên profile quá dài.")
            profile_id = identity()
            conn.execute(
                insert(s.profiles).values(
                    id=profile_id,
                    book_id=book_id,
                    name=payload.name,
                    version=1,
                    schema_revision=book["schema_revision"],
                    mapping_json=json.dumps(payload.mapping),
                    profile_json=json.dumps(payload.profile),
                    created_by=actor.id,
                )
            )
            return {"id": profile_id, "version": 1}

        return service.write(
            actor,
            "profile.create",
            payload.request_key,
            payload.model_dump() | {"book_id": book_id},
            op,
        )

    def startup(runtime):
        state["jobs"] = AccountingJobs(runtime)
        AccountingService(runtime).dispatch()

    def worker(context, payload):
        return state["jobs"].run(context, payload)

    return ModuleManifest(
        "accounting",
        "/accounting",
        permissions=(
            "accounting.read",
            "accounting.write",
            "accounting.configure",
            "accounting.restore",
        ),
        migrations=s.MIGRATIONS,
        router=router,
        job_handlers={
            k: JobHandler(worker, resumable=True)
            for k in (
                "accounting.parse",
                "accounting.validate",
                "accounting.commit",
                "accounting.export",
            )
        },
        on_startup=startup,
    )
