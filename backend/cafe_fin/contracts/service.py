"""Module services: short authorized writes, immutable snapshots, independent outputs."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import asdict

from sqlalchemy import func, select

from cafe_fin.core.amounts import parse_kg, parse_money
from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.contracts import RecordsReadBridge
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.renderers import DocumentRenderer, DocumentSnapshot
from cafe_fin.core.time import utc_now

from .migrations.v001 import ATTACHMENTS, DRAFTS, LINES, OUTPUTS, TEMPLATES, VERSIONS
from .rendering import DEFAULT_TEMPLATES, build_document, template_hash, totals, validate_template
from .schemas import ContractData, computed_units

MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
MAX_OUTPUT_BYTES = 32 * 1024**2
MAX_ATTACHMENT_BYTES = 20 * 1024**2


class IndependentDocumentRenderer(DocumentRenderer):
    """Reuse core DOCX without initializing the unrelated PDF font subsystem.

    The core DOCX method has no instance setup. PDF setup is deferred to its own
    attempt, so a missing/corrupt PDF font cannot prevent a Word export.
    """

    def __init__(self):
        pass

    def pdf(self, snapshot):
        return DocumentRenderer().pdf(snapshot)


def _identity(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise CoreError("INVALID_ID", "Mã định danh phải là UUID.", 422) from None
    return str(parsed)


def restore_document(raw: dict) -> DocumentSnapshot:
    return DocumentSnapshot(
        title=raw["title"],
        subtitle=raw["subtitle"],
        fields=tuple(tuple(pair) for pair in raw["fields"]),
        paragraphs=tuple(raw["paragraphs"]),
        column_headers=tuple(raw["column_headers"]),
        rows=tuple(tuple(row) for row in raw["rows"]),
    )


class ContractService:
    def __init__(self, runtime, bridge: RecordsReadBridge | None = None):
        self.runtime = runtime
        self.bridge = bridge

    def _authorize(self, actor, permission="contracts.write"):
        return lambda conn: self.runtime.auth.authorize(conn, actor, permission)

    def _execute(self, actor, action, key, payload, effect, permission="contracts.write"):
        return self.runtime.writer.execute(
            actor.id,
            "contracts." + action,
            key,
            payload,
            effect,
            authorize=self._authorize(actor, permission),
        )

    @staticmethod
    def _draft(conn, identity, *, include_deleted=False):
        row = conn.execute(select(DRAFTS).where(DRAFTS.c.id == identity)).mappings().first()
        if row is None or (row.deleted_at and not include_deleted):
            raise CoreError("NOT_FOUND", "Không tìm thấy hợp đồng.", 404)
        return dict(row)

    @staticmethod
    def _dto(row):
        internal = {
            "data_json",
            "totals_json",
            "quantity_milli",
            "subtotal_cents",
            "net_cents",
            "tax_cents",
            "total_cents",
        }
        result = {k: v for k, v in row.items() if k not in internal}
        result["data"] = json.loads(row["data_json"])
        result["totals"] = json.loads(row["totals_json"])
        return result

    def read(self, identity):
        with self.runtime.reader() as conn:
            return self._dto(self._draft(conn, _identity(identity), include_deleted=True))

    def page(
        self,
        *,
        page=1,
        page_size=20,
        search="",
        sort="-occurred_on",
        kind=None,
        include_deleted=False,
    ):
        fields = {
            "occurred_on": DRAFTS.c.occurred_on,
            "number": DRAFTS.c.number,
            "updated_at": DRAFTS.c.updated_at,
            "party_name": DRAFTS.c.party_name,
        }
        if sort.removeprefix("-") not in fields or not 1 <= page_size <= 500 or page < 1:
            raise CoreError("INVALID_PAGE", "Phân trang hoặc cách sắp xếp không hợp lệ.", 422)
        query = select(DRAFTS)
        if not include_deleted:
            query = query.where(DRAFTS.c.deleted_at.is_(None))
        if search:
            # Escape LIKE metacharacters; search is literal user input.
            pattern = (
                "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            )
            query = query.where(
                DRAFTS.c.number.ilike(pattern, escape="\\")
                | DRAFTS.c.party_name.ilike(pattern, escape="\\")
            )
        if kind:
            if kind not in ("purchase", "sale"):
                raise CoreError("INVALID_FILTER", "Loại hợp đồng không hợp lệ.", 422)
            query = query.where(DRAFTS.c.kind == kind)
        field = fields[sort.removeprefix("-")]
        with self.runtime.reader() as conn:
            count = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(field.desc() if sort.startswith("-") else field, DRAFTS.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return {
                "items": [self._dto(dict(row)) for row in rows],
                "total": count,
                "page": page,
                "page_size": page_size,
            }

    def save(self, actor, key, data: ContractData, *, identity=None, expected_version=None):
        raw = data.model_dump(mode="json")
        computed = totals(data)
        units = computed_units(data)
        identity = _identity(identity) if identity else None
        payload = {"id": identity, "expected_version": expected_version, "data": raw}

        def effect(conn):
            before = self._draft(conn, identity) if identity else None
            now = utc_now()
            row = {
                "id": identity or str(uuid.uuid4()),
                "version": require_version(before["version"], expected_version) if before else 1,
                "number": data.number,
                "kind": data.kind,
                "occurred_on": data.occurred_on,
                "party_name": data.counterparty.name,
                "data_json": canonical_json(raw),
                "totals_json": canonical_json(computed),
                "quantity_milli": units["quantity_kg"],
                "subtotal_cents": units["subtotal"],
                "net_cents": units["net_amount"],
                "tax_cents": units["tax_amount"],
                "total_cents": units["grand_total"],
                "created_at": before["created_at"] if before else now,
                "updated_at": now,
                "created_by": before["created_by"] if before else actor.id,
                "updated_by": actor.id,
                "deleted_at": None,
            }
            if before:
                conn.execute(DRAFTS.update().where(DRAFTS.c.id == identity).values(**row))
            else:
                conn.execute(DRAFTS.insert().values(**row))
            conn.execute(LINES.delete().where(LINES.c.contract_id == row["id"]))
            for position, line in enumerate(data.lines):
                conn.execute(
                    LINES.insert().values(
                        contract_id=row["id"],
                        position=position,
                        quantity_milli=parse_kg(line.quantity_kg),
                        unit_price_cents=parse_money(line.unit_price),
                        amount_cents=units["line_amounts"][position],
                        gross_milli=parse_kg(line.gross_kg) if line.gross_kg is not None else None,
                        tare_milli=parse_kg(line.tare_kg) if line.tare_kg is not None else None,
                        net_milli=parse_kg(line.net_kg) if line.net_kg is not None else None,
                        source_json=canonical_json(line.source.model_dump(mode="json"))
                        if line.source
                        else None,
                    )
                )
            result = self._dto(row)
            AuditService.record(
                conn,
                actor=actor.id,
                entity="contracts.draft",
                entity_id=row["id"],
                action="update" if before else "create",
                before=self._dto(before) if before else None,
                after=result,
            )
            return result

        return self._execute(actor, "save", key, payload, effect)

    def delete_or_restore(self, actor, key, identity, expected_version, *, restore=False):
        identity = _identity(identity)

        def effect(conn):
            before = self._draft(conn, identity, include_deleted=True)
            now = utc_now()
            after = before | {
                "version": require_version(before["version"], expected_version),
                "deleted_at": None if restore else now,
                "updated_at": now,
                "updated_by": actor.id,
            }
            conn.execute(DRAFTS.update().where(DRAFTS.c.id == identity).values(**after))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="contracts.draft",
                entity_id=identity,
                action="restore" if restore else "soft_delete",
                before=self._dto(before),
                after=self._dto(after),
            )
            return self._dto(after)

        return self._execute(
            actor,
            "restore" if restore else "delete",
            key,
            {"id": identity, "expected_version": expected_version},
            effect,
        )

    def _template(self, conn, identity):
        row = (
            conn.execute(
                select(TEMPLATES)
                .where(TEMPLATES.c.id == identity)
                .order_by(TEMPLATES.c.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if row:
            return json.loads(row.payload_json) | {
                "id": row.id,
                "kind": row.kind,
                "version": row.version,
                "sha256": row.sha256,
            }
        default = next((dict(x) for x in DEFAULT_TEMPLATES if x["id"] == identity), None)
        if default is None:
            raise CoreError("TEMPLATE_NOT_FOUND", "Không tìm thấy mẫu hợp đồng.", 404)
        return default | {
            "version": 1,
            "sha256": template_hash({k: default[k] for k in ("title", "body")}),
        }

    def templates(self):
        with self.runtime.reader() as conn:
            return {"items": [self._template(conn, x["id"]) for x in DEFAULT_TEMPLATES]}

    def edit_template(self, actor, key, identity, expected_version, title, body):
        payload = {
            "id": identity,
            "expected_version": expected_version,
            "title": title,
            "body": body,
        }

        def effect(conn):
            previous = self._template(conn, identity)
            version = require_version(previous["version"], expected_version)
            updated = validate_template({"title": title, "body": body})
            digest = template_hash(updated)
            conn.execute(
                TEMPLATES.insert().values(
                    id=identity,
                    version=version,
                    kind=previous["kind"],
                    payload_json=canonical_json(updated),
                    sha256=digest,
                    created_at=utc_now(),
                    created_by=actor.id,
                )
            )
            result = updated | {
                "id": identity,
                "kind": previous["kind"],
                "version": version,
                "sha256": digest,
            }
            AuditService.record(
                conn,
                actor=actor.id,
                entity="contracts.template",
                entity_id=identity,
                action="revise",
                before=previous,
                after=result,
            )
            return result

        return self._execute(
            actor, "templates.revise", key, payload, effect, permission="contracts.templates"
        )

    def preview(self, data: ContractData):
        computed = totals(data)
        with self.runtime.reader() as conn:
            template = self._template(conn, data.template_id)
        document = build_document(data, computed, {k: template[k] for k in ("title", "body")})
        return {
            "document": json.loads(document.canonical_bytes()),
            "totals": computed,
            "template": template,
            "snapshot_sha256": document.sha256,
        }

    def export(self, actor, key, identity, expected_version, formats):
        identity = _identity(identity)
        formats = self._formats(formats)
        # The same lock serializes local fonts and competing requests for one output.
        # Writer transactions never encompass rendering or FileStore streaming.
        with self.runtime.render_lock:

            def prepare(conn):
                draft = self._draft(conn, identity)
                require_version(draft["version"], expected_version)
                data = ContractData.model_validate_json(draft["data_json"])
                template = self._template(conn, data.template_id)
                computed = totals(data)
                document = build_document(
                    data, computed, {k: template[k] for k in ("title", "body")}
                )
                snapshot = {
                    "data": data.model_dump(mode="json"),
                    "totals": computed,
                    "template": template,
                    "document": asdict(document),
                }
                encoded = canonical_json(snapshot)
                sequence = (
                    conn.execute(
                        select(func.max(VERSIONS.c.sequence)).where(
                            VERSIONS.c.contract_id == identity
                        )
                    ).scalar_one_or_none()
                    or 0
                )
                version_id = str(uuid.uuid4())
                row = {
                    "id": version_id,
                    "contract_id": identity,
                    "sequence": sequence + 1,
                    "contract_version": draft["version"],
                    "snapshot_json": encoded,
                    "snapshot_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "template_id": template["id"],
                    "template_version": template["version"],
                    "template_sha256": template["sha256"],
                    "created_at": utc_now(),
                    "created_by": actor.id,
                }
                conn.execute(VERSIONS.insert().values(**row))
                for format in formats:
                    conn.execute(
                        OUTPUTS.insert().values(
                            version_id=version_id,
                            format=format,
                            status="pending",
                            updated_at=utc_now(),
                        )
                    )
                AuditService.record(
                    conn,
                    actor=actor.id,
                    entity="contracts.export",
                    entity_id=version_id,
                    action="snapshot",
                    after={k: v for k, v in row.items() if k != "snapshot_json"},
                )
                return {"id": version_id}

            prepared = self._execute(
                actor,
                "exports.prepare",
                key,
                {"id": identity, "expected_version": expected_version, "formats": formats},
                prepare,
            )
            return self._render(actor, identity, prepared["id"], formats)

    @staticmethod
    def _formats(formats):
        if (
            not formats
            or len(formats) > 2
            or len(set(formats)) != len(formats)
            or any(x not in MEDIA for x in formats)
        ):
            raise CoreError("INVALID_FORMAT", "Chọn DOCX hoặc PDF, không lặp định dạng.", 422)
        return sorted(formats)

    def add_formats(self, actor, key, identity, version_id, formats):
        identity, version_id = _identity(identity), _identity(version_id)
        formats = self._formats(formats)
        with self.runtime.render_lock:

            def prepare(conn):
                self._version(conn, identity, version_id)
                for format in formats:
                    exists = conn.execute(
                        select(OUTPUTS.c.status).where(
                            OUTPUTS.c.version_id == version_id, OUTPUTS.c.format == format
                        )
                    ).first()
                    if not exists:
                        conn.execute(
                            OUTPUTS.insert().values(
                                version_id=version_id,
                                format=format,
                                status="pending",
                                updated_at=utc_now(),
                            )
                        )
                return {"id": version_id}

            self._execute(
                actor,
                "exports.add_formats",
                key,
                {"id": identity, "version_id": version_id, "formats": formats},
                prepare,
            )
            return self._render(actor, identity, version_id, formats)

    @staticmethod
    def _version(conn, identity, version_id):
        row = (
            conn.execute(
                select(VERSIONS).where(
                    VERSIONS.c.id == version_id, VERSIONS.c.contract_id == identity
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise CoreError("NOT_FOUND", "Không tìm thấy phiên bản hợp đồng.", 404)
        return dict(row)

    def version(self, identity, version_id):
        with self.runtime.reader() as conn:
            row = self._version(conn, _identity(identity), _identity(version_id))
            files = conn.execute(select(OUTPUTS).where(OUTPUTS.c.version_id == version_id))
            result = {k: v for k, v in row.items() if k != "snapshot_json"}
            result["snapshot"] = json.loads(row["snapshot_json"])
            result["files"] = {
                r.format: {
                    k: v
                    for k, v in dict(r._mapping).items()
                    if k not in ("rendered_bytes", "version_id", "format")
                }
                for r in files
            }
            return result

    def versions(self, identity, page=1, page_size=20):
        identity = _identity(identity)
        with self.runtime.reader() as conn:
            self._draft(conn, identity, include_deleted=True)
            query = select(VERSIONS.c.id).where(VERSIONS.c.contract_id == identity)
            count = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            ids = list(
                conn.execute(
                    query.order_by(VERSIONS.c.sequence.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).scalars()
            )
        return {
            "items": [self.version(identity, x) for x in ids],
            "total": count,
            "page": page,
            "page_size": page_size,
        }

    def _render(self, actor, identity, version_id, formats):
        version = self.version(identity, version_id)
        document = restore_document(version["snapshot"]["document"])
        for format in formats:
            with self.runtime.reader() as conn:
                row = dict(
                    conn.execute(
                        select(OUTPUTS).where(
                            OUTPUTS.c.version_id == version_id, OUTPUTS.c.format == format
                        )
                    )
                    .mappings()
                    .one()
                )
            try:
                if row["file_id"] is not None:
                    # Do not recreate a historical artifact whose bytes disappeared.
                    # A verified restore can make the same file available again.
                    with self.runtime.files.read(row["file_id"]):
                        pass
                    if row["status"] != "succeeded":

                        def available(conn):
                            self._authorize(actor)(conn)
                            conn.execute(
                                OUTPUTS.update()
                                .where(
                                    OUTPUTS.c.version_id == version_id, OUTPUTS.c.format == format
                                )
                                .values(
                                    status="succeeded",
                                    error_code=None,
                                    error_message=None,
                                    updated_at=utc_now(),
                                )
                            )
                            AuditService.record(
                                conn,
                                actor=actor.id,
                                entity="contracts.export",
                                entity_id=version_id,
                                action="file_available",
                                after={"format": format, "file_id": row["file_id"]},
                            )

                        self.runtime.writer.run(available)
                    continue
                if row["rendered_bytes"] is None:
                    rendered = getattr(IndependentDocumentRenderer(), format)(document)
                    content = rendered.content
                    if len(content) > MAX_OUTPUT_BYTES:
                        raise CoreError("FILE_TOO_LARGE", "Tài liệu vượt giới hạn 32 MiB.", 413)

                    def stage(conn):
                        conn.execute(
                            OUTPUTS.update()
                            .where(OUTPUTS.c.version_id == version_id, OUTPUTS.c.format == format)
                            .values(
                                rendered_bytes=content,
                                status="rendered",
                                error_code=None,
                                error_message=None,
                                updated_at=utc_now(),
                            )
                        )

                    self.runtime.writer.run(
                        lambda conn: (self._authorize(actor)(conn), stage(conn))
                    )
                else:
                    content = row["rendered_bytes"]
                file_key = hashlib.sha256(f"contracts:{version_id}:{format}".encode()).hexdigest()
                stored = self.runtime.files.put(
                    io.BytesIO(content),
                    category="documents",
                    original_name=f"contract-{identity}-v{version['sequence']}.{format}",
                    actor=actor.id,
                    request_key=file_key,
                    media_type=MEDIA[format],
                    authorize=self._authorize(actor),
                )

                def finish(conn):
                    self._authorize(actor)(conn)
                    conn.execute(
                        OUTPUTS.update()
                        .where(OUTPUTS.c.version_id == version_id, OUTPUTS.c.format == format)
                        .values(
                            status="succeeded",
                            file_id=stored.id,
                            sha256=stored.sha256,
                            size=stored.size,
                            rendered_bytes=None,
                            error_code=None,
                            error_message=None,
                            updated_at=utc_now(),
                        )
                    )
                    AuditService.record(
                        conn,
                        actor=actor.id,
                        entity="contracts.export",
                        entity_id=version_id,
                        action="file_saved",
                        before={"format": format, "status": row["status"]},
                        after={"format": format, "file_id": stored.id, "sha256": stored.sha256},
                    )

                self.runtime.writer.run(finish)
            except Exception as exc:
                code = exc.code if isinstance(exc, CoreError) else "RENDER_FAILED"
                message = (
                    exc.message if isinstance(exc, CoreError) else "Không xuất được định dạng này."
                )

                # A DB failure recording the error must propagate, never claim success.
                def fail(conn):
                    self._authorize(actor)(conn)
                    conn.execute(
                        OUTPUTS.update()
                        .where(
                            OUTPUTS.c.version_id == version_id,
                            OUTPUTS.c.format == format,
                        )
                        .values(
                            status="failed",
                            error_code=code,
                            error_message=message,
                            updated_at=utc_now(),
                        )
                    )
                    AuditService.record(
                        conn,
                        actor=actor.id,
                        entity="contracts.export",
                        entity_id=version_id,
                        action="file_failed",
                        before={"format": format, "status": row["status"]},
                        after={"format": format, "status": "failed", "error_code": code},
                    )

                self.runtime.writer.run(fail)
        return self.version(identity, version_id)

    def file_for_version(self, identity, version_id, format):
        if format not in MEDIA:
            raise CoreError("INVALID_FORMAT", "Định dạng không hợp lệ.", 422)
        version = self.version(identity, version_id)
        file = version["files"].get(format)
        if not file or file["status"] != "succeeded":
            raise CoreError("EXPORT_NOT_AVAILABLE", "Định dạng này chưa xuất thành công.", 409)
        return self.runtime.files.get(file["file_id"])

    def add_attachment(self, actor, key, identity, file_id, version_id, note, status):
        identity, file_id = _identity(identity), _identity(file_id)
        version_id = _identity(version_id) if version_id else None
        stored = self.runtime.files.get(file_id)
        if stored.category != "documents" or stored.size > MAX_ATTACHMENT_BYTES:
            raise CoreError(
                "ATTACHMENT_NOT_ALLOWED", "Chứng từ phải thuộc documents và tối đa 20 MiB.", 422
            )
        extension = stored.original_name.rsplit(".", 1)[-1].lower()
        if extension not in ("pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff"):
            raise CoreError(
                "ATTACHMENT_NOT_ALLOWED", "Chấp nhận PDF, DOCX, PNG, JPEG hoặc TIFF.", 422
            )
        with self.runtime.files.read(file_id) as source:
            signature = source.read(8)
        signatures = {
            "pdf": signature.startswith(b"%PDF-"),
            "docx": signature.startswith(b"PK\x03\x04"),
            "png": signature == b"\x89PNG\r\n\x1a\n",
            "jpg": signature.startswith(b"\xff\xd8\xff"),
            "jpeg": signature.startswith(b"\xff\xd8\xff"),
            "tif": signature.startswith((b"II*\0", b"MM\0*")),
            "tiff": signature.startswith((b"II*\0", b"MM\0*")),
        }
        if not signatures[extension]:
            raise CoreError(
                "ATTACHMENT_TYPE_MISMATCH", "Nội dung không khớp loại tệp đã chọn.", 422
            )

        def effect(conn):
            self._draft(conn, identity, include_deleted=True)
            if version_id:
                self._version(conn, identity, version_id)
            row = {
                "id": str(uuid.uuid4()),
                "contract_id": identity,
                "version_id": version_id,
                "file_id": file_id,
                "sha256": stored.sha256,
                "original_name": stored.original_name,
                "note": note,
                "status": status,
                "created_at": utc_now(),
                "created_by": actor.id,
            }
            conn.execute(ATTACHMENTS.insert().values(**row))
            AuditService.record(
                conn,
                actor=actor.id,
                entity="contracts.attachment",
                entity_id=row["id"],
                action="user_recorded",
                after=row,
            )
            return row | {"signature_verification": "not_performed"}

        return self._execute(
            actor,
            "attachments.add",
            key,
            {
                "id": identity,
                "file_id": file_id,
                "version_id": version_id,
                "note": note,
                "status": status,
            },
            effect,
        )

    def attachments(self, identity, page=1, page_size=20):
        identity = _identity(identity)
        with self.runtime.reader() as conn:
            self._draft(conn, identity, include_deleted=True)
            query = select(ATTACHMENTS).where(ATTACHMENTS.c.contract_id == identity)
            count = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
            rows = conn.execute(
                query.order_by(ATTACHMENTS.c.created_at.desc(), ATTACHMENTS.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return {
                "items": [dict(r) | {"signature_verification": "not_performed"} for r in rows],
                "total": count,
                "page": page,
                "page_size": page_size,
            }

    def source_party(self, identity):
        if self.bridge is None:
            raise CoreError(
                "RECORDS_BRIDGE_UNAVAILABLE", "Chưa nối dữ liệu đối tác; có thể nhập tay.", 503
            )
        value = self.bridge.lookup_party(_identity(identity))
        if value is None:
            raise CoreError("NOT_FOUND", "Không tìm thấy đối tác.", 404)
        return value.model_dump(mode="json")

    def source_weighing(self, identity):
        if self.bridge is None:
            raise CoreError(
                "RECORDS_BRIDGE_UNAVAILABLE", "Chưa nối dữ liệu phiếu cân; có thể nhập tay.", 503
            )
        value = self.bridge.get_weighing(_identity(identity))
        if value is None:
            raise CoreError("NOT_FOUND", "Không tìm thấy phiếu cân.", 404)
        return value.model_dump(mode="json")
