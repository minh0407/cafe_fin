import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.migrations import LOCKS
from cafe_fin.reporting.sender import check_connection, dispatch_one, reconcile
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram import MAX_DOCUMENT_BYTES, DeliveryError, MessageReceipt
from cafe_fin.reporting.telegram_migrations import ATTEMPTS, OUTBOX
from sqlalchemy import func, select

from tests.reporting.conftest import BOT_ID, BOT_TOKEN, CHAT_ID, configure, saved


def enqueue(env, row, attachment=None):
    return env.service.enqueue(
        env.actor,
        row["id"],
        models.Enqueue(request_key="enqueue-" + row["id"], attachment_export_id=attachment),
    )


def delivery(env, identity):
    return next(x for x in env.service.list("deliveries")["items"] if x["id"] == identity)


def export_summary(env, row, format="xlsx"):
    return env.service.export(
        env.actor, row["id"], models.Export(request_key="export-" + row["id"], format=format)
    )


def assert_no_attempts(env):
    with env.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(ATTEMPTS)).scalar_one() == 0
    assert not env.transport.texts and not env.transport.files and not env.transport.verifications


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
        no_store.set_credentials(env.actor, models.Credentials(bot_token=BOT_TOKEN))
    assert no_store.settings()["bot_verified_at"] is None
    assert_no_attempts(env)


def test_configured_destination_without_credential_stays_unconfigured_and_catches_up_safely(env):
    configure(env)
    credential = env.secrets.values.copy()
    env.secrets.values.clear()
    item = enqueue(env, saved(env))
    assert item["state"] == "UNCONFIGURED"
    assert dispatch_one(env.service)["state"] == "UNCONFIGURED"
    assert_no_attempts(env)
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

    def send(token, chat_id, text, bot_id):
        # A writer transaction must be available during the WAN call.
        env.runtime.writer.run(lambda conn: conn.execute(select(OUTBOX.c.id)).first())
        assert token == BOT_TOKEN and chat_id == CHAT_ID and bot_id == BOT_ID
        return old_send(token, chat_id, text, bot_id)

    env.transport.send_text = send
    result = dispatch_one(env.service)
    assert result["state"] == "SENT" and result["message_id"] == "101"
    assert result["message_chat_id"] == CHAT_ID and result["provider"] == "telegram"
    assert result["bot_id"] == BOT_ID and result["chat_id"] == CHAT_ID
    assert "oa_id" not in result
    with env.runtime.reader() as conn:
        assert conn.execute(select(OUTBOX.c.oa_id)).scalar_one() == ""
    assert dispatch_one(env.service)["state"] == "IDLE"
    assert len(env.transport.texts) == 1
    attempts = env.service.attempts(result["id"], 1, 1)
    assert attempts["total"] == 2 and len(attempts["items"]) == 1
    assert attempts["items"][0]["provider"] == "telegram"
    assert env.service.detail(row["id"])["state"] == "SAVED"


def test_timeout_after_send_is_unknown_and_reconcile_never_reads_secret_or_calls_wan(
    env, monkeypatch
):
    configure(env)
    item = enqueue(env, saved(env))
    env.transport.send_error = DeliveryError("TELEGRAM_NETWORK_ERROR", unknown=True)
    result = dispatch_one(env.service)
    assert result["state"] == "UNKNOWN" and not result["message_id"]
    with pytest.raises(CoreError, match="DELIVERY_RETRY_UNSAFE"):
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(
                request_key="retry",
                expected_version=result["version"],
            ),
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("Manual reconciliation must not read secrets or use WAN")

    monkeypatch.setattr(env.secrets, "get", forbidden)
    monkeypatch.setattr(env.secrets, "has", forbidden)
    for method in ("verify", "send_text", "send_document"):
        monkeypatch.setattr(env.transport, method, forbidden)
    for key in ("reconcile", "reconcile-again"):
        unresolved = reconcile(
            env.service,
            env.actor,
            item["id"],
            models.Retry(
                request_key=key,
                expected_version=result["version"],
            ),
        )
        assert unresolved["state"] == "UNKNOWN" and unresolved["message_id"] is None
    assert len(env.transport.texts) == 1
    assert env.service.attempts(result["id"], 1, 25)["total"] == 2


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        "",
        "bad receipt",
        MessageReceipt(CHAT_ID, 0),
        MessageReceipt(CHAT_ID, True),
        MessageReceipt(CHAT_ID, "101"),
        MessageReceipt("-1009876543210", 101),
    ],
)
def test_missing_or_unpaired_receipt_cannot_be_success(env, receipt):
    configure(env)
    enqueue(env, saved(env))
    env.transport.receipt = receipt
    result = dispatch_one(env.service)
    assert result["state"] == "UNKNOWN" and result["message_id"] is None
    assert result["message_chat_id"] is None


def test_wrong_group_rejection_precedes_send_and_transport_errors_are_redacted(env):
    configure(env)
    enqueue(env, saved(env))
    env.transport.verify_error = DeliveryError("TELEGRAM_CHAT_INVALID")
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED" and result["error_code"] == "TELEGRAM_CHAT_INVALID"
    assert not env.transport.texts
    env.transport.verify_error = None
    env.service.retry(
        env.actor,
        result["id"],
        models.Retry(
            request_key="retry",
            expected_version=result["version"],
        ),
    )
    assert dispatch_one(env.service)["state"] == "SENT"
    with env.runtime.reader() as conn:
        persisted = json.dumps([list(x) for x in conn.execute(select(REQUESTS))])
        persisted += json.dumps([list(x) for x in conn.execute(select(AUDIT))])
        persisted += json.dumps([list(x) for x in conn.execute(select(ATTEMPTS))])
    assert BOT_TOKEN not in persisted
    assert "bot_token" not in json.dumps(env.service.public_settings())


def test_connection_check_only_verifies_and_new_token_needs_new_proof(env):
    configure(env, attachments=True)
    before = env.service.settings()["version"]
    replacement = BOT_ID + ":" + "B" * 35
    env.service.set_credentials(env.actor, models.Credentials(bot_token=replacement))
    config = env.service.settings()
    assert config["version"] == before + 1 and config["bot_verified_at"] is None
    assert env.service.public_settings()["sender_status"] == "UNCONFIGURED"
    assert_no_attempts(env)
    env.transport.verify_error = DeliveryError("TELEGRAM_UNAUTHORIZED")
    assert check_connection(env.service, env.actor)["code"] == "TELEGRAM_UNAUTHORIZED"
    assert env.service.settings()["bot_verified_at"] is None
    env.transport.verify_error = None
    assert check_connection(env.service, env.actor)["state"] == "CONNECTED"
    assert env.service.settings()["version"] == before + 2
    assert env.service.settings()["bot_verified_at"]
    assert env.transport.verifications == [(CHAT_ID, BOT_ID, True)] * 2
    assert not env.transport.texts and not env.transport.files
    with env.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(ATTEMPTS)).scalar_one() == 0


@pytest.mark.parametrize("failure", ["core_error", "unexpected_error", "process_crash"])
def test_failed_token_replacement_clears_proof_durably_before_os_put(env, monkeypatch, failure):
    configure(env)
    item = enqueue(env, saved(env))
    old_version = env.service.settings()["version"]
    old_values = env.secrets.values.copy()

    class ProcessCrash(BaseException):
        pass

    def fail_put(key, value):
        # DB commit and secret replacement cannot be atomic: clear proof first.
        config = env.service.settings()
        assert config["bot_verified_at"] is None and config["version"] == old_version + 1
        env.runtime.writer.run(lambda conn: conn.execute(select(OUTBOX.c.id)).first())
        if failure == "process_crash":
            raise ProcessCrash()
        if failure == "core_error":
            raise CoreError("SECRET_STORE_UNAVAILABLE", "Synthetic OS failure", 503)
        raise OSError("PRIVATE-OS-ERROR-NOT-FOR-UI")

    monkeypatch.setattr(env.secrets, "put", fail_put)
    expected = ProcessCrash if failure == "process_crash" else CoreError
    with pytest.raises(expected) as error:
        env.service.set_credentials(
            env.actor, models.Credentials(bot_token=BOT_ID + ":" + "B" * 35)
        )
    if failure != "process_crash":
        assert error.value.code == "SECRET_STORE_UNAVAILABLE"
        assert "PRIVATE-OS" not in error.value.message
    assert env.secrets.values == old_values
    assert env.service.settings()["bot_verified_at"] is None
    assert env.service.public_settings()["sender_status"] == "UNCONFIGURED"
    assert dispatch_one(env.service)["state"] == "UNCONFIGURED"
    assert_no_attempts(env)
    env.runtime.close()
    restarted = Runtime(env.root, modules=env.registry)
    service = ReportingService(
        restarted, source=env.source, secret_store=env.secrets, transport=env.transport
    )
    try:
        service.recover()
        assert service.settings()["bot_verified_at"] is None
        service.catch_up(datetime(2026, 11, 3, tzinfo=timezone.utc))
        assert dispatch_one(service)["state"] == "UNCONFIGURED"
        assert service.list("deliveries")["items"][0]["id"] == item["id"]
        assert not env.transport.verifications and not env.transport.texts
    finally:
        restarted.close()


def test_failed_proof_database_commit_never_replaces_os_token(env, monkeypatch):
    from cafe_fin.reporting.service import AuditService

    configure(env)
    old_settings, old_secrets = env.service.settings(), env.secrets.values.copy()
    original_record, puts = AuditService.record, []

    def fail_commit(conn, **kwargs):
        if kwargs.get("action") == "configure_bot":
            raise RuntimeError("Synthetic failure inside settings transaction")
        return original_record(conn, **kwargs)

    monkeypatch.setattr(AuditService, "record", fail_commit)
    monkeypatch.setattr(env.secrets, "put", lambda *args: puts.append(args))
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        env.service.set_credentials(
            env.actor, models.Credentials(bot_token=BOT_ID + ":" + "B" * 35)
        )
    assert puts == [] and env.secrets.values == old_secrets
    assert env.service.settings() == old_settings
    assert not env.transport.verifications and not env.transport.texts


@pytest.mark.parametrize(
    "credential", [None, {}, {"bot_token": "malformed"}, {"bot_token": "999999:" + "B" * 35}]
)
def test_malformed_or_wrong_bot_os_token_fails_closed_before_claim(env, credential):
    configure(env)
    item = enqueue(env, saved(env))
    key = env.service.secret_key(env.service.settings())
    if credential is None:
        env.secrets.values.pop(key)
    else:
        env.secrets.values[key] = credential
    assert env.service.public_settings()["sender_status"] == "UNCONFIGURED"
    assert dispatch_one(env.service)["state"] == "UNCONFIGURED"
    assert delivery(env, item["id"])["attempts"] == 0
    assert_no_attempts(env)


def test_attachment_selected_summary_only_and_text_receipt_not_resent_on_file_retry(env):
    configure(env, attachments=True)
    row = saved(env)
    file = export_summary(env, row)
    item = enqueue(env, row, file["id"])
    env.transport.file_error = DeliveryError("TELEGRAM_API_REJECTED")
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED" and result["message_id"] == "101"
    assert result["message_chat_id"] == CHAT_ID and result["file_message_id"] is None
    content, filename = env.transport.files[0]
    assert filename == "CafeFin-summary.xlsx"
    with zipfile.ZipFile(io.BytesIO(content)) as workbook:
        assert all(
            env.source.malicious.encode() not in workbook.read(name) for name in workbook.namelist()
        )
    env.transport.file_error = None
    env.service.retry(
        env.actor, item["id"], models.Retry(request_key="retry", expected_version=result["version"])
    )
    result = dispatch_one(env.service)
    assert result["state"] == "SENT" and result["file_message_id"] == "102"
    assert result["file_message_chat_id"] == CHAT_ID
    assert len(env.transport.texts) == 1 and len(env.transport.files) == 2
    with pytest.raises(CoreError, match="DELIVERY_PAYLOAD_CONFLICT"):
        env.service.enqueue(env.actor, row["id"], models.Enqueue(request_key="other-attachment"))


def test_send_document_timeout_stays_unknown_with_durable_text_receipt(env):
    configure(env, attachments=True)
    row = saved(env)
    item = enqueue(env, row, export_summary(env, row)["id"])
    env.transport.file_error = DeliveryError("TELEGRAM_NETWORK_ERROR", unknown=True)
    result = dispatch_one(env.service)
    assert result["state"] == "UNKNOWN" and result["phase"] == "attachment"
    assert result["message_id"] == "101" and result["message_chat_id"] == CHAT_ID
    assert result["file_message_id"] is None and result["file_message_chat_id"] is None
    with pytest.raises(CoreError, match="DELIVERY_RETRY_UNSAFE"):
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(request_key="retry", expected_version=result["version"]),
        )
    env.service.recover()
    assert delivery(env, item["id"])["state"] == "UNKNOWN"
    assert dispatch_one(env.service)["state"] == "IDLE"
    assert len(env.transport.texts) == len(env.transport.files) == 1


@pytest.mark.parametrize("kind", ["txt", "empty", "limit", "oversized"])
def test_attachment_requires_pdf_xlsx_nonempty_and_at_most_five_mib(env, monkeypatch, kind):
    from cafe_fin.reporting import exports

    configure(env, attachments=True)
    row = saved(env)
    if kind != "txt":
        render = exports.render

        def sized_render(*args):
            content, media_type = render(*args)
            if kind == "empty":
                return b"", media_type
            size = MAX_DOCUMENT_BYTES + (kind == "oversized")
            # ZIP permits trailing bytes: use a real XLSX with synthetic padding.
            return content + b" " * (size - len(content)), media_type

        monkeypatch.setattr(exports, "render", sized_render)
    file = export_summary(env, row, "txt" if kind == "txt" else "xlsx")
    if kind == "limit":
        assert file["size"] == MAX_DOCUMENT_BYTES
        enqueue(env, row, file["id"])
        assert dispatch_one(env.service)["state"] == "SENT"
        assert len(env.transport.files[0][0]) == MAX_DOCUMENT_BYTES
    else:
        with pytest.raises(CoreError, match="ATTACHMENT_INVALID"):
            enqueue(env, row, file["id"])
        assert_no_attempts(env)


def test_other_report_export_cannot_be_attached(env):
    configure(env, attachments=True)
    first = saved(env)
    file = export_summary(env, first)
    with pytest.raises(CoreError, match="ATTACHMENT_INVALID"):
        enqueue(env, saved(env, "second", "Bổ sung"), file["id"])


def test_document_rights_preflight_and_unknown_error_code_redaction(env):
    configure(env, attachments=True)
    row = saved(env)
    enqueue(env, row, export_summary(env, row)["id"])
    env.transport.verify_error = DeliveryError("TELEGRAM_SEND_DENIED")
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED" and result["error_code"] == "TELEGRAM_SEND_DENIED"
    assert env.transport.verifications == [(CHAT_ID, BOT_ID, True)]
    assert not env.transport.texts and not env.transport.files
    env.service.retry(
        env.actor,
        result["id"],
        models.Retry(request_key="retry", expected_version=result["version"]),
    )
    env.transport.verify_error = DeliveryError("PRIVATE-CREDENTIAL-must-not-persist")
    result = dispatch_one(env.service)
    assert result["error_code"] == "TELEGRAM_TRANSPORT_ERROR"
    assert "PRIVATE-CREDENTIAL" not in json.dumps(env.service.attempts(result["id"], 1, 25))


@pytest.mark.parametrize("delay", [1, 3600, 3601])
def test_rate_limit_requires_bounded_manual_retry_after_due_time(env, delay):
    configure(env)
    now = datetime(2026, 11, 3, 2, 0, tzinfo=timezone.utc)
    env.service.clock = lambda: now
    item = enqueue(env, saved(env))
    env.transport.send_error = DeliveryError("TELEGRAM_RATE_LIMITED", retry_after=delay)
    result = dispatch_one(env.service)
    assert result["state"] == "FAILED"
    assert env.service.catch_up(now + timedelta(days=1)) == 0
    if delay > 3600:
        assert result["error_code"] == "TELEGRAM_RETRY_REVIEW_REQUIRED"
        assert result["retry_not_before"] is None
        code = "DELIVERY_RETRY_REVIEW_REQUIRED"
    else:
        assert result["error_code"] == "TELEGRAM_RATE_LIMITED"
        assert datetime.fromisoformat(result["retry_not_before"]) == now + timedelta(seconds=delay)
        code = "DELIVERY_RETRY_LATER"
    with pytest.raises(CoreError, match=code):
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(request_key="early", expected_version=result["version"]),
        )
    assert len(env.transport.texts) == 1
    if delay <= 3600:
        now += timedelta(seconds=delay)
        env.transport.send_error = None
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(request_key="due", expected_version=result["version"]),
        )
        assert dispatch_one(env.service)["state"] == "SENT"
        assert len(env.transport.texts) == 2


def test_duplicate_scheduler_catchup_keeps_saved_day_latest_version_no_new_snapshots(env):
    configure(env)
    old = saved(env)
    latest = saved(env, "new", "Bổ sung")
    assert env.service.catch_up(datetime(2026, 11, 1, 10, 59, tzinfo=timezone.utc)) == 0
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


@pytest.mark.parametrize("receipt_chat", [CHAT_ID, None, "-1009876543210"])
def test_recovery_requires_durable_receipt_paired_with_correct_chat(env, receipt_chat):
    configure(env)
    item = enqueue(env, saved(env))
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update()
            .where(OUTBOX.c.id == item["id"])
            .values(
                state="SENDING",
                phase="complete",
                message_id="101",
                message_chat_id=receipt_chat,
            )
        )
    )
    env.service.recover()
    result = delivery(env, item["id"])
    assert result["state"] == ("SENT" if receipt_chat == CHAT_ID else "UNKNOWN")
    assert result["message_id"] == "101"
    assert dispatch_one(env.service)["state"] == "IDLE"
    assert not env.transport.texts


def test_different_bot_cannot_reuse_old_proof_or_repurpose_immutable_delivery(env):
    configure(env)
    item = enqueue(env, saved(env))
    original_key = env.service.secret_key(env.service.settings())
    new_bot = "654321"
    new_token = new_bot + ":" + "C" * 35
    env.service.set_credentials(env.actor, models.Credentials(bot_token=new_token))
    config = env.service.settings()
    assert config["bot_id"] == new_bot and config["bot_verified_at"] is None
    assert env.secrets.values[original_key] == {"bot_token": BOT_TOKEN}
    assert env.secrets.values[env.service.secret_key(config)] == {"bot_token": new_token}
    assert dispatch_one(env.service)["state"] == "UNCONFIGURED"
    assert_no_attempts(env)
    env.transport.allowed_bot_id = new_bot
    assert check_connection(env.service, env.actor)["state"] == "CONNECTED"
    pinned = delivery(env, item["id"])
    assert pinned["state"] == "WAITING" and pinned["attempts"] == 0
    assert dispatch_one(env.service)["state"] == "IDLE"
    with pytest.raises(CoreError, match="DELIVERY_RETRY_UNSAFE"):
        env.service.retry(
            env.actor,
            item["id"],
            models.Retry(
                request_key="different-bot-retry",
                expected_version=pinned["version"],
            ),
        )
    with pytest.raises(CoreError, match="DELIVERY_IDENTITY_CONFLICT"):
        env.service.enqueue(
            env.actor, item["report_id"], models.Enqueue(request_key="different-bot")
        )
    assert delivery(env, item["id"])["bot_id"] == BOT_ID
    assert not env.transport.texts and not env.transport.files


def test_chat_change_invalidates_connection_proof_before_any_scheduled_wan(env):
    configure(env)
    enqueue(env, saved(env))
    config = env.service.settings()
    env.service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="different-chat",
            expected_version=config["version"],
            enabled=True,
            chat_id="-1009876543210",
            send_at="18:00",
        ),
    )
    assert env.service.settings()["bot_verified_at"] is None
    assert env.service.public_settings()["sender_status"] == "UNCONFIGURED"
    assert dispatch_one(env.service)["state"] == "UNCONFIGURED"
    assert_no_attempts(env)
