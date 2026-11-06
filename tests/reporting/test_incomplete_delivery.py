"""Incomplete targets are local-only; configuration absence is no send attempt."""

import hashlib
import threading
import time
from datetime import datetime, timezone

import pytest
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.migrations import ATTEMPTS, OUTBOX
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.zalo import DeliveryError, OfficialGMF
from sqlalchemy import func, select

from tests.reporting.test_daily_generation import setup_auto


def incomplete(env, monkeypatch, missing):
    service, source, clock, _ = setup_auto(env)
    service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="partial-target",
            expected_version=1,
            enabled=True,
            auto_generate_daily=True,
            send_at="18:00",
            oa_id="" if missing in {"oa", "both"} else "demo-oa",
            group_id="" if missing in {"group", "both"} else "demo-group",
            daily_book_ids=["cash"],
            daily_export_formats=["txt"],
        ),
    )
    config = service.settings()
    credential = {
        "access_token": "SYNTHETIC",
        "expires_at": int(time.time()) + 90000,
        "refresh_state": "READY",
        "app_id": "demo",
        "app_secret": "SYNTHETIC",
        "refresh_token": "SYNTHETIC",
    }
    # Deliberately present even for the empty-OA synthetic key: credential presence
    # alone must not make an incomplete target ready.
    env.secrets.put(service.secret_key(config), credential)
    adapter, calls = OfficialGMF(), []
    original_verify, original_token = adapter.verify, sender.access_token

    def observed_token(*args):
        calls.append("token")
        return original_token(*args)

    def observed_verify(*args):
        calls.append("verify")
        return original_verify(*args)

    def no_request(url, **kwargs):
        calls.append("request")
        raise DeliveryError("ZALO_API_REJECTED")  # Never WAN, even if regressed.

    def no_send(*args, **kwargs):
        calls.append("send")
        raise AssertionError("An incomplete target must not send")

    adapter.verify = observed_verify
    adapter._request = no_request
    adapter.send_text = adapter.send_file = adapter.upload = no_send
    monkeypatch.setattr(sender, "access_token", observed_token)
    service.transport = adapter
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    result = service.tick()
    assert result["generation"]["state"] == "COMPLETED"
    assert result["delivery"]["state"] == "UNCONFIGURED"
    return service, source, clock, adapter, calls, credential


def assert_local_only(service, runtime, calls):
    rows = service.list("deliveries")["items"]
    assert len(rows) == 1 and rows[0]["state"] == "UNCONFIGURED"
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


@pytest.mark.parametrize("missing", ["oa", "group", "both"])
@pytest.mark.parametrize("retry_from", ["UNCONFIGURED", "FAILED"])
def test_incomplete_target_stays_local_through_catchup_retry_defense_and_real_restart(
    env, monkeypatch, missing, retry_from
):
    service, source, clock, adapter, calls, _ = incomplete(env, monkeypatch, missing)
    row, report = assert_local_only(service, env.runtime, calls)
    assert service.catch_up(clock["now"]) == 0
    assert_local_only(service, env.runtime, calls)
    if retry_from == "FAILED":
        env.runtime.writer.run(
            lambda conn: conn.execute(
                OUTBOX.update()
                .where(OUTBOX.c.id == row["id"])
                .values(state="FAILED", error_code="ZALO_API_REJECTED")
            )
        )
    result = service.retry(
        env.actor,
        row["id"],
        models.Retry(request_key="manual-retry", expected_version=row["version"]),
    )
    assert result["state"] == "UNCONFIGURED"
    assert sender.dispatch_one(service)["state"] == "UNCONFIGURED"
    assert_local_only(service, env.runtime, calls)
    # Persisted legacy WAITING row must be repaired before claim/attempt/token.
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
        (module_manifest(source=source, secret_store=env.secrets, transport=adapter),)
    )
    runtime = Runtime(env.root, modules=registry)
    try:
        runtime.start()  # actual recovery + startup hook + JobRunner dispatch
        assert finished.wait(5)
        restored = ReportingService(
            runtime, source=source, secret_store=env.secrets, transport=adapter
        )
        _, preserved = assert_local_only(restored, runtime, calls)
        assert preserved["id"] == report["id"] and source.calls == 1
        assert restored.list("reports")["total"] == 1
    finally:
        runtime.close()


@pytest.mark.parametrize("missing", ["oa", "group"])
def test_complete_current_configuration_cannot_dispatch_legacy_row_with_empty_pinned_target(
    env, monkeypatch, missing
):
    service, _, _, _, calls, credential = incomplete(env, monkeypatch, missing)
    row, _ = assert_local_only(service, env.runtime, calls)
    service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="complete-target",
            expected_version=2,
            enabled=True,
            auto_generate_daily=True,
            oa_id="demo-oa",
            group_id="demo-group",
            send_at="18:00",
            daily_book_ids=["cash"],
            daily_export_formats=["txt"],
        ),
    )
    env.secrets.put(service.secret_key(service.settings()), credential)
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update().where(OUTBOX.c.id == row["id"]).values(state="WAITING")
        )
    )
    assert sender.dispatch_one(service)["state"] == "UNCONFIGURED"
    current, _ = assert_local_only(service, env.runtime, calls)
    assert current["destination"] == row["destination"] and current["oa_id"] == row["oa_id"]
