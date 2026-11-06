import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.migrations import LOCKS, OUTBOX
from cafe_fin.reporting.sender import check_connection, dispatch_one, reconcile
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.zalo import DeliveryError
from sqlalchemy import select

from tests.reporting.conftest import configure, saved


def enqueue(env, row, attachment=None):
    return env.service.enqueue(
        env.actor,
        row["id"],
        models.Enqueue(request_key="enqueue-" + row["id"], attachment_export_id=attachment),
    )


def delivery(env, identity):
    return next(x for x in env.service.list("deliveries")["items"] if x["id"] == identity)


def test_missing_config_and_os_store_do_not_block_local_reports(env):
    row = saved(env)
    unconfigured = enqueue(env, row)
    assert unconfigured["state"] == "UNCONFIGURED"
    assert dispatch_one(env.service)["state"] == "DISABLED"
    assert env.service.detail(row["id"])["state"] == "SAVED"
    no_store = ReportingService(env.runtime, source=env.source)
    assert not no_store.public_settings()["credential_store_available"]
    configure(env)
    with pytest.raises(CoreError, match="SECRET_STORE_UNAVAILABLE"):
        no_store.set_credentials(
            env.actor,
            models.Credentials(app_id="app", app_secret="secret", refresh_token="refresh"),
        )


def test_configured_destination_without_credential_stays_unconfigured_and_catches_up_safely(env):
    configure(env)
    credential = env.secrets.values.copy()
    env.secrets.values.clear()
    item = enqueue(env, saved(env))
    assert item["state"] == "UNCONFIGURED"
    env.secrets.values.update(credential)
    env.service.catch_up(datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert delivery(env, item["id"])["state"] == "WAITING"
    assert env.service.list("deliveries")["total"] == 1


def test_durable_unique_queue_and_receipt_network_outside_writer(env):
    configure(env)
    row = saved(env)
    with ThreadPoolExecutor(max_workers=4) as executor:
        values = list(
            executor.map(
                lambda n: env.service.enqueue(
                    env.actor, row["id"], models.Enqueue(request_key=f"q-{n}")
                ),
                range(4),
            )
        )
    assert len({x["id"] for x in values}) == 1
    old_send = env.transport.send_text

    def send(token, group, text):
        # A writer transaction must be available during slow network operations.
        env.runtime.writer.run(lambda conn: conn.execute(select(OUTBOX.c.id)).first())
        return old_send(token, group, text)

    env.transport.send_text = send
    result = dispatch_one(env.service)
    assert result["state"] == "SENT" and result["message_id"] == "text-receipt"
    assert dispatch_one(env.service)["state"] == "IDLE"
    assert len(env.transport.texts) == 1
    attempts = env.service.attempts(result["id"], 1, 1)
    assert attempts["total"] == 2 and len(attempts["items"]) == 1
    assert env.service.detail(row["id"])["state"] == "SAVED"


def test_timeout_after_send_is_unknown_and_reconciliation_does_not_blind_retry(env):
    configure(env)
    item = enqueue(env, saved(env))
    env.transport.send_error = DeliveryError("ZALO_NETWORK_ERROR", unknown=True)
    result = dispatch_one(env.service)
    assert result["state"] == "UNKNOWN" and not result["message_id"]
    with pytest.raises(CoreError, match="DELIVERY_RETRY_UNSAFE"):
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(request_key="retry", expected_version=result["version"]),
        )
    unresolved = reconcile(
        env.service,
        env.actor,
        item["id"],
        models.Retry(request_key="reconcile", expected_version=result["version"]),
    )
    assert unresolved["state"] == "UNKNOWN"
    assert dispatch_one(env.service)["state"] == "IDLE"
    env.transport.reconciled = "correlated-receipt"
    result = reconcile(
        env.service,
        env.actor,
        item["id"],
        models.Retry(request_key="reconcile-2", expected_version=result["version"]),
    )
    assert result["state"] == "SENT" and result["message_id"] == "correlated-receipt"
    assert len(env.transport.texts) == 1


@pytest.mark.parametrize("receipt", [None, "", "bad receipt with spaces"])
def test_missing_receipt_cannot_be_success(env, receipt):
    configure(env)
    enqueue(env, saved(env))
    env.transport.receipt = receipt
    assert dispatch_one(env.service)["state"] == "UNKNOWN"


def test_wrong_group_config_and_expired_token_refresh_and_redaction(env):
    configure(env)
    enqueue(env, saved(env))
    env.transport.verify_error = DeliveryError("ZALO_GROUP_UNAVAILABLE")
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED" and not env.transport.texts
    assert env.transport.refreshes == 1
    env.transport.verify_error = None
    env.service.retry(
        env.actor,
        result["id"],
        models.Retry(request_key="retry", expected_version=result["version"]),
    )
    assert dispatch_one(env.service)["state"] == "SENT"
    assert env.transport.refreshes == 1  # cached valid token, not one refresh per send
    with env.runtime.reader() as conn:
        persisted = json.dumps([list(x) for x in conn.execute(select(REQUESTS))])
        persisted += json.dumps([list(x) for x in conn.execute(select(AUDIT))])
    for forbidden in ("SYNTHETIC-app-secret", "SYNTHETIC-refresh", "SYNTHETIC-access-rotated"):
        assert forbidden not in persisted
    assert "access_token" not in json.dumps(env.service.public_settings())


def test_refresh_timeout_marks_reauth_and_never_reuses_one_time_token(env):
    configure(env)
    enqueue(env, saved(env))
    env.transport.refresh_error = DeliveryError("ZALO_NETWORK_ERROR", unknown=True)
    result = dispatch_one(env.service)
    # No send was entered: token outcome requires reauthorization, not send success.
    assert result["state"] == "FAILED"
    credential = env.secrets.get(env.service.secret_key(env.service.settings()))
    assert credential["refresh_state"] == "REAUTH_REQUIRED"
    env.transport.refresh_error = None
    check = check_connection(env.service, env.actor)
    assert check["code"] == "ZALO_REAUTH_REQUIRED" and env.transport.refreshes == 1
    assert not env.transport.texts


def test_attachment_selected_summary_only_and_text_receipt_not_resent_on_file_retry(env):
    configure(env, attachments=True)
    row = saved(env)
    file = env.service.export(
        env.actor, row["id"], models.Export(request_key="export", format="txt")
    )
    item = enqueue(env, row, file["id"])
    env.transport.file_error = DeliveryError("ZALO_API_REJECTED")
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED" and result["message_id"] == "text-receipt"
    assert not result["file_message_id"]
    assert env.source.malicious.encode() not in env.transport.uploads[0][0]
    env.transport.file_error = None
    env.service.retry(
        env.actor, item["id"], models.Retry(request_key="retry", expected_version=result["version"])
    )
    result = dispatch_one(env.service)
    assert result["state"] == "SENT" and result["file_message_id"] == "file-receipt"
    assert len(env.transport.texts) == 1
    with pytest.raises(CoreError, match="DELIVERY_PAYLOAD_CONFLICT"):
        env.service.enqueue(env.actor, row["id"], models.Enqueue(request_key="other-attachment"))


def test_other_report_export_cannot_be_attached(env):
    configure(env, attachments=True)
    first = saved(env)
    file = env.service.export(
        env.actor, first["id"], models.Export(request_key="export", format="txt")
    )
    second = saved(env, "second", "Bổ sung")
    with pytest.raises(CoreError, match="ATTACHMENT_INVALID"):
        enqueue(env, second, file["id"])


def test_duplicate_scheduler_catchup_keeps_saved_day_latest_version_no_new_snapshots(env):
    configure(env)
    old = saved(env)
    latest = saved(env, "new", "Bổ sung")
    now = datetime(2026, 11, 1, 10, 59, tzinfo=timezone.utc)
    assert env.service.catch_up(now) == 0
    now = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=4) as executor:
        counts = list(executor.map(lambda _: env.service.catch_up(now), range(4)))
    assert sum(counts) == 1
    values = env.service.list("deliveries")
    assert values["total"] == 1 and values["items"][0]["report_id"] == latest["id"]
    assert env.service.list("reports")["total"] == 2
    assert env.service.detail(old["id"])["from_on"] == "2026-10-31"


def test_single_sender_and_admin_config_cannot_race_network(env):
    configure(env)
    enqueue(env, saved(env))
    entered, release = threading.Event(), threading.Event()
    send = env.transport.send_text

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return send(*args)

    env.transport.send_text = blocked
    with ThreadPoolExecutor(max_workers=2) as executor:
        task = executor.submit(dispatch_one, env.service)
        assert entered.wait(5)
        try:
            assert dispatch_one(env.service)["state"] == "BUSY"
            with pytest.raises(CoreError, match="SENDER_BUSY"):
                configure(env)
        finally:
            release.set()
        assert task.result()["state"] == "SENT"
    assert len(env.transport.texts) == 1


def test_restart_marks_claimed_sending_unknown_and_clears_durable_lock(env):
    configure(env)
    item = enqueue(env, saved(env))
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update().where(OUTBOX.c.id == item["id"]).values(state="SENDING")
        )
    )
    env.runtime.writer.run(
        lambda conn: conn.execute(LOCKS.insert().values(id="sender", owner="old-process"))
    )
    env.runtime.close()
    restarted = Runtime(env.root, modules=env.registry)
    service = ReportingService(
        restarted, source=env.source, secret_store=env.secrets, transport=env.transport
    )
    try:
        service.recover()
        assert service.list("deliveries")["items"][0]["state"] == "UNKNOWN"
        assert dispatch_one(service)["state"] == "IDLE"
        assert not env.transport.texts
    finally:
        restarted.close()


def test_unverified_file_capability_fails_before_text_and_redacts_transport_error(env):
    configure(env, attachments=True)
    report = saved(env)
    file = env.service.export(
        env.actor, report["id"], models.Export(request_key="export", format="txt")
    )
    enqueue(env, report, file["id"])
    env.transport.upload_verified = False
    result = dispatch_one(env.service)
    assert (
        result["state"] == "FAILED" and result["error_code"] == "ZALO_UPLOAD_CAPABILITY_UNVERIFIED"
    )
    assert not env.transport.texts
    env.transport.upload_verified = True
    env.service.retry(
        env.actor,
        result["id"],
        models.Retry(request_key="retry", expected_version=result["version"]),
    )
    env.transport.verify_error = DeliveryError("PRIVATE-CREDENTIAL-must-not-persist")
    result = dispatch_one(env.service)
    assert result["error_code"] == "ZALO_TRANSPORT_ERROR"
    assert "PRIVATE-CREDENTIAL" not in json.dumps(env.service.attempts(result["id"], 1, 25))


def test_recovery_accepts_durable_text_receipt_without_resending(env):
    configure(env)
    item = enqueue(env, saved(env))
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update()
            .where(OUTBOX.c.id == item["id"])
            .values(state="SENDING", phase="complete", message_id="durable-confirmed-message")
        )
    )
    env.service.recover()
    result = delivery(env, item["id"])
    assert result["state"] == "SENT" and result["message_id"] == "durable-confirmed-message"
    assert dispatch_one(env.service)["state"] == "IDLE"
    assert not env.transport.texts
