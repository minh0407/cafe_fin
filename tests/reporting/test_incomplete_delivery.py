"""Incomplete Telegram configuration stays local through retries and real restart."""

import hashlib
import threading
from datetime import datetime, timezone

import pytest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram import DeliveryError, OfficialTelegram
from cafe_fin.reporting.telegram_migrations import ATTEMPTS, OUTBOX
from sqlalchemy import func, select

from tests.reporting.conftest import BOT_ID, BOT_TOKEN, CHAT_ID, TypedSyntheticSource


def incomplete(env, missing):
    clock = {"now": datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)}
    source = TypedSyntheticSource()
    service = ReportingService(
        env.runtime,
        actor_source_factory=lambda runtime, actor: source,
        secret_store=env.secrets,
        transport=env.transport,
        clock=lambda: clock["now"],
    )
    env.service = service
    service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="partial-target",
            expected_version=0,
            enabled=True,
            auto_generate_daily=True,
            send_at="18:00",
            chat_id="" if missing == "chat" else CHAT_ID,
            daily_book_ids=["cash"],
            daily_export_formats=["txt"],
        ),
    )
    if missing == "bot":
        # An OS entry alone cannot create a configured bot or connection proof.
        env.secrets.put(service.secret_key({"bot_id": BOT_ID}), {"bot_token": BOT_TOKEN})
    else:
        service.set_credentials(env.actor, models.Credentials(bot_token=BOT_TOKEN))
        if missing == "token":
            assert sender.check_connection(service, env.actor)["state"] == "CONNECTED"
            env.secrets.values.clear()
    adapter, calls = OfficialTelegram(), []

    def no_request(*args, **kwargs):
        calls.append("request")
        raise DeliveryError("TELEGRAM_API_REJECTED")  # No WAN even on regression.

    def no_send(*args, **kwargs):
        calls.append("send")
        raise AssertionError("Incomplete Telegram configuration must not send")

    adapter._request = no_request
    adapter.send_text = adapter.send_document = no_send
    service.transport = adapter
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    assert service.public_settings()["sender_status"] == "UNCONFIGURED"
    result = service.tick()
    assert result["generation"]["state"] == "COMPLETED"
    assert result["delivery"]["state"] == "UNCONFIGURED"
    return service, source, clock, adapter, calls


def assert_local_only(service, runtime, calls, *, expected_state="UNCONFIGURED"):
    rows = service.list("deliveries")["items"]
    assert len(rows) == 1 and rows[0]["state"] == expected_state
    assert rows[0]["provider"] == "telegram"
    assert rows[0]["attempts"] == 0 and rows[0]["message_id"] is None
    with runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(ATTEMPTS)).scalar_one() == 0
    report = service.list("reports")["items"][0]
    detail = service.detail(report["id"])
    assert report["state"] == "SAVED" and detail["exports"][0]["local_export"]["state"] == "READY"
    file = detail["exports"][0]
    path = runtime.root.resolve_key(file["local_export"]["relative_key"])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == file["sha256"]
    assert calls == []
    return rows[0], report


@pytest.mark.parametrize("missing", ["chat", "bot", "token", "proof"])
@pytest.mark.parametrize("retry_from", ["UNCONFIGURED", "FAILED"])
def test_incomplete_target_stays_local_through_catchup_retry_defense_and_real_restart(
    env,
    monkeypatch,
    missing,
    retry_from,
):
    service, source, clock, adapter, calls = incomplete(env, missing)
    row, report = assert_local_only(service, env.runtime, calls)
    assert service.catch_up(clock["now"]) == 0
    assert_local_only(service, env.runtime, calls)
    if retry_from == "FAILED":
        env.runtime.writer.run(
            lambda conn: conn.execute(
                OUTBOX.update()
                .where(OUTBOX.c.id == row["id"])
                .values(
                    state="FAILED",
                    error_code="TELEGRAM_API_REJECTED",
                )
            )
        )
    result = service.retry(
        env.actor,
        row["id"],
        models.Retry(
            request_key="manual-retry",
            expected_version=row["version"],
        ),
    )
    assert result["state"] == "UNCONFIGURED"
    assert sender.dispatch_one(service)["state"] == "UNCONFIGURED"
    assert_local_only(service, env.runtime, calls)
    # Defend even against an already persisted WAITING row, before any attempt.
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update().where(OUTBOX.c.id == row["id"]).values(state="WAITING")
        )
    )
    assert sender.dispatch_one(service)["state"] == "UNCONFIGURED"
    assert_local_only(service, env.runtime, calls)
    env.runtime.close()
    finished = threading.Event()
    original_tick = ReportingService.tick

    def fixed_startup_tick(self, now=None):
        result = original_tick(self, clock["now"])
        finished.set()
        return result

    monkeypatch.setattr(ReportingService, "tick", fixed_startup_tick)
    registry = ModuleRegistry(
        (
            module_manifest(
                source=source,
                secret_store=env.secrets,
                transport=adapter,
            ),
        )
    )
    runtime = Runtime(env.root, modules=registry)
    try:
        runtime.start()  # Genuine recovery, startup hook and JobRunner dispatch.
        assert finished.wait(5)
        restored = ReportingService(
            runtime,
            source=source,
            secret_store=env.secrets,
            transport=adapter,
        )
        _, preserved = assert_local_only(restored, runtime, calls)
        assert preserved["id"] == report["id"] and source.calls == 1
        assert restored.list("reports")["total"] == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("missing", ["bot", "chat"])
def test_complete_current_configuration_cannot_dispatch_empty_pinned_target(env, missing):
    service, _, _, adapter, calls = incomplete(env, missing)
    row, _ = assert_local_only(service, env.runtime, calls)
    service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="complete-target",
            expected_version=service.settings()["version"],
            enabled=True,
            auto_generate_daily=True,
            chat_id=CHAT_ID,
            send_at="18:00",
            daily_book_ids=["cash"],
            daily_export_formats=["txt"],
        ),
    )
    service.set_credentials(env.actor, models.Credentials(bot_token=BOT_TOKEN))
    service.transport = env.transport
    assert sender.check_connection(service, env.actor)["state"] == "CONNECTED"
    service.transport = adapter
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update().where(OUTBOX.c.id == row["id"]).values(state="WAITING")
        )
    )
    assert sender.dispatch_one(service)["state"] == "IDLE"
    current, _ = assert_local_only(service, env.runtime, calls, expected_state="WAITING")
    assert current["chat_id"] == row["chat_id"] and current["bot_id"] == row["bot_id"]
