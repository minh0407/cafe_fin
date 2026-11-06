import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.storage import FILES
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.migrations import OUTBOX
from cafe_fin.reporting.zalo import DeliveryError
from conftest import configure, saved
from sqlalchemy import select


def second_user(env, role="operator"):
    env.runtime.auth.create_user(
        env.actor,
        username="reviewuser",
        password="synthetic-review-password",
        role=role,
        request_key="review-user",
    )
    login = env.runtime.auth.login("reviewuser", "synthetic-review-password")
    return env.runtime.auth.authenticate(login["access_token"])


def test_file_receipt_failure_cross_actor_retry_reuses_same_file_and_reauthorizes(env, monkeypatch):
    report = saved(env)
    command = env.service.command

    def fail_final(actor, action, *args, **kwargs):
        if action == "export":
            raise CoreError("SYNTHETIC_FINAL_FAILURE", "Synthetic failure", 503)
        return command(actor, action, *args, **kwargs)

    monkeypatch.setattr(env.service, "command", fail_final)
    with pytest.raises(CoreError, match="SYNTHETIC_FINAL_FAILURE"):
        env.service.export(
            env.actor, report["id"], models.Export(request_key="first", format="txt")
        )
    monkeypatch.setattr(env.service, "command", command)
    with env.runtime.reader() as conn:
        before = list(conn.execute(select(FILES)).mappings())
    actor = second_user(env)
    result = env.service.export(
        actor, report["id"], models.Export(request_key="other-user", format="txt")
    )
    with env.runtime.reader() as conn:
        assert len(list(conn.execute(select(FILES)))) == 1
    assert result["file_id"] == before[0].id
    env.runtime.auth.update_user(
        env.actor,
        actor.id,
        role="operator",
        active=False,
        expected_version=actor.version,
        request_key="revoke-exporter",
    )
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.service.export(actor, report["id"], models.Export(request_key="revoked", format="txt"))


@pytest.mark.parametrize("after_commit", [False, True])
def test_terminal_text_receipt_fault_cannot_become_unknown_or_resend(
    env, monkeypatch, after_commit
):
    configure(env)
    report = saved(env)
    env.service.enqueue(env.actor, report["id"], models.Enqueue(request_key="queue"))
    finish = sender.finish
    failed = False

    def fail_once(service, identity, state, phase, **kwargs):
        nonlocal failed
        if state == "SENT" and not failed:
            failed = True
            if after_commit:
                finish(service, identity, state, phase, **kwargs)
            raise OSError("Synthetic final-write failure")
        return finish(service, identity, state, phase, **kwargs)

    monkeypatch.setattr(sender, "finish", fail_once)
    result = sender.dispatch_one(env.service)
    assert result["state"] == "SENT" and result["message_id"] == "text-receipt"
    env.service.recover()
    assert env.service.list("deliveries")["items"][0]["state"] == "SENT"
    assert sender.dispatch_one(env.service)["state"] == "IDLE"
    assert len(env.transport.texts) == 1


def test_positive_reconcile_revocation_during_network_is_rejected_in_final_transaction(env):
    configure(env)
    report = saved(env)
    item = env.service.enqueue(env.actor, report["id"], models.Enqueue(request_key="queue"))
    env.transport.send_error = DeliveryError("ZALO_NETWORK_ERROR", unknown=True)
    unknown = sender.dispatch_one(env.service)
    admin = second_user(env, "admin")

    def revoke(*args):
        env.runtime.auth.update_user(
            admin,
            env.actor.id,
            role="operator",
            active=False,
            expected_version=env.actor.version,
            request_key="revoke-reconciler",
        )
        return "positive-correlated-receipt"

    env.transport.reconcile = revoke
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        sender.reconcile(
            env.service,
            env.actor,
            item["id"],
            models.Retry(request_key="reconcile", expected_version=unknown["version"]),
        )
    with env.runtime.reader() as conn:
        row = conn.execute(select(OUTBOX).where(OUTBOX.c.id == item["id"])).mappings().one()
    assert row.state == "UNKNOWN" and row.message_id is None
