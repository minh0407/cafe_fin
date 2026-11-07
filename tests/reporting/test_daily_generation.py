import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.migrations import MIGRATIONS as V1_MIGRATIONS
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.schedule import list_runs
from cafe_fin.reporting.schedule_migrations import DAILY_RUNS
from cafe_fin.reporting.service import ReportingService
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.reporting.conftest import BOT_TOKEN, CHAT_ID, TypedSyntheticSource, saved


def setup_auto(env, *, formats=None, credentials=False):
    clock = {"now": datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)}
    source = TypedSyntheticSource()
    observed = []

    def factory(runtime, actor):
        observed.append((actor.id, actor.role, actor.version))
        return source

    service = ReportingService(
        env.runtime,
        actor_source_factory=factory,
        secret_store=env.secrets,
        transport=env.transport,
        clock=lambda: clock["now"],
    )
    env.service = service
    service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="auto-config",
            expected_version=0,
            enabled=True,
            auto_generate_daily=True,
            send_at="18:00",
            daily_book_ids=["cash", "missing"],
            daily_export_formats=formats or ["txt"],
            chat_id=CHAT_ID if credentials else "",
        ),
    )
    if credentials:
        service.set_credentials(
            env.actor,
            models.Credentials(bot_token=BOT_TOKEN),
        )
    if credentials:
        from cafe_fin.reporting.sender import check_connection

        assert check_connection(service, env.actor)["state"] == "CONNECTED"
        env.transport.verifications.clear()
    return service, source, clock, observed


def test_opt_in_creates_saves_selected_formats_and_unconfigured_queue_without_credentials(env):
    service, source, clock, observed = setup_auto(env, formats=["pdf", "xlsx", "txt"])
    assert service.tick()["generation"]["state"] == "NOT_DUE_OR_COMPLETE"
    assert source.calls == 0
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    output = service.tick()
    assert output["generation"]["state"] == "COMPLETED"
    reports = service.list("reports")
    assert reports["total"] == 1 and reports["items"][0]["state"] == "SAVED"
    report = service.detail(reports["items"][0]["id"])
    assert report["from_on"] == report["through_on"] == "2026-11-06"
    assert {x["format"] for x in report["exports"]} == {"pdf", "xlsx", "txt"}
    assert report["snapshot"]["cutoff"] == "2026-11-06T11:00:00+00:00"
    assert not report["snapshot"]["generation"]["created_late"]
    assert service.list("deliveries")["items"][0]["state"] == "UNCONFIGURED"
    assert service.list("deliveries")["items"][0]["attachment_export_id"] is None
    assert source.calls == 1 and observed == [(env.actor.id, "admin", env.actor.version)]
    service.tick()
    assert service.list("reports")["total"] == service.list("deliveries")["total"] == 1
    assert source.calls == 1 and not env.transport.texts


def test_concurrent_ticks_and_restart_create_one_snapshot_version_and_outbox(env):
    service, source, clock, _ = setup_auto(env)
    clock["now"] = datetime(2026, 11, 6, 11, 15, tzinfo=timezone.utc)
    entered, release = threading.Event(), threading.Event()
    capture = source.capture

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return capture(*args)

    source.capture = blocked
    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(service.tick)
        assert entered.wait(5)
        assert service.tick()["generation"]["state"] == "BUSY"
        release.set()
        assert running.result()["generation"]["state"] == "COMPLETED"
    report_id = service.list("reports")["items"][0]["id"]
    assert service.detail(report_id)["snapshot"]["generation"]["created_late"]
    env.runtime.close()
    runtime = Runtime(env.root, modules=env.registry)
    try:
        restarted = ReportingService(runtime, source=source, clock=lambda: clock["now"])
        restarted.recover()
        restarted.tick()
        assert restarted.list("reports")["total"] == restarted.list("deliveries")["total"] == 1
        assert restarted.list("reports")["items"][0]["version"] == 1
        assert source.calls == 1
    finally:
        runtime.close()


def test_configured_fake_channel_sends_once_after_local_exports_complete(env):
    service, source, clock, _ = setup_auto(env, credentials=True)
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    output = service.tick()
    assert output["generation"]["state"] == "COMPLETED"
    assert output["delivery"]["state"] == "SENT"
    assert output["delivery"]["message_id"] == "101"
    service.tick()
    assert source.calls == len(env.transport.texts) == 1
    assert service.list("reports")["total"] == service.list("deliveries")["total"] == 1


def test_missing_past_days_are_marked_without_capture_and_today_is_created_late(env):
    service, source, clock, _ = setup_auto(env)
    clock["now"] = datetime(2026, 11, 8, 11, 45, tzinfo=timezone.utc)
    service.tick()
    runs = list_runs(service)
    assert runs["total"] == 3
    assert {x["business_on"] for x in runs["items"] if x["state"] == "MISSED"} == {
        "2026-11-06",
        "2026-11-07",
    }
    assert source.calls == 1
    report = service.detail(service.list("reports")["items"][0]["id"])
    assert report["from_on"] == "2026-11-08"
    assert report["snapshot"]["generation"]["created_late"]
    assert report["snapshot"]["cutoff"] == "2026-11-08T11:45:00+00:00"


def test_existing_manual_report_is_reused_and_already_queued_older_version_wins(env):
    service, source, clock, _ = setup_auto(env)
    first = saved(env, "manual", first="2026-11-06", last="2026-11-06")
    queued = service.enqueue(env.actor, first["id"], models.Enqueue(request_key="manual-queue"))
    saved(env, "manual-revision", "Bổ sung", first="2026-11-06", last="2026-11-06")
    before = source.calls
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    result = service.tick()["generation"]
    assert result["policy"] == "REUSED_ALREADY_QUEUED_MANUAL"
    assert result["report_id"] == first["id"] and result["outbox_id"] == queued["id"]
    assert service.list("reports")["total"] == 2 and service.list("deliveries")["total"] == 1
    assert source.calls == before


def test_export_failure_preserves_saved_report_and_retries_without_recapture(env, monkeypatch):
    service, source, clock, _ = setup_auto(env)
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    export = service.export

    def fail(*args, **kwargs):
        raise OSError("SYNTHETIC-private-error-not-for-status")

    monkeypatch.setattr(service, "export", fail)
    failed = service.tick()
    assert failed["generation"]["state"] == "FAILED"
    assert failed["delivery"]["state"] == "BLOCKED"
    assert service.list("reports")["items"][0]["state"] == "SAVED"
    assert service.list("deliveries")["total"] == 0
    monkeypatch.setattr(service, "export", export)
    assert service.tick()["generation"]["state"] == "COMPLETED"
    assert source.calls == 1 and service.list("reports")["total"] == 1
    assert "private" not in json.dumps(list_runs(service))


def test_disable_during_capture_blocks_publication_and_no_actor_is_reresolved(env):
    service, source, clock, observed = setup_auto(env)
    env.runtime.auth.create_user(
        env.actor,
        username="otheradmin",
        password="synthetic-other-password",
        role="admin",
        request_key="other-admin",
    )
    other = env.runtime.auth.authenticate(
        env.runtime.auth.login("otheradmin", "synthetic-other-password")["access_token"]
    )
    capture = source.capture

    def revoked(*args):
        env.runtime.auth.update_user(
            other,
            env.actor.id,
            role="operator",
            active=False,
            expected_version=env.actor.version,
            request_key="disable-daily-owner",
        )
        return capture(*args)

    source.capture = revoked
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    output = service.tick()
    assert output["generation"]["state"] == "BLOCKED"
    assert service.list("reports")["total"] == service.list("deliveries")["total"] == 0
    assert len(observed) == 1
    assert service.tick()["generation"]["state"] == "BLOCKED"
    assert len(observed) == 1 and not env.transport.texts


def test_logout_does_not_require_replacement_session_for_authorized_daily_config(env):
    service, source, clock, _ = setup_auto(env)
    env.runtime.auth.logout(env.auth["access_token"])
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    assert service.tick()["generation"]["state"] == "COMPLETED"
    assert source.calls == 1 and service.list("reports")["total"] == 1


def test_demotion_after_saved_export_blocks_queue_using_same_captured_actor(env, monkeypatch):
    service, source, clock, observed = setup_auto(env)
    env.runtime.auth.create_user(
        env.actor,
        username="guardadmin",
        password="synthetic-guard-password",
        role="admin",
        request_key="guard-admin",
    )
    admin = env.runtime.auth.authenticate(
        env.runtime.auth.login("guardadmin", "synthetic-guard-password")["access_token"]
    )
    export = service.export

    def demoted(*args, **kwargs):
        result = export(*args, **kwargs)
        env.runtime.auth.update_user(
            admin,
            env.actor.id,
            role="operator",
            active=True,
            expected_version=env.actor.version,
            request_key="demote-after-export",
        )
        return result

    monkeypatch.setattr(service, "export", demoted)
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    assert service.tick()["generation"]["state"] == "BLOCKED"
    assert service.list("reports")["items"][0]["state"] == "SAVED"
    assert service.list("deliveries")["total"] == 0
    assert len(observed) == source.calls == 1


def test_config_change_during_capture_pins_old_inputs_and_requires_manual_handling(env):
    service, source, clock, _ = setup_auto(env)
    capture = source.capture

    def changed(*args):
        old = service.settings()
        service.update_settings(
            env.actor,
            models.DeliverySettings(
                request_key="changed-config",
                expected_version=old["version"],
                enabled=True,
                auto_generate_daily=True,
                send_at="18:00",
                daily_book_ids=["another"],
                daily_export_formats=["txt"],
            ),
        )
        return capture(*args)

    source.capture = changed
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    result = service.tick()["generation"]
    assert result["state"] == "NEEDS_MANUAL"
    assert service.list("deliveries")["total"] == 0
    with env.runtime.reader() as conn:
        row = conn.execute(select(DAILY_RUNS)).mappings().one()
        assert json.loads(row.pins_json)["daily_book_ids"] == ["cash", "missing"]
    assert source.calls == 1


def test_admin_identity_is_server_derived_bounded_config_and_v1_checksum_unchanged(env):
    service, _, _, _ = setup_auto(env)
    assert service.settings()["scheduled_actor_id"] == env.actor.id
    with pytest.raises(ValidationError):
        models.DeliverySettings(
            request_key="spoof", expected_version=1, scheduled_actor_id="another-admin"
        )
    with pytest.raises(ValidationError):
        models.DeliverySettings(
            request_key="too-many", expected_version=1, daily_book_ids=[str(x) for x in range(101)]
        )
    with pytest.raises(IntegrityError):
        from cafe_fin.reporting.schedule import insert_run

        def mutate(conn):
            row = insert_run(conn, "2026-11-06", service.settings(conn))
            conn.execute(
                DAILY_RUNS.update().where(DAILY_RUNS.c.id == row.id).values(pins_json="{}")
            )

        env.runtime.writer.run(mutate)
    assert (
        env.runtime.modules.ordered()[0].migrations[0].fingerprint == V1_MIGRATIONS[0].fingerprint
    )


def test_clock_crossing_vietnam_midnight_before_capture_marks_missed_without_old_source_read(env):
    service, source, clock, _ = setup_auto(env)
    factory = service.actor_source_factory

    def crosses_midnight(runtime, actor):
        clock["now"] = datetime(2026, 11, 6, 17, 0, tzinfo=timezone.utc)
        return factory(runtime, actor)

    service.actor_source_factory = crosses_midnight
    clock["now"] = datetime(2026, 11, 6, 16, 59, 59, tzinfo=timezone.utc)
    result = service.tick()["generation"]
    assert result["state"] == "MISSED"
    assert service.list("reports")["total"] == 0 and source.calls == 0


def test_migration_from_v1_preserves_saved_snapshot(tmp_path):
    manifest = module_manifest(source=TypedSyntheticSource())
    old = Runtime(
        tmp_path / "upgrade",
        initialize=True,
        modules=ModuleRegistry((replace(manifest, migrations=V1_MIGRATIONS),)),
    )
    try:
        auth = old.auth.setup("upgradeadmin", "synthetic-upgrade-password")
        actor = old.auth.authenticate(auth["access_token"])
        service = ReportingService(old, source=TypedSyntheticSource())
        preview = service.preview(
            actor, models.Preview(request_key="old", from_on="2026-11-06", through_on="2026-11-06")
        )
    finally:
        old.close()
    current = Runtime(tmp_path / "upgrade", modules=ModuleRegistry((manifest,)))
    try:
        service = ReportingService(current)
        assert service.detail(preview["id"])["sha256"] == preview["sha256"]
        assert list_runs(service)["total"] == 0
    finally:
        current.close()
