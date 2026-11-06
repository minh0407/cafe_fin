"""Actual dormant/candidate activation with reporting's default owner hook."""

import copy
import hashlib
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
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.migrations import ATTEMPTS, OUTBOX
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.restore import GUARD_ACTION, GUARD_ACTOR, REVIEW_CODE
from cafe_fin.reporting.schedule import insert_run, manual_report
from cafe_fin.reporting.schedule_migrations import DAILY_RUNS
from cafe_fin.reporting.service import ReportingService
from conftest import FakeTransport, MemorySecrets, TypedSyntheticSource
from sqlalchemy import func, select

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

    def refresh(self, *args):
        self.calls.append("refresh")
        return super().refresh(*args)

    def verify(self, *args):
        self.calls.append("verify")
        return super().verify(*args)

    def send_text(self, *args):
        self.calls.append("text")
        return super().send_text(*args)

    def reconcile(self, *args):
        self.calls.append("reconcile")
        return super().reconcile(*args)


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
        models.Credentials(app_id="demo", app_secret="SYNTHETIC", refresh_token="SYNTHETIC"),
    )

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


def config(service, actor, *, enabled, auto=False, group="demo-group", key=None):
    old = service.settings()
    return service.update_settings(
        actor,
        models.DeliverySettings(
            request_key=key or "config-" + str(uuid4()),
            expected_version=old["version"],
            enabled=enabled,
            auto_generate_daily=auto,
            oa_id="demo-oa",
            group_id=group,
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
                phase="attachment" if attachment else "text",
            )
        )
    )
    return row, item, result


def delivery(rt, identity):
    with rt.reader() as conn:
        return dict(conn.execute(select(OUTBOX).where(OUTBOX.c.id == identity)).mappings().one())


def activate(candidate):
    return MaintenanceOperations(candidate.runtime, generation=str(uuid4())).activate(
        candidate.operation_id, access_token=candidate.token, origin_generation=candidate.generation
    )


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
            ("SENDING", "confirmed-text", None, False),
            ("SENDING", "confirmed-prefix", None, True),
            ("UNKNOWN", None, None, False),
            ("SENT", "already-sent", None, False),
            ("SENDING", "confirmed-text-file", "confirmed-file", True),
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
    row, _, queued = queue(lab.source, "2026-10-01", state="SENT", text="proof")
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
        models.Credentials(
            app_id="demo", app_secret="NEW_SYNTHETIC", refresh_token="NEW_SYNTHETIC"
        ),
    )
    assert candidate.service.settings()["restore_review"]["required"]
    config(candidate.service, candidate.actor, enabled=True, group="another-group")
    assert candidate.service.catch_up() == 0
    assert sender.dispatch_one(candidate.service)["state"] == "IDLE"
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
