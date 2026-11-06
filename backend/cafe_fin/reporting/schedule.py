"""Finite local daily generation; persistent pins, no historical balance invention."""

import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from cafe_fin.core.audit import AuditService
from cafe_fin.core.db import canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.time import utc_now

from . import models
from .migrations import LOCKS, OUTBOX, REPORTS
from .restore import REVIEW_CODE, held_report, suspended
from .schedule_migrations import DAILY_CURSOR, DAILY_RUNS
from .service import new_id

PROFILE = "delivery"
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def due_at(now, config):
    local = now.astimezone(ZoneInfo(config["timezone"]))
    return datetime.combine(local.date(), time.fromisoformat(config["send_at"]), local.tzinfo)


@contextmanager
def generation_lock(service):
    owner = new_id()

    def acquire(conn):
        if conn.execute(select(LOCKS.c.id).where(LOCKS.c.id == "daily_generation")).first():
            return False
        conn.execute(LOCKS.insert().values(id="daily_generation", owner=owner))
        return True

    acquired = service.runtime.writer.run(acquire)
    try:
        yield acquired
    finally:
        if acquired:
            service.runtime.writer.run(
                lambda conn: conn.execute(
                    LOCKS.delete().where(LOCKS.c.id == "daily_generation", LOCKS.c.owner == owner)
                )
            )


def dto(row):
    return {
        key: row[key]
        for key in (
            "id",
            "profile_id",
            "business_on",
            "state",
            "phase",
            "actor_id",
            "config_version",
            "report_id",
            "outbox_id",
            "policy",
            "attempts",
            "error_code",
            "created_at",
            "updated_at",
        )
    }


def list_runs(service, page=1, page_size=25):
    with service.runtime.reader() as conn:
        total = conn.execute(select(func.count()).select_from(DAILY_RUNS)).scalar_one()
        rows = conn.execute(
            select(DAILY_RUNS)
            .order_by(DAILY_RUNS.c.business_on.desc(), DAILY_RUNS.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).mappings()
        return {
            "items": [dto(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


def row_for(conn, identity):
    return conn.execute(select(DAILY_RUNS).where(DAILY_RUNS.c.id == identity)).mappings().one()


def captured_report(conn, run):
    if run.report_id:
        return conn.execute(select(REPORTS).where(REPORTS.c.id == run.report_id)).mappings().one()
    return (
        conn.execute(
            select(REPORTS).where(
                REPORTS.c.created_by == run.actor_id,
                REPORTS.c.command_key == "scheduled-preview-" + run.id,
            )
        )
        .mappings()
        .first()
    )


def manual_report(conn, day, config):
    series = hashlib.sha256(
        canonical_json(
            {"from_on": day, "through_on": day, "book_ids": config["daily_book_ids"]}
        ).encode()
    ).hexdigest()
    # Prefer a version already queued for this destination, even if a newer manual
    # version exists: automatic work must not silently send a second version.
    queued = (
        conn.execute(
            select(REPORTS)
            .join(OUTBOX, OUTBOX.c.report_id == REPORTS.c.id)
            .where(
                REPORTS.c.series_key == series,
                ~held_report(REPORTS.c.id),
                OUTBOX.c.destination == config["group_id"],
                OUTBOX.c.oa_id == config["oa_id"],
                func.json_extract(REPORTS.c.snapshot_json, "$.period.date_range_contract")
                == models.DATE_RANGE_CONTRACT,
            )
            .order_by(OUTBOX.c.created_at, OUTBOX.c.id)
            .limit(1)
        )
        .mappings()
        .first()
    )
    if queued:
        return queued, "REUSED_ALREADY_QUEUED_MANUAL"
    saved = (
        conn.execute(
            select(REPORTS)
            .where(
                REPORTS.c.series_key == series,
                REPORTS.c.state == "SAVED",
                ~held_report(REPORTS.c.id),
                func.json_extract(REPORTS.c.snapshot_json, "$.period.date_range_contract")
                == models.DATE_RANGE_CONTRACT,
            )
            .order_by(REPORTS.c.version.desc())
            .limit(1)
        )
        .mappings()
        .first()
    )
    if saved:
        return saved, "REUSED_SAVED_MANUAL"
    held = conn.execute(
        select(REPORTS.c.id)
        .where(REPORTS.c.series_key == series, held_report(REPORTS.c.id))
        .limit(1)
    ).first()
    # Do not sidestep an uncertain restored delivery by creating an automatic
    # replacement version of the same day/book selection.
    return None, "RESTORE_REQUIRES_MANUAL" if held else "GENERATED_CURRENT_DAY"


def insert_run(conn, day, config, *, missed=False, scheduled_due_at=None):
    report, policy = manual_report(conn, day, config)
    identity, now = new_id(), utc_now()
    state = "MISSED" if missed and report is None else "PENDING"
    if policy == "RESTORE_REQUIRES_MANUAL":
        state = "NEEDS_MANUAL"
    elif state == "MISSED":
        policy = "MISSED_NO_SNAPSHOT"
    conn.execute(
        DAILY_RUNS.insert().values(
            id=identity,
            profile_id=PROFILE,
            business_on=day,
            state=state,
            phase="exports" if report is not None else "capture",
            pins_json=canonical_json(config | {"scheduled_due_at": scheduled_due_at}),
            actor_id=config["scheduled_actor_id"],
            config_version=config["version"],
            report_id=report.id if report is not None else None,
            outbox_id=None,
            policy=policy,
            attempts=0,
            error_code=REVIEW_CODE
            if state == "NEEDS_MANUAL"
            else "MISSED_REQUIRES_MANUAL"
            if state == "MISSED"
            else None,
            created_at=now,
            updated_at=now,
        )
    )
    return row_for(conn, identity)


def prepare(service, actor, config, now):
    today = now.astimezone(VN).date()

    def operation(conn):
        service.guard_schedule(conn, config, actor)
        cursor = (
            conn.execute(select(DAILY_CURSOR).where(DAILY_CURSOR.c.profile_id == PROFILE))
            .mappings()
            .first()
        )
        next_day = date.fromisoformat(
            cursor.next_unchecked_on if cursor else config["auto_activated_on"]
        )
        # Bounded bookkeeping for missing days. Capturing today is independent of
        # this cursor, so a long gap cannot delay today's scheduled capture.
        for _ in range(100):
            if next_day >= today:
                break
            existing = (
                conn.execute(
                    select(DAILY_RUNS).where(
                        DAILY_RUNS.c.profile_id == PROFILE,
                        DAILY_RUNS.c.business_on == next_day.isoformat(),
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                insert_run(conn, next_day.isoformat(), config, missed=True)
            elif (
                existing.report_id is None
                and existing.state not in {"COMPLETED", "MISSED"}
                and existing.error_code != REVIEW_CODE
            ):
                captured = captured_report(conn, existing)
                if captured is not None:
                    conn.execute(
                        DAILY_RUNS.update()
                        .where(DAILY_RUNS.c.id == existing.id)
                        .values(
                            report_id=captured.id,
                            state="PENDING",
                            phase="save",
                            updated_at=utc_now(),
                        )
                    )
                else:
                    conn.execute(
                        DAILY_RUNS.update()
                        .where(DAILY_RUNS.c.id == existing.id)
                        .values(
                            state="MISSED",
                            error_code="MISSED_REQUIRES_MANUAL",
                            updated_at=utc_now(),
                        )
                    )
            next_day += timedelta(days=1)
        if cursor:
            conn.execute(
                DAILY_CURSOR.update()
                .where(DAILY_CURSOR.c.profile_id == PROFILE)
                .values(next_unchecked_on=next_day.isoformat(), updated_at=utc_now())
            )
        else:
            conn.execute(
                DAILY_CURSOR.insert().values(
                    profile_id=PROFILE, next_unchecked_on=next_day.isoformat(), updated_at=utc_now()
                )
            )
        current = (
            conn.execute(
                select(DAILY_RUNS).where(
                    DAILY_RUNS.c.profile_id == PROFILE,
                    DAILY_RUNS.c.business_on == today.isoformat(),
                )
            )
            .mappings()
            .first()
        )
        if now >= due_at(now, config) and current is None:
            current = insert_run(
                conn,
                today.isoformat(),
                config,
                scheduled_due_at=due_at(now, config).astimezone(timezone.utc).isoformat(),
            )
        eligible = {"PENDING", "FAILED", "BLOCKED"}
        if current is None or current.state not in eligible:
            current = (
                conn.execute(
                    select(DAILY_RUNS)
                    .where(DAILY_RUNS.c.state.in_(eligible), DAILY_RUNS.c.report_id.is_not(None))
                    .order_by(DAILY_RUNS.c.business_on, DAILY_RUNS.c.id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if current is None:
            return None
        if current.config_version != config["version"]:
            conn.execute(
                DAILY_RUNS.update()
                .where(DAILY_RUNS.c.id == current.id)
                .values(
                    state="NEEDS_MANUAL", error_code="SCHEDULE_CONFIG_CHANGED", updated_at=utc_now()
                )
            )
            return dict(row_for(conn, current.id))
        conn.execute(
            DAILY_RUNS.update()
            .where(DAILY_RUNS.c.id == current.id)
            .values(
                state="RUNNING",
                attempts=current.attempts + 1,
                error_code=None,
                updated_at=utc_now(),
            )
        )
        return dict(row_for(conn, current.id))

    return service.runtime.writer.run(operation)


def update_run(service, actor, config, identity, **values):
    def operation(conn):
        service.guard_schedule(conn, config, actor)
        conn.execute(
            DAILY_RUNS.update()
            .where(DAILY_RUNS.c.id == identity)
            .values(**values, updated_at=utc_now())
        )
        AuditService.record(
            conn,
            actor=actor.id,
            entity="reporting_daily_run",
            entity_id=identity,
            action="progress",
            after=values,
        )
        return dto(row_for(conn, identity))

    return service.runtime.writer.run(operation)


def generate_daily(service, now):
    if now.tzinfo is None:
        raise ValueError("Aware scheduler time required")
    config = service.settings()
    if suspended(config):
        return {"state": "RESTORE_SUSPENDED"}
    if not config["enabled"] or not config["auto_generate_daily"]:
        return {"state": "DISABLED"}
    try:
        actor = service.resolve_scheduled_actor(config)
    except CoreError:
        return {"state": "BLOCKED", "error_code": "SCHEDULE_ACTOR_BLOCKED"}
    with generation_lock(service) as acquired:
        if not acquired:
            return {"state": "BUSY"}
        run = prepare(service, actor, config, now)
        if run is None:
            return {"state": "NOT_DUE_OR_COMPLETE"}
        if run["state"] == "NEEDS_MANUAL":
            return run
        identity = run["id"]
        try:
            with service.runtime.reader() as conn:
                report = captured_report(conn, row_for(conn, identity))
            if report is None:
                if run["business_on"] != now.astimezone(VN).date().isoformat():
                    return update_run(
                        service,
                        actor,
                        config,
                        identity,
                        state="MISSED",
                        error_code="MISSED_REQUIRES_MANUAL",
                    )
                service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
                pinned_due = datetime.fromisoformat(
                    json.loads(run["pins_json"])["scheduled_due_at"]
                )
                report = service.preview(
                    actor,
                    models.Preview(
                        request_key="scheduled-preview-" + identity,
                        from_on=run["business_on"],
                        through_on=run["business_on"],
                        book_ids=config["daily_book_ids"],
                        reason="Tạo báo cáo cuối ngày theo cấu hình Admin.",
                    ),
                    capture_metadata={
                        "kind": "scheduled_daily",
                        "profile_id": PROFILE,
                        "run_id": identity,
                        "created_late": service.clock() > pinned_due,
                        "scheduled_due_at": pinned_due.isoformat(),
                    },
                )
            else:
                report = dict(report)
            update_run(service, actor, config, identity, report_id=report["id"], phase="save")
            service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
            service.save(
                actor,
                report["id"],
                models.Save(
                    request_key="scheduled-save-" + identity, expected_version=report["version"]
                ),
            )
            update_run(service, actor, config, identity, phase="exports")
            for format in config["daily_export_formats"]:
                service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
                service.export(
                    actor,
                    report["id"],
                    models.Export(
                        request_key=f"scheduled-export-{identity}-{format}", format=format
                    ),
                )
            update_run(service, actor, config, identity, phase="queue")
            service.runtime.writer.run(lambda conn: service.guard_schedule(conn, config, actor))
            # Keep any explicitly chosen existing manual attachment; never select a new one.
            with service.runtime.reader() as conn:
                existing = (
                    conn.execute(
                        select(OUTBOX).where(
                            OUTBOX.c.report_id == report["id"],
                            OUTBOX.c.destination == config["group_id"],
                            OUTBOX.c.oa_id == config["oa_id"],
                        )
                    )
                    .mappings()
                    .first()
                )
            if existing is not None:
                outbox_id = existing.id
            else:
                queued = service.enqueue(
                    actor,
                    report["id"],
                    models.Enqueue(request_key="scheduled-queue-" + identity),
                    expected_config_version=config["version"],
                )
                outbox_id = queued["id"]
            return update_run(
                service,
                actor,
                config,
                identity,
                state="COMPLETED",
                phase="done",
                outbox_id=outbox_id,
            )
        except Exception as exc:
            # Preserve captured snapshots, files and queue receipts. No raw exception
            # or arbitrary provider content enters scheduler status/audit.
            code = "SCHEDULE_STEP_FAILED"
            state = "FAILED"
            if isinstance(exc, CoreError) and exc.code in {
                "SESSION_EXPIRED",
                "PERMISSION_DENIED",
                "BACKGROUND_ACTOR_UNAVAILABLE",
            }:
                code, state = "SCHEDULE_ACTOR_BLOCKED", "BLOCKED"
            elif isinstance(exc, CoreError) and exc.code == "SCHEDULE_CONFIG_CHANGED":
                code, state = exc.code, "NEEDS_MANUAL"
            elif isinstance(exc, CoreError) and exc.code == "SCHEDULE_DAY_MISSED":
                code, state = "MISSED_REQUIRES_MANUAL", "MISSED"

            def record_failure(conn):
                conn.execute(
                    DAILY_RUNS.update()
                    .where(DAILY_RUNS.c.id == identity)
                    .values(state=state, error_code=code, updated_at=utc_now())
                )
                return dto(row_for(conn, identity))

            return service.runtime.writer.run(record_failure)
