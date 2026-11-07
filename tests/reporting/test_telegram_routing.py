"""An incompatible historical route cannot poison healthy Telegram work."""

from datetime import datetime, timedelta, timezone

import pytest
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.telegram import DeliveryError
from cafe_fin.reporting.telegram_migrations import ATTEMPTS, OUTBOX
from sqlalchemy import select

from tests.reporting.conftest import BOT_TOKEN, CHAT_ID, configure


def saved_day(env, day, key, *, reason=""):
    preview = env.service.preview(
        env.actor,
        models.Preview(request_key=key, from_on=day, through_on=day, book_ids=[], reason=reason),
    )
    return env.service.save(
        env.actor,
        preview["id"],
        models.Save(request_key="save-" + key, expected_version=preview["version"]),
    )


def row(env, identity):
    with env.runtime.reader() as conn:
        return dict(conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one())


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("initial", ["no_bot", "another_bot"])
def test_identity_backlog_never_aborts_tick_or_blocks_healthy_current_bot(env, automatic, initial):
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    env.service.clock = lambda: now
    if initial == "another_bot":
        configure(env)
    else:
        env.service.update_settings(
            env.actor,
            models.DeliverySettings(
                request_key="chat-first",
                expected_version=0,
                chat_id=CHAT_ID,
                enabled=True,
                send_at="18:00",
            ),
        )
    old = saved_day(env, "2026-11-07", "old")
    pending = env.service.enqueue(env.actor, old["id"], models.Enqueue(request_key="old-queue"))
    original = row(env, pending["id"])
    if initial == "another_bot":
        env.transport.allowed_bot_id = "654321"
        token = "654321:" + "B" * 35
        env.service.set_credentials(env.actor, models.Credentials(bot_token=token))
        assert sender.check_connection(env.service, env.actor)["state"] == "CONNECTED"
    else:
        env.service.set_credentials(env.actor, models.Credentials(bot_token=BOT_TOKEN))
        assert sender.check_connection(env.service, env.actor)["state"] == "CONNECTED"
    current = env.service.settings()
    env.service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="current-auto",
            expected_version=current["version"],
            chat_id=CHAT_ID,
            enabled=True,
            send_at="18:00",
            auto_generate_daily=automatic,
            daily_export_formats=["txt"],
        ),
    )
    healthy = saved_day(env, "2026-11-06", "healthy")
    queued = env.service.enqueue(
        env.actor, healthy["id"], models.Enqueue(request_key="healthy-queue")
    )
    assert queued["state"] == "WAITING"
    env.transport.verifications.clear()
    for _ in range(2):
        env.service.tick(now)
    assert row(env, queued["id"])["state"] == "SENT"
    assert len(env.transport.texts) == (2 if initial == "no_bot" else 1)
    assert row(env, pending["id"]) == original

    assert original["attempts"] == 0
    assert env.service.list("reports")["total"] == 2
    if initial == "no_bot":
        with env.runtime.reader() as conn:
            bound = (
                conn.execute(
                    select(OUTBOX).where(
                        OUTBOX.c.report_id == old["id"],
                        OUTBOX.c.bot_id == env.service.settings(conn)["bot_id"],
                    )
                )
                .mappings()
                .one()
            )
            assert bound.state == "SENT" and bound.destination == CHAT_ID
        assert env.service.detail(old["id"])["version"] == 1
        return  # Normal setup never requires a report adjustment.
    # A known old bot requires an explicit adjustment for a different bot.
    revised = saved_day(
        env, "2026-11-07", "explicit-revision", reason="Explicit bot route adjustment."
    )
    explicit = env.service.enqueue(
        env.actor, revised["id"], models.Enqueue(request_key="explicit-send")
    )
    assert explicit["state"] == "WAITING"
    assert sender.dispatch_one(env.service)["state"] == "SENT"
    assert len(env.transport.texts) == 2
    assert row(env, pending["id"]) == original


@pytest.mark.parametrize("review", [False, True])
def test_rate_limit_holds_entire_bot_without_wan_or_attempt_on_other_reports(env, review):
    configure(env)
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    clock = {"now": now}
    env.service.clock = lambda: clock["now"]
    first = saved_day(env, "2026-11-05", "rate-first")
    second = saved_day(env, "2026-11-06", "rate-second")
    a = env.service.enqueue(env.actor, first["id"], models.Enqueue(request_key="rate-a"))
    b = env.service.enqueue(env.actor, second["id"], models.Enqueue(request_key="rate-b"))
    env.transport.send_error = DeliveryError(
        "TELEGRAM_RETRY_REVIEW_REQUIRED" if review else "TELEGRAM_RATE_LIMITED",
        retry_after=None if review else 120,
    )
    assert sender.dispatch_one(env.service)["state"] == "FAILED"
    env.transport.send_error = None
    verifications = list(env.transport.verifications)
    with env.runtime.reader() as conn:
        attempts = list(conn.execute(select(ATTEMPTS)).mappings())
    for _ in range(2):
        assert sender.dispatch_one(env.service)["state"] == ("BLOCKED" if review else "COOLDOWN")
    assert env.transport.verifications == verifications and len(env.transport.texts) == 1
    assert row(env, b["id"])["attempts"] == 0
    with env.runtime.reader() as conn:
        assert list(conn.execute(select(ATTEMPTS)).mappings()) == attempts
    clock["now"] = now + timedelta(seconds=120)
    if review:
        third = saved_day(env, "2026-11-07", "rate-third")
        c = env.service.enqueue(env.actor, third["id"], models.Enqueue(request_key="rate-c"))
        assert sender.dispatch_one(env.service)["state"] == "BLOCKED"
        assert row(env, c["id"])["attempts"] == 0
    else:
        assert sender.dispatch_one(env.service)["state"] == "SENT"
        assert row(env, b["id"])["state"] == "SENT"
    assert row(env, a["id"])["state"] == "FAILED"


@pytest.mark.parametrize("after_commit", [False, True])
def test_text_proof_survives_transient_prefix_write_failure_and_document_only_retry(
    env, monkeypatch, after_commit
):
    configure(env, attachments=True)
    report = saved_day(env, "2026-11-07", "text-proof")
    item = env.service.export(
        env.actor, report["id"], models.Export(request_key="text-proof-pdf", format="pdf")
    )
    queued = env.service.enqueue(
        env.actor,
        report["id"],
        models.Enqueue(request_key="text-proof-queue", attachment_export_id=item["id"]),
    )
    finish, failed = sender.finish, False

    def fail_prefix(*args, **kwargs):
        nonlocal failed
        if args[2] == "SENDING" and kwargs.get("message_id") is not None and not failed:
            failed = True
            if after_commit:
                finish(*args, **kwargs)
            raise OSError("synthetic transient prefix write/ACK failure")
        return finish(*args, **kwargs)

    monkeypatch.setattr(sender, "finish", fail_prefix)
    result = sender.dispatch_one(env.service)
    assert result["state"] == "FAILED" and result["phase"] == "preflight_document"
    assert result["message_id"] == "101" and result["message_chat_id"] == CHAT_ID
    assert len(env.transport.texts) == 1 and not env.transport.files
    env.service.retry(
        env.actor,
        queued["id"],
        models.Retry(request_key="document-only-retry", expected_version=result["version"]),
    )
    assert sender.dispatch_one(env.service)["state"] == "SENT"
    assert len(env.transport.texts) == 1 and len(env.transport.files) == 1
