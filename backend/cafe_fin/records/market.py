"""Durable daily claim; network outside writer; board/evidence/audit atomic."""

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import Field
from sqlalchemy import insert, select

from cafe_fin.core.audit import AuditService, require_version
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import BUSINESS_ZONE

from . import market_http
from .market_parser import parse_banggianongsan_html
from .migrations import DOCUMENTS as D
from .migrations import REVISIONS as R
from .migrations.market_v2 import DAYS, EVIDENCE, SETTINGS
from .models import Input, PriceBoard
from .pricing import normalize_board

SERVICE_ID = "00000000-0000-4000-8000-000000000014"
PARSER_VERSION = "banggianongsan-v3"


class CheckCommand(Input):
    request_key: str = Field(min_length=1, max_length=128)


class SettingsCommand(CheckCommand):
    expected_version: int = Field(ge=1)
    enabled: bool


def now():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def today():
    return now().astimezone(BUSINESS_ZONE).date().isoformat()


def network_available():
    return os.getenv("CAFE_FIN_MARKET_NETWORK", "1") == "1"


def settings(conn):
    return conn.execute(select(SETTINGS).where(SETTINGS.c.id == 1)).mappings().one()


def existing_board(conn, day):
    return (
        conn.execute(
            select(D.c.id, D.c.version).where(
                D.c.kind == "price-boards", D.c.code_key == f"purchase_processed:{day}:all"
            )
        )
        .mappings()
        .first()
    )


def status_data(conn, day):
    config = settings(conn)
    row = conn.execute(select(DAYS).where(DAYS.c.price_date == day)).mappings().first()
    evidence = conn.execute(select(EVIDENCE).where(EVIDENCE.c.price_date == day)).mappings().first()
    board = existing_board(conn, day)
    snapshot = json.loads(evidence.snapshot_json) if evidence else None
    current = today()
    code = (
        "APPLIED"
        if evidence
        else "EXISTING_BOARD"
        if board
        else "NO_HISTORY"
        if day != current and not row
        else "DISABLED"
        if not config.enabled
        else "NETWORK_DISABLED"
        if not network_available()
        else "WAITING_SOURCE"
        if row
        and row.status == "FETCHING"
        and row.lease_expires_at
        and row.lease_expires_at <= stamp(now())
        else row.status
        if row
        else "WAITING_SOURCE"
    )
    return {
        "price_date": day,
        "today": current,
        "enabled": bool(config.enabled),
        "settings_version": config.version,
        "network_available": network_available(),
        "status": code,
        "source_url": market_http.SOURCE_URL,
        "board_id": board.id if board else None,
        "board_version": board.version if board else None,
        "attempts": row.attempts if row else 0,
        "last_checked_at": row.last_checked_at if row else None,
        "next_attempt_at": row.next_attempt_at if row else None,
        "detail": row.detail if row else None,
        "snapshot": snapshot,
    }


class MarketService:
    def __init__(self, runtime):
        self.runtime = runtime

    def authorize(self, conn, actor, permission):
        return self.runtime.auth.authorize(conn, actor, permission)

    def status(self, actor, day=None):
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            self.authorize(conn, actor, "records.read")
            return status_data(conn, day or today())

    def set_settings(self, actor, command):
        def operation(conn):
            old = dict(settings(conn))
            version = require_version(old["version"], command.expected_version)
            conn.execute(
                SETTINGS.update()
                .where(SETTINGS.c.id == 1)
                .values(enabled=int(command.enabled), version=version)
            )
            AuditService.record(
                conn,
                actor=actor.id,
                entity="records.market_settings",
                entity_id="1",
                action="update",
                before=old,
                after={"id": 1, "enabled": int(command.enabled), "version": version},
            )
            return status_data(conn, today())

        return self.runtime.writer.execute(
            actor.id,
            "records.market.settings",
            command.request_key,
            command.model_dump(exclude={"request_key"}),
            operation,
            authorize=lambda conn: self.authorize(conn, actor, "records.write"),
        )

    def check(self, actor=None, request_key=None):
        # Timer callbacks participate in the same lifecycle admission as HTTP.
        with self.runtime.maintenance.admit("/api/v1/records/market/processed/check"):
            return self._check(actor, request_key)

    def _check(self, actor, request_key):
        day, invocation = today(), str(uuid.uuid4())

        def claim(conn):
            config, at = settings(conn), now()
            if (
                not config.enabled
                or not network_available()
                or existing_board(conn, day)
                or conn.execute(select(EVIDENCE).where(EVIDENCE.c.price_date == day)).first()
            ):
                return {"owner": None}
            row = conn.execute(select(DAYS).where(DAYS.c.price_date == day)).mappings().first()
            if row and (
                (row.next_attempt_at and row.next_attempt_at > stamp(at))
                or (row.lease_expires_at and row.lease_expires_at > stamp(at))
            ):
                return {"owner": None}
            token = str(uuid.uuid4())
            values = {
                "status": "FETCHING",
                "attempts": (row.attempts if row else 0) + 1,
                "last_checked_at": stamp(at),
                "next_attempt_at": stamp(at + timedelta(minutes=5)),
                "lease_token": token,
                "lease_expires_at": stamp(at + timedelta(seconds=30)),
                "settings_version": config.version,
                "detail": "Đang kiểm tra nguồn giá.",
            }
            if row:
                conn.execute(DAYS.update().where(DAYS.c.price_date == day).values(**values))
            else:
                conn.execute(insert(DAYS).values(price_date=day, **values))
            return {"owner": invocation, "token": token}

        if actor is not None:
            ticket = self.runtime.writer.execute(
                actor.id,
                "records.market.check",
                request_key,
                {},
                claim,
                authorize=lambda conn: self.authorize(conn, actor, "records.write"),
            )
        else:
            ticket = self.runtime.writer.run(claim)
        if ticket.get("owner") == invocation:
            error, html, value, source_day = None, None, None, None
            fetched_at = now()
            try:
                html = market_http.download_html()
                fetched_at = now()
                value, source_day = parse_banggianongsan_html(
                    html, datetime.fromisoformat(day).date()
                )
            except market_http.MarketError as exc:
                error = exc
            except (ValueError, TypeError, RecursionError, OverflowError):
                error = market_http.MarketError(
                    "SOURCE_CHANGED", "Cấu trúc nguồn không còn phù hợp."
                )

            def finalize(conn):
                if actor is not None:
                    self.authorize(conn, actor, "records.write")
                row = conn.execute(select(DAYS).where(DAYS.c.price_date == day)).mappings().one()
                if row.lease_token != ticket["token"] or row.lease_expires_at <= stamp(now()):
                    return
                config = settings(conn)
                outcome = error
                if today() != day:
                    outcome = market_http.MarketError(
                        "DAY_CHANGED", "Đã sang ngày mới khi tải nguồn."
                    )
                elif not config.enabled or config.version != row.settings_version:
                    outcome = market_http.MarketError(
                        "WAITING_SOURCE", "Cấu hình đã thay đổi khi tải nguồn."
                    )
                elif not network_available():
                    outcome = market_http.MarketError(
                        "NETWORK_DISABLED", "Mạng nguồn giá đã bị tắt."
                    )
                elif existing_board(conn, day):
                    outcome = market_http.MarketError(
                        "EXISTING_BOARD", "Đã có bảng giá; giữ nguyên bảng hiện có."
                    )
                updates = {"lease_token": None, "lease_expires_at": None}
                if outcome:
                    retry = now() + timedelta(
                        hours=1 if outcome.code == "BLOCKED" else 0,
                        minutes=0 if outcome.code == "BLOCKED" else 5,
                    )
                    if outcome.retry_at:
                        retry = max(retry, outcome.retry_at)
                    updates.update(
                        status=outcome.code, detail=outcome.detail, next_attempt_at=stamp(retry)
                    )
                else:
                    board = create_board(conn, day, str(value))
                    evidence = {
                        "source_url": market_http.SOURCE_URL,
                        "source_date": source_day.isoformat(),
                        "price_vnd_per_kg": str(value),
                        "fetched_at": stamp(fetched_at),
                        "region": "Gia Lai",
                        "product": "ROBUSTA_GREEN_BEAN",
                        "unit": "VND/kg",
                        "parser_version": PARSER_VERSION,
                        "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
                        "board_id": board["id"],
                        "board_version": board["version"],
                    }
                    conn.execute(
                        insert(EVIDENCE).values(
                            price_date=day,
                            board_id=board["id"],
                            snapshot_json=canonical_json(evidence),
                        )
                    )
                    AuditService.record(
                        conn,
                        actor=SERVICE_ID,
                        entity="records.market_processed",
                        entity_id=day,
                        action="apply",
                        after=evidence,
                    )
                    updates.update(
                        status="APPLIED",
                        next_attempt_at=None,
                        detail="Đã áp giá nhân xô Robusta Gia Lai làm Grade 5.",
                    )
                conn.execute(DAYS.update().where(DAYS.c.price_date == day).values(**updates))

            self.runtime.writer.run(finalize)
        with self.runtime.reader() as conn:
            conn.exec_driver_sql("BEGIN")
            if actor is not None:
                self.authorize(conn, actor, "records.read")
            return status_data(conn, day)


def create_board(conn, day, price):
    """Internal collector-only insert using public board schema and normalizer."""
    data = PriceBoard.model_validate(
        {
            "request_key": "market-internal",
            "price_date": day,
            "price_kind": "purchase_processed",
            "pricing_method": "grade",
            "grade5_price_vnd": price,
        }
    ).model_dump(mode="json", exclude={"request_key", "expected_version"})
    normalize_board(data, None, lambda *_: None)  # product_id is fixed null, no reference.
    doc_id, timestamp = str(uuid.uuid4()), stamp(now())
    inserted = conn.execute(
        insert(D).values(
            id=doc_id,
            kind="price-boards",
            code_key=data["code"].casefold(),
            version=1,
            created_at=timestamp,
            created_by=SERVICE_ID,
        )
    )
    result = data | {
        "id": doc_id,
        "version": 1,
        "created_at": timestamp,
        "created_by": SERVICE_ID,
        "updated_at": timestamp,
        "updated_by": SERVICE_ID,
        "recorded_at": timestamp,
        "deleted_at": None,
        "order_key": f"{inserted.inserted_primary_key[0]:020d}",
    }
    conn.execute(
        insert(R).values(
            document_id=doc_id,
            version=1,
            recorded_at=timestamp,
            actor=SERVICE_ID,
            action="create",
            data_json=canonical_json(result),
        )
    )
    AuditService.record(
        conn,
        actor=SERVICE_ID,
        entity="records.price-boards",
        entity_id=doc_id,
        action="create",
        after=result,
    )
    return result


def guard_managed(conn, document_id):
    if conn.execute(select(EVIDENCE.c.board_id).where(EVIDENCE.c.board_id == document_id)).first():
        raise CoreError(
            "MARKET_BOARD_MANAGED", "Bảng tự động được giữ nguyên cùng bằng chứng nguồn.", 409
        )


def tick(runtime):
    if not network_available():
        return
    try:
        MarketService(runtime).check()
    except CoreError as exc:
        if exc.code not in {"MAINTENANCE_REQUIRED", "RUNTIME_CLOSED", "WRITER_CLOSED"}:
            raise
