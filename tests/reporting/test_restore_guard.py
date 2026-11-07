"""Actual dormant/candidate activation with reporting's default owner hook."""

import copy
import hashlib
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.core.activation import activation_context
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_operations import MaintenanceOperations
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import exports, local_exports, models, sender
from cafe_fin.reporting.local_export_migrations import LOCAL_EXPORTS
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.restore import GUARD_ACTION, GUARD_ACTOR, REVIEW_CODE
from cafe_fin.reporting.schedule import insert_run, manual_report
from cafe_fin.reporting.schedule_migrations import DAILY_RUNS
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram_migrations import ATTEMPTS, OUTBOX
from sqlalchemy import func, select

from tests.reporting.conftest import (
    BOT_TOKEN,
    CHAT_ID,
    FakeTransport,
    MemorySecrets,
    TypedSyntheticSource,
)

PASSWORD = "synthetic-restore-password"


class CheckedSecrets(MemorySecrets):
    locked = False
    reads = writes = 0

    def has(self, key):
        self.reads += 1
        assert not self.locked, "Restore hold must not consult old OS credentials"
        return super().has(key)

    def get(self, key):
        self.reads += 1
        assert not self.locked, "Restore hold must not read credential values"
        return super().get(key)

    def put(self, key, value):
        self.writes += 1
        assert not self.locked, "Guard must not copy/delete/replace credentials"
        return super().put(key, value)


class CheckedTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.calls = []

    def verify(self, *args, **kwargs):
        self.calls.append("verify")
        return super().verify(*args, **kwargs)

    def send_text(self, *args):
        self.calls.append("text")
        return super().send_text(*args)

    def send_document(self, *args):
        self.calls.append("document")
        return super().send_document(*args)


@pytest.fixture
def lab(tmp_path):
    runtimes = []
    secrets, transport, source = CheckedSecrets(), CheckedTransport(), TypedSyntheticSource()
    manifest = module_manifest(source=source, secret_store=secrets, transport=transport)
    registry = ModuleRegistry((manifest,))

    def make(path, initialize=False, username="otheradmin"):
        rt = Runtime(path, initialize=initialize, modules=registry)
        runtimes.append(rt)
        if initialize:
            login = rt.auth.setup("restoreadmin", PASSWORD)
            actor = rt.auth.authenticate(login["access_token"])
            rt.auth.create_user(
                actor, username="otheradmin", password=PASSWORD, role="admin", request_key="other"
            )
        else:
            login = rt.auth.login(username, PASSWORD)
            actor = rt.auth.authenticate(login["access_token"])
        return SimpleNamespace(
            runtime=rt,
            actor=actor,
            token=login["access_token"],
            service=ReportingService(rt, source=source, secret_store=secrets, transport=transport),
        )

    source_env = make(tmp_path / "source", True)
    config(source_env.service, source_env.actor, enabled=True, auto=False)
    source_env.service.set_credentials(
        source_env.actor,
        models.Credentials(bot_token=BOT_TOKEN),
    )

    assert sender.check_connection(source_env.service, source_env.actor)["state"] == "CONNECTED"
    transport.calls.clear()
    transport.verifications.clear()

    def prepare(kind="restore", backup=None, origin=None):
        origin = origin or source_env
        generation, operation_id = str(uuid4()), str(uuid4())
        if kind == "restore" and backup is None:
            backup = tmp_path / ("backup-" + operation_id)
            origin.runtime.backups.create(backup)
        origin.runtime.quiesce(operation_id, access_token=origin.token)
        parent = tmp_path / ("selected-" + operation_id)
        parent.mkdir()
        target = parent / ("CafeFinData-" + operation_id)
        result = MaintenanceOperations(origin.runtime, generation=generation).prepare(
            operation_id,
            kind,
            access_token=origin.token,
            origin_generation=generation,
            destination=target,
            backup_source=backup,
        )
        assert result["state"] == "PREPARED"
        candidate = make(target)
        candidate.generation, candidate.operation_id = generation, operation_id
        return candidate

    yield SimpleNamespace(
        make=make,
        prepare=prepare,
        source=source_env,
        secrets=secrets,
        transport=transport,
        dto_source=source,
        manifest=manifest,
        registry=registry,
        runtimes=runtimes,
    )
    secrets.locked = False
    for rt in reversed(runtimes):
        rt.close()


def config(service, actor, *, enabled, auto=False, group=CHAT_ID, key=None):
    old = service.settings()
    return service.update_settings(
        actor,
        models.DeliverySettings(
            request_key=key or "config-" + str(uuid4()),
            expected_version=old["version"],
            enabled=enabled,
            auto_generate_daily=auto,
            chat_id=group,
            send_at="18:00",
            attachments_enabled=True,
            daily_export_formats=["txt"],
        ),
    )


def report(env, day):
    preview = env.service.preview(
        env.actor,
        models.Preview(request_key="preview-" + day, from_on=day, through_on=day, book_ids=[]),
    )
    row = env.service.save(
        env.actor, preview["id"], models.Save(request_key="save-" + day, expected_version=1)
    )
    item = env.service.export(
        env.actor, row["id"], models.Export(request_key="export-" + day, format="txt")
    )
    return row, item


def queue(env, day, *, state="WAITING", text=None, file=None, attachment=False):
    row, item = report(env, day)
    if attachment:
        item = env.service.export(
            env.actor, row["id"], models.Export(request_key="attachment-" + day, format="pdf")
        )
    result = env.service.enqueue(
        env.actor,
        row["id"],
        models.Enqueue(
            request_key="enqueue-" + day, attachment_export_id=item["id"] if attachment else None
        ),
    )
    env.runtime.writer.run(
        lambda conn: conn.execute(
            OUTBOX.update()
            .where(OUTBOX.c.id == result["id"])
            .values(
                state=state,
                message_id=text,
                file_message_id=file,
                message_chat_id=CHAT_ID if text else None,
                file_message_chat_id=CHAT_ID if file else None,
                phase="attachment" if attachment else "text",
            )
        )
    )
    return row, item, result


def delivery(rt, identity):
    with rt.reader() as conn:
        return dict(conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one())


def activate(candidate):
    submitted, submit = [], candidate.runtime.jobs.submit

    def observe_submit(*args, **kwargs):
        result = submit(*args, **kwargs)
        if len(args) > 3 and args[1] == "reporting.dispatch" and args[3].startswith("startup-"):
            submitted.append(result["job_id"])
        return result

    candidate.runtime.jobs.submit = observe_submit
    try:
        result = MaintenanceOperations(candidate.runtime, generation=str(uuid4())).activate(
            candidate.operation_id,
            access_token=candidate.token,
            origin_generation=candidate.generation,
        )
        # Finish the real finite startup job before the test enables a separate
        # fixed-clock schedule. Otherwise real-time startup races that schedule.
        until = time.monotonic() + 5
        while submitted and any(
            candidate.runtime.jobs.status(job)["state"] in {"WAITING", "RUNNING"}
            for job in submitted
        ):
            assert time.monotonic() < until
            time.sleep(0.01)
        return result
    finally:
        candidate.runtime.jobs.submit = submit


def test_default_hook_quarantines_before_recovery_preserves_proofs_bytes_and_requires_explicit_choice(
    lab, monkeypatch
):
    seeded = []
    for index, (state, text, file, attachment) in enumerate(
        [
            ("WAITING", None, None, False),
            ("FAILED", None, None, False),
            ("UNCONFIGURED", None, None, False),
            ("SENDING", None, None, False),
            ("SENDING", "201", None, False),
            ("SENDING", "202", None, True),
            ("UNKNOWN", None, None, False),
            ("SENT", "205", None, False),
            ("SENDING", "203", "204", True),
            ("SENDING", "", None, False),
        ],
        1,
    ):
        row, item, queued = queue(
            lab.source,
            f"2026-10-{index:02d}",
            state=state,
            text=text,
            file=file,
            attachment=attachment,
        )
        with lab.source.runtime.files.read(item["file_id"]) as stream:
            content = stream.read()
        seeded.append((row, item, queued, state, text, file, content))
    pending_runs = []
    for index, state in enumerate(("PENDING", "RUNNING", "FAILED", "BLOCKED"), 1):
        run = lab.source.runtime.writer.run(
            lambda conn: dict(
                insert_run(conn, f"2026-10-{index:02d}", lab.source.service.settings(conn))
            )
        )
        lab.source.runtime.writer.run(
            lambda conn: conn.execute(
                DAILY_RUNS.update().where(DAILY_RUNS.c.id == run["id"]).values(state=state)
            )
        )
        pending_runs.append(run)
    secret_values = copy.deepcopy(lab.secrets.values)
    candidate = lab.prepare()
    old_key = lab.source.service.secret_key(lab.source.service.settings())
    assert candidate.service.secret_key(candidate.service.settings()) == old_key
    lab.secrets.reads = lab.secrets.writes = 0
    lab.secrets.locked = True
    candidate.runtime.start()
    assert candidate.runtime.maintenance.status()["state"] == "DORMANT"
    assert (
        not candidate.runtime.runner.thread.is_alive()
        and not candidate.runtime.periodic.thread.is_alive()
    )
    assert sender.dispatch_one(candidate.service)["state"] == "BLOCKED"
    recovered = []
    original_recover = candidate.runtime.jobs.recover_interrupted

    def observe_recovery():
        assert candidate.service.settings()["restore_review"]["required"]
        assert delivery(candidate.runtime, seeded[0][2]["id"])["state"] == "UNKNOWN"
        assert (
            candidate.runtime.runner.thread.ident is None
            and candidate.runtime.periodic.thread.ident is None
        )
        recovered.append(True)
        return original_recover()

    monkeypatch.setattr(candidate.runtime.jobs, "recover_interrupted", observe_recovery)
    assert activate(candidate)["state"] == "ACTIVE"
    assert recovered and all(recovered)
    public = candidate.service.public_settings()
    assert public["restore_review_required"] and public["sender_status"] == "RESTORE_SUSPENDED"
    assert public["credential_configured"] is None
    assert not public["enabled"] and not public["auto_generate_daily"]
    assert candidate.service.tick()["delivery"]["state"] == "SUSPENDED"
    with candidate.runtime.reader() as conn:
        for old_run in pending_runs:
            run = (
                conn.execute(select(DAILY_RUNS).where(DAILY_RUNS.c.id == old_run["id"]))
                .mappings()
                .one()
            )
            assert run.state == "NEEDS_MANUAL" and run.error_code == REVIEW_CODE
            assert run.pins_json == old_run["pins_json"] and run.attempts == 0
    assert public["restore_review"]["daily_runs_held"] == 4
    for row, item, queued, old_state, text, file, content in seeded:
        current = delivery(candidate.runtime, queued["id"])
        complete = bool(text) and (not current["attachment_export_id"] or bool(file))
        assert current["state"] == ("SENT" if old_state == "SENT" or complete else "UNKNOWN")
        assert current["message_id"] == text and current["file_message_id"] == file
        assert current["version"] == queued["version"] + (0 if old_state == "SENT" else 1)
        assert current["attempts"] == 0
        assert candidate.service.detail(row["id"])["snapshot"] == row["snapshot"]
        with candidate.runtime.files.read(item["file_id"]) as stream:
            assert stream.read() == content
    old_row, _, queued, *_ = seeded[0]
    for action in (
        lambda: candidate.service.enqueue(
            candidate.actor, old_row["id"], models.Enqueue(request_key="enqueue-2026-10-01")
        ),
        lambda: candidate.service.retry(
            candidate.actor, queued["id"], models.Retry(request_key="retry", expected_version=2)
        ),
        lambda: sender.reconcile(
            candidate.service,
            candidate.actor,
            queued["id"],
            models.Retry(request_key="reconcile", expected_version=2),
        ),
        lambda: sender.check_connection(candidate.service, candidate.actor),
    ):
        with pytest.raises(CoreError, match=REVIEW_CODE):
            action()
    config(candidate.service, candidate.actor, enabled=False)
    assert candidate.service.settings()["restore_review"]["required"]
    assert lab.transport.calls == [] and lab.secrets.reads == lab.secrets.writes == 0
    assert lab.secrets.values == secret_values
    with candidate.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(ATTEMPTS)).scalar_one() == 0
        audit = (
            conn.execute(select(AUDIT).where(AUDIT.c.entity == "reporting_activation"))
            .mappings()
            .one()
        )
        assert audit.actor == candidate.actor.id and audit.action == "restore_quarantine"
    lab.secrets.locked = False
    config(candidate.service, candidate.actor, enabled=True)
    assert not candidate.service.settings()["restore_review"]["required"]
    # Same actor/key as the source request really replays its pre-restore receipt.
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    original_actor = candidate.runtime.auth.authenticate(login["access_token"])
    assert (
        candidate.service.enqueue(
            original_actor, old_row["id"], models.Enqueue(request_key="enqueue-2026-10-01")
        )["state"]
        == "UNKNOWN"
    )
    candidate.service.catch_up()
    assert sender.dispatch_one(candidate.service)["state"] == "IDLE" and lab.transport.calls == []
    with candidate.runtime.reader() as conn:
        assert manual_report(conn, old_row["from_on"], candidate.service.settings(conn)) == (
            None,
            "RESTORE_REQUIRES_MANUAL",
        )
    fresh, fresh_item = report(candidate, "2026-10-22")
    candidate.service.enqueue(candidate.actor, fresh["id"], models.Enqueue(request_key="future"))
    assert sender.dispatch_one(candidate.service)["state"] == "SENT"
    assert lab.transport.calls.count("text") == 1
    assert delivery(candidate.runtime, queued["id"])["state"] == "UNKNOWN"
    assert (
        hashlib.sha256(
            candidate.runtime.root.resolve_key(
                fresh_item["local_export"]["relative_key"]
            ).read_bytes()
        ).hexdigest()
        == fresh_item["sha256"]
    )


def test_guard_replay_lost_ack_cross_admin_fresh_authority_and_post_review_restart(
    lab, monkeypatch
):
    old, _, queued = queue(lab.source, "2026-10-01")
    candidate = lab.prepare()
    assert activate(candidate)["state"] == "ACTIVE"
    context = activation_context(candidate.runtime.root)
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    other = candidate.runtime.auth.authenticate(login["access_token"])
    before = candidate.service.settings()["version"]
    execute = candidate.runtime.writer.execute

    def lost_ack(*args, **kwargs):
        result = execute(*args, **kwargs)
        if args[1] == GUARD_ACTION:
            raise OSError("synthetic lost ACK")
        return result

    monkeypatch.setattr(candidate.runtime.writer, "execute", lost_ack)
    with pytest.raises(OSError):
        candidate.service.restore_quarantine(candidate.actor, context)
    monkeypatch.setattr(candidate.runtime.writer, "execute", execute)
    assert candidate.service.restore_quarantine(other, context)["quarantined"] == 1
    assert candidate.service.settings()["version"] == before
    config(candidate.service, other, enabled=True)
    chosen_version = candidate.service.settings()["version"]
    candidate.service.restore_quarantine(candidate.actor, context)
    assert (
        candidate.service.settings()["enabled"]
        and candidate.service.settings()["version"] == chosen_version
    )
    candidate.runtime.auth.update_user(
        other,
        candidate.actor.id,
        role="operator",
        active=False,
        expected_version=candidate.actor.version,
        request_key="revoke-activation-admin",
    )
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        candidate.service.restore_quarantine(candidate.actor, context)
    with pytest.raises(CoreError):
        candidate.service.restore_quarantine(other, replace(context, kind="move"))
    with candidate.runtime.reader() as conn:
        assert (
            conn.execute(
                select(func.count())
                .select_from(REQUESTS)
                .where(REQUESTS.c.actor == GUARD_ACTOR, REQUESTS.c.action == GUARD_ACTION)
            ).scalar_one()
            == 1
        )
    path = candidate.runtime.root.path
    candidate.runtime.close()
    reopened = lab.make(path, username="restoreadmin")
    reopened.runtime.start()
    assert (
        reopened.service.settings()["enabled"]
        and reopened.service.settings()["version"] == chosen_version
    )
    assert (
        delivery(reopened.runtime, queued["id"])["state"] == "UNKNOWN" and lab.transport.calls == []
    )
    assert reopened.service.detail(old["id"])["sha256"] == old["sha256"]


def test_new_restore_activation_id_requires_review_again_and_move_keeps_schedule(lab):
    row, _, queued = queue(lab.source, "2026-10-01", state="SENT", text="206")
    moved = lab.prepare("move")
    version = moved.service.settings()["version"]
    assert activate(moved)["state"] == "ACTIVE"
    assert moved.service.settings()["enabled"] and moved.service.settings()["version"] == version
    assert moved.service.settings()["restore_review"] is None
    restored = lab.prepare(origin=moved)
    assert activate(restored)["state"] == "ACTIVE"
    assert restored.service.settings()["restore_review"]["required"]
    config(restored.service, restored.actor, enabled=True)
    next_restore = lab.prepare(origin=restored)
    assert activate(next_restore)["state"] == "ACTIVE"
    assert next_restore.operation_id != restored.operation_id
    assert next_restore.service.settings()["restore_review"]["required"]
    assert not next_restore.service.settings()["enabled"]
    assert delivery(next_restore.runtime, queued["id"])["state"] == "SENT"
    assert (
        next_restore.service.detail(row["id"])["sha256"] == row["sha256"]
        and lab.transport.calls == []
    )


def test_old_unknown_stays_held_after_credential_and_destination_change(lab):
    row, _, queued = queue(lab.source, "2026-10-01")
    candidate = lab.prepare()
    activate(candidate)
    candidate.service.set_credentials(
        candidate.actor,
        models.Credentials(bot_token="123456:" + "B" * 35),
    )
    assert candidate.service.settings()["restore_review"]["required"]
    config(candidate.service, candidate.actor, enabled=True, group="-1009999999")
    assert candidate.service.catch_up() == 0
    assert sender.dispatch_one(candidate.service)["state"] == "UNCONFIGURED"
    with candidate.runtime.reader() as conn:
        assert manual_report(conn, row["from_on"], candidate.service.settings(conn))[0] is None
        assert conn.execute(select(func.count()).select_from(OUTBOX)).scalar_one() == 1
    assert delivery(candidate.runtime, queued["id"])["state"] == "UNKNOWN"
    assert not lab.transport.calls


def test_initial_guard_commit_lost_ack_keeps_core_held_and_receipt_replays_once(lab, monkeypatch):
    _, _, queued = queue(lab.source, "2026-10-01")
    candidate = lab.prepare()
    context = activation_context(candidate.runtime.root)
    execute = candidate.runtime.writer.execute

    def lost_ack(*args, **kwargs):
        result = execute(*args, **kwargs)
        if args[1] == GUARD_ACTION:
            raise OSError("synthetic lost ACK after guard commit")
        return result

    monkeypatch.setattr(candidate.runtime.writer, "execute", lost_ack)
    with pytest.raises(CoreError, match="MAINTENANCE_ACTIVATION_FAILED"):
        activate(candidate)
    monkeypatch.setattr(candidate.runtime.writer, "execute", execute)
    assert candidate.runtime.maintenance.status()["state"] == "FAILED_HELD"
    assert candidate.runtime.runner.thread.ident is None
    assert candidate.runtime.periodic.thread.ident is None
    version = candidate.service.settings()["version"]
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    other = candidate.runtime.auth.authenticate(login["access_token"])
    assert candidate.service.restore_quarantine(other, context)["quarantined"] == 1
    assert candidate.service.settings()["version"] == version
    assert delivery(candidate.runtime, queued["id"])["version"] == 2
    candidate.runtime.close()
    reopened = lab.make(candidate.runtime.root.path)
    assert reopened.runtime.maintenance.status()["state"] == "DORMANT"
    with pytest.raises(CoreError, match="ACTIVATION_REPLAY_REQUIRED"):
        reopened.runtime.activate(candidate.operation_id, access_token=reopened.token)
    assert reopened.service.restore_quarantine(reopened.actor, context)["quarantined"] == 1
    assert reopened.service.settings()["version"] == version
    assert not lab.transport.calls


def test_old_retry_receipt_cannot_bypass_hold_or_return_stale_waiting(lab):
    _, _, queued = queue(lab.source, "2026-10-01", state="FAILED")
    command = models.Retry(request_key="source-retry", expected_version=1)
    retried = lab.source.service.retry(lab.source.actor, queued["id"], command)
    assert retried["state"] == "WAITING"
    candidate = lab.prepare()
    activate(candidate)
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    actor = candidate.runtime.auth.authenticate(login["access_token"])
    with pytest.raises(CoreError, match=REVIEW_CODE):
        candidate.service.retry(actor, queued["id"], command)
    config(candidate.service, actor, enabled=True)
    replay = candidate.service.retry(actor, queued["id"], command)
    assert replay["state"] == "UNKNOWN" and replay["version"] == retried["version"] + 1
    assert delivery(candidate.runtime, queued["id"])["state"] == "UNKNOWN"
    assert not lab.transport.calls


def test_revocation_between_guard_fences_denies_committed_receipt_replay(lab, monkeypatch):
    queue(lab.source, "2026-10-01")
    candidate = lab.prepare()
    activate(candidate)
    context = activation_context(candidate.runtime.root)
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    other = candidate.runtime.auth.authenticate(login["access_token"])
    execute = candidate.runtime.writer.execute

    def revoke_then_replay(*args, **kwargs):
        # AuthService uses execute too; restore it before the queued mutation.
        monkeypatch.setattr(candidate.runtime.writer, "execute", execute)
        candidate.runtime.auth.update_user(
            other,
            candidate.actor.id,
            role="operator",
            active=False,
            expected_version=candidate.actor.version,
            request_key="queued-revoke",
        )
        return execute(*args, **kwargs)

    monkeypatch.setattr(candidate.runtime.writer, "execute", revoke_then_replay)
    before = candidate.service.settings()["version"]
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        candidate.service.restore_quarantine(candidate.actor, context)
    assert candidate.service.settings()["version"] == before


def test_review_allows_future_day_generation_without_replacement_of_old_unknown(lab):
    today = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    _, _, queued = queue(lab.source, "2026-11-07")
    candidate = lab.prepare()
    activate(candidate)
    clock = {"now": today}
    candidate.service.clock = lambda: clock["now"]
    config(candidate.service, candidate.actor, enabled=True, auto=True)
    captures = lab.dto_source.calls
    candidate.service.tick(today)
    assert lab.dto_source.calls == captures and not lab.transport.calls
    with candidate.runtime.reader() as conn:
        run = conn.execute(select(DAILY_RUNS)).mappings().one()
        assert run.state == "NEEDS_MANUAL" and run.error_code == REVIEW_CODE
    clock["now"] = today + timedelta(days=1)
    assert candidate.service.tick(clock["now"])["delivery"]["state"] == "SENT"
    assert lab.dto_source.calls == captures + 1
    assert lab.transport.calls.count("text") == 1
    assert delivery(candidate.runtime, queued["id"])["state"] == "UNKNOWN"
    with candidate.runtime.reader() as conn:
        old = (
            conn.execute(select(DAILY_RUNS).where(DAILY_RUNS.c.business_on == "2026-11-07"))
            .mappings()
            .one()
        )
        assert old.state == "NEEDS_MANUAL" and old.error_code == REVIEW_CODE


@pytest.mark.parametrize("automatic", [False, True])
def test_held_series_blocks_existing_saved_revision_but_future_and_explicit_send_work(
    lab, automatic
):
    today = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    first, first_export, queued = queue(lab.source, "2026-11-07")
    preview = lab.source.service.preview(
        lab.source.actor,
        models.Preview(
            request_key="saved-revision-before-backup",
            from_on="2026-11-07",
            through_on="2026-11-07",
            book_ids=[],
            reason="Synthetic saved adjustment, not explicitly queued.",
        ),
    )
    second = lab.source.service.save(
        lab.source.actor,
        preview["id"],
        models.Save(
            request_key="save-revision-before-backup",
            expected_version=preview["version"],
        ),
    )
    second_export = lab.source.service.export(
        lab.source.actor,
        second["id"],
        models.Export(
            request_key="export-revision-before-backup",
            format="txt",
        ),
    )
    assert second["version"] == 2 and lab.source.service.list("deliveries")["total"] == 1
    frozen = []
    for row, item in ((first, first_export), (second, second_export)):
        with lab.source.runtime.files.read(item["file_id"]) as stream:
            frozen.append((row, item, stream.read()))
    candidate = lab.prepare()
    activate(candidate)
    clock = {"now": today}
    candidate.service.clock = lambda: clock["now"]
    config(candidate.service, candidate.actor, enabled=True, auto=automatic)
    held = delivery(candidate.runtime, queued["id"])
    captures = lab.dto_source.calls
    for _ in range(2):
        candidate.service.tick(clock["now"])
    assert lab.transport.calls == [] and lab.dto_source.calls == captures
    assert candidate.service.list("deliveries")["total"] == 1
    assert candidate.service.list("reports")["total"] == 2
    assert delivery(candidate.runtime, queued["id"]) == held
    with candidate.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(ATTEMPTS)).scalar_one() == 0
        assert manual_report(conn, "2026-11-07", candidate.service.settings(conn)) == (
            None,
            "RESTORE_REQUIRES_MANUAL",
        )

    clock["now"] = today + timedelta(days=1)
    if not automatic:
        report(candidate, "2026-11-08")
    assert candidate.service.tick(clock["now"])["delivery"]["state"] == "SENT"
    assert lab.transport.calls.count("text") == 1
    assert delivery(candidate.runtime, queued["id"]) == held

    # Existing explicit Admin enqueue/dispatch is allowed after settings review.
    explicit = candidate.service.enqueue(
        candidate.actor,
        second["id"],
        models.Enqueue(
            request_key="explicit-admin-revision-send",
        ),
    )
    assert explicit["state"] == "WAITING"
    assert sender.dispatch_one(candidate.service)["state"] == "SENT"
    assert lab.transport.calls.count("text") == 2
    assert delivery(candidate.runtime, queued["id"]) == held
    for row, item, content in frozen:
        current = candidate.service.detail(row["id"])
        assert current["snapshot"] == row["snapshot"] and current["sha256"] == row["sha256"]
        with candidate.runtime.files.read(item["file_id"]) as stream:
            assert stream.read() == content


def relocation_files(lab):
    row, txt = report(lab.source, "2026-10-01")
    receipts = [txt] + [
        lab.source.service.export(
            lab.source.actor,
            row["id"],
            models.Export(
                request_key="relocate-" + format,
                format=format,
            ),
        )
        for format in ("pdf", "xlsx")
    ]
    # Local-copy maintenance does not need a provider target or credentials.
    lab.source.service.update_settings(
        lab.source.actor,
        models.DeliverySettings(
            request_key="local-only-relocation",
            expected_version=lab.source.service.settings()["version"],
            enabled=False,
            chat_id="",
        ),
    )
    frozen = {}
    for receipt in receipts:
        path = lab.source.runtime.root.resolve_key(receipt["local_export"]["relative_key"])
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == receipt["sha256"]
        frozen[receipt["id"]] = content
    return row, receipts, frozen


def preserved_relocation_inputs(lab, candidate, tmp_path):
    paths = list(lab.source.runtime.root.path.rglob("*"))
    backup = tmp_path / ("backup-" + candidate.operation_id)
    if backup.exists():
        paths += list(backup.rglob("*"))
    paths.append(candidate.runtime.root.resolve_key("backup-manifest.json"))
    # Windows deliberately denies reads of the live process-lock byte; it is not
    # source data or a backup artifact. The source DB/files remain hashed below.
    return {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file() and path.name != ".instance.lock"
    }


def assert_preserved_inputs(frozen):
    assert all(
        path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        for path, digest in frozen.items()
    )


def assert_relocated_files(candidate, receipts, frozen):
    for receipt in receipts:
        path = candidate.runtime.root.resolve_key(receipt["local_export"]["relative_key"])
        assert path.read_bytes() == frozen[receipt["id"]]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"]
        with candidate.runtime.files.read(receipt["file_id"]) as stream:
            assert stream.read() == frozen[receipt["id"]]
    assert {
        item["local_export"]["state"]
        for item in candidate.service.detail(receipts[0]["report_id"])["exports"]
    } == {"READY"}


@pytest.mark.parametrize("kind", ["move", "restore"])
def test_activation_recreates_all_three_human_formats_before_recovery_in_bounded_pages(
    lab,
    tmp_path,
    monkeypatch,
    kind,
):
    row, receipts, frozen = relocation_files(lab)
    candidate = lab.prepare(kind)
    inputs = preserved_relocation_inputs(lab, candidate, tmp_path)
    assert all(
        not candidate.runtime.root.resolve_key(item["local_export"]["relative_key"]).exists()
        for item in receipts
    )
    monkeypatch.setattr(local_exports, "RELOCATION_PAGE_SIZE", 2)
    monkeypatch.setattr(
        exports, "render", lambda *args: pytest.fail("Canonical exports must not be re-rendered")
    )
    actual_export = candidate.runtime.files.export
    copied = []

    def copy(file_id, destination):
        assert candidate.runtime.maintenance.status()["state"] == "ACTIVATING"
        candidate.runtime.writer.run(candidate.service.authorize(candidate.actor, "core.manage"))
        copied.append(file_id)
        return actual_export(file_id, destination)

    monkeypatch.setattr(candidate.runtime.files, "export", copy)
    recover = candidate.runtime.jobs.recover_interrupted

    def observe_recovery():
        assert_relocated_files(candidate, receipts, frozen)
        return recover()

    monkeypatch.setattr(candidate.runtime.jobs, "recover_interrupted", observe_recovery)
    lab.secrets.reads = lab.secrets.writes = 0
    assert activate(candidate)["state"] == "ACTIVE"
    assert len(copied) == 3
    assert_relocated_files(candidate, receipts, frozen)
    assert candidate.service.detail(row["id"])["snapshot"] == row["snapshot"]
    context = activation_context(candidate.runtime.root)
    before = {
        item["id"]: item["local_export"]["attempts"]
        for item in candidate.service.detail(row["id"])["exports"]
    }
    candidate.service.restore_quarantine(candidate.actor, context)
    assert candidate.service.repair_local_exports(candidate.actor, context) == {
        "ready": 3,
        "failed": 0,
    }
    assert len(copied) == 3
    assert {
        item["id"]: item["local_export"]["attempts"]
        for item in candidate.service.detail(row["id"])["exports"]
    } == before
    assert not lab.transport.calls and lab.secrets.reads == lab.secrets.writes == 0
    assert_preserved_inputs(inputs)
    with candidate.runtime.reader() as conn:
        audit = (
            conn.execute(select(AUDIT).where(AUDIT.c.action == "invalidate_local_copies"))
            .mappings()
            .one()
        )
        assert audit.actor == candidate.actor.id


@pytest.mark.parametrize("failure", ["io", "conflict"])
def test_relocation_copy_failure_is_visible_retryable_and_never_overwrites_unknown_file(
    lab,
    tmp_path,
    monkeypatch,
    failure,
):
    row, receipts, frozen = relocation_files(lab)
    candidate = lab.prepare()
    inputs = preserved_relocation_inputs(lab, candidate, tmp_path)
    txt = next(item for item in receipts if item["format"] == "txt")
    path = candidate.runtime.root.resolve_key(txt["local_export"]["relative_key"])
    actual_export = candidate.runtime.files.export
    if failure == "conflict":
        path.write_bytes(b"UNKNOWN-USER-FILE")
    else:

        def unavailable(file_id, destination):
            if destination.suffix == ".txt":
                raise OSError("synthetic interrupted local-copy IO")
            return actual_export(file_id, destination)

        monkeypatch.setattr(candidate.runtime.files, "export", unavailable)
    assert activate(candidate)["state"] == "ACTIVE"
    details = {item["format"]: item for item in candidate.service.detail(row["id"])["exports"]}
    state = details["txt"]["local_export"]
    assert state["state"] == ("FAILED" if failure == "io" else "CONFLICT")
    assert state["verified_at"] is None
    assert (
        details["pdf"]["local_export"]["state"]
        == details["xlsx"]["local_export"]["state"]
        == "READY"
    )
    context = activation_context(candidate.runtime.root)
    if failure == "conflict":
        assert candidate.service.repair_local_exports(candidate.actor, context)["failed"] == 1
        assert path.read_bytes() == b"UNKNOWN-USER-FILE"
        path.unlink()  # Synthetic owner resolves its own conflicting file.
    monkeypatch.setattr(candidate.runtime.files, "export", actual_export)
    assert candidate.service.repair_local_exports(candidate.actor, context) == {
        "ready": 3,
        "failed": 0,
    }
    assert_relocated_files(candidate, receipts, frozen)
    assert not lab.transport.calls
    assert_preserved_inputs(inputs)


def test_interrupted_activation_copy_reuses_completed_bytes_after_restart_with_fresh_admin(
    lab,
    tmp_path,
    monkeypatch,
):
    _, receipts, frozen = relocation_files(lab)
    candidate = lab.prepare()
    inputs = preserved_relocation_inputs(lab, candidate, tmp_path)
    context = activation_context(candidate.runtime.root)
    actual_export = candidate.runtime.files.export
    copied = []

    class Interrupted(BaseException):
        pass

    def interrupt(file_id, destination):
        actual_export(file_id, destination)
        copied.append(file_id)
        raise Interrupted()

    monkeypatch.setattr(candidate.runtime.files, "export", interrupt)
    with pytest.raises(CoreError, match="MAINTENANCE_ACTIVATION_FAILED"):
        activate(candidate)
    with candidate.runtime.reader() as conn:
        assert set(conn.execute(select(LOCAL_EXPORTS.c.state)).scalars()) <= {"COPYING", "PENDING"}
    assert len(copied) == 1
    candidate.runtime.close()
    reopened = lab.make(candidate.runtime.root.path, username="restoreadmin")
    assert reopened.runtime.maintenance.status()["state"] == "DORMANT"
    export = reopened.runtime.files.export

    def copy_remaining(file_id, destination):
        assert file_id not in copied
        return export(file_id, destination)

    monkeypatch.setattr(reopened.runtime.files, "export", copy_remaining)
    assert reopened.service.repair_local_exports(reopened.actor, context) == {
        "ready": 3,
        "failed": 0,
    }
    assert_relocated_files(reopened, receipts, frozen)
    assert reopened.runtime.maintenance.status()["state"] == "DORMANT"
    assert not lab.transport.calls
    assert_preserved_inputs(inputs)


def test_revoked_activation_admin_cannot_finalize_or_replay_local_repair(
    lab, tmp_path, monkeypatch
):
    row, receipts, frozen = relocation_files(lab)
    candidate = lab.prepare("move")
    inputs = preserved_relocation_inputs(lab, candidate, tmp_path)
    login = candidate.runtime.auth.login("restoreadmin", PASSWORD)
    other = candidate.runtime.auth.authenticate(login["access_token"])
    context = activation_context(candidate.runtime.root)
    export = candidate.runtime.files.export

    def revoke_after_copy(file_id, destination):
        result = export(file_id, destination)
        candidate.runtime.auth.update_user(
            other,
            candidate.actor.id,
            role="operator",
            active=False,
            expected_version=candidate.actor.version,
            request_key="revoke-local-activation-admin",
        )
        return result

    monkeypatch.setattr(candidate.runtime.files, "export", revoke_after_copy)
    with pytest.raises(CoreError, match="MAINTENANCE_ACTIVATION_FAILED"):
        activate(candidate)
    with candidate.runtime.reader() as conn:
        assert set(conn.execute(select(LOCAL_EXPORTS.c.state)).scalars()) <= {"FAILED", "PENDING"}
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        candidate.service.repair_local_exports(candidate.actor, context)
    monkeypatch.setattr(candidate.runtime.files, "export", export)
    assert candidate.service.repair_local_exports(other, context) == {"ready": 3, "failed": 0}
    assert_relocated_files(candidate, receipts, frozen)
    with candidate.runtime.reader() as conn:
        audits = (
            conn.execute(
                select(AUDIT).where(
                    AUDIT.c.entity == "reporting_local_export", AUDIT.c.actor == other.id
                )
            )
            .mappings()
            .all()
        )
        assert audits
    assert candidate.service.detail(row["id"])["snapshot"] == row["snapshot"]
    assert not lab.transport.calls
    assert_preserved_inputs(inputs)
