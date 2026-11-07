"""Real SQLite v3 -> v4 upgrade and current-version restore, using synthetic data."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cafe_fin.core.db import AUDIT, SCHEMA, canonical_json
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_operations import MaintenanceOperations
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.time import utc_now
from cafe_fin.reporting import migrations as legacy
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.restore import REVIEW_CODE
from cafe_fin.reporting.schedule_migrations import DAILY_RUNS
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram import MessageReceipt
from cafe_fin.reporting.telegram_migrations import ATTEMPTS, OUTBOX, TRANSITION_CODE
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.reporting.conftest import MemorySecrets, TypedSyntheticSource

PASSWORD = "synthetic-provider-upgrade-password"
BOT_ID = "123456"
CHAT_ID = "-1001234567890"
OLD_STATES = ("WAITING", "SENDING", "FAILED", "UNKNOWN", "UNCONFIGURED", "SENT")
FROZEN_CHECKSUMS = {
    1: "4905f7fc692f7969cf9dd940c3b5c7886c5de338dd49079f3b30009d42baf656",
    2: "2d9052e06e943722ae46d218ed93b503cb993ee9d162410c5cd1a602a1b8ccd7",
    3: "ae4a93ea23f4cb3dfc62798f28b25e6bce92f51d7b18ef74ecd7e97333e687b2",
}


class CheckedSecrets(MemorySecrets):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.locked = False
        self.values["cafe_fin/reporting/synthetic-root/legacy-oa"] = {
            "access_token": "SYNTHETIC-OLD"
        }

    def check(self, operation, key):
        self.calls.append((operation, key))
        assert not self.locked, "Activation must not consult or rewrite OS credentials"
        assert "/telegram/" in key, "Legacy credential namespace must never be consulted"

    def has(self, key):
        self.check("has", key)
        return super().has(key)

    def get(self, key):
        self.check("get", key)
        return super().get(key)

    def put(self, key, value):
        self.check("put", key)
        return super().put(key, value)


class CheckedTransport:
    def __init__(self):
        self.texts, self.files, self.verifications = [], [], []
        self.locked = False

    def verify(self, token, chat_id, bot_id, *, documents=False):
        self.verifications.append((chat_id, bot_id, documents))
        assert not self.locked
        return bot_id

    def send_text(self, token, chat_id, text, bot_id):
        self.texts.append((chat_id, bot_id, text))
        assert not self.locked
        return MessageReceipt(chat_id, len(self.texts) + 100)

    def send_document(self, token, chat_id, content, filename, bot_id):
        self.files.append((chat_id, bot_id, content, filename))
        assert not self.locked
        return MessageReceipt(chat_id, len(self.files) + 200)


def all_rows(runtime, table):
    with runtime.reader() as conn:
        return {row["id"]: dict(row) for row in conn.execute(select(table)).mappings()}


def make_report(env, day, *, suffix="", formats=("txt",)):
    key = day + suffix
    preview = env.service.preview(
        env.actor,
        models.Preview(
            request_key="preview-" + key,
            from_on=day,
            through_on=day,
            book_ids=[],
            reason="Synthetic legacy fixture " + suffix,
        ),
    )
    report = env.service.save(
        env.actor,
        preview["id"],
        models.Save(request_key="save-" + key, expected_version=preview["version"]),
    )
    exports = [
        env.service.export(
            env.actor, report["id"], models.Export(request_key="export-" + key + fmt, format=fmt)
        )
        for fmt in formats
    ]
    return report, exports


def set_telegram(env, *, bot_id=BOT_ID, chat_id=CHAT_ID, automatic=False):
    env.service.update_settings(
        env.actor,
        models.DeliverySettings(
            request_key="telegram-config-" + uuid4().hex,
            expected_version=env.service.settings()["version"],
            chat_id=chat_id,
            enabled=True,
            send_at="18:00",
            auto_generate_daily=automatic,
            daily_export_formats=["txt"],
        ),
    )
    env.service.set_credentials(env.actor, models.Credentials(bot_token=bot_id + ":" + "A" * 35))
    assert sender.check_connection(env.service, env.actor)["state"] == "CONNECTED"


@pytest.fixture
def upgraded(tmp_path):
    runtimes = []
    source, secrets, transport = TypedSyntheticSource(), CheckedSecrets(), CheckedTransport()
    manifest = module_manifest(source=source, secret_store=secrets, transport=transport)
    old_manifest = replace(manifest, migrations=manifest.migrations[:3])

    def open_env(path, *, old=False, initialize=False):
        registry = ModuleRegistry((old_manifest if old else manifest,))
        runtime = Runtime(path, initialize=initialize, modules=registry)
        runtimes.append(runtime)
        auth = (
            runtime.auth.setup("transitionadmin", PASSWORD)
            if initialize
            else runtime.auth.login("transitionadmin", PASSWORD)
        )
        actor = runtime.auth.authenticate(auth["access_token"])
        return SimpleNamespace(
            runtime=runtime,
            actor=actor,
            token=auth["access_token"],
            service=ReportingService(
                runtime, source=source, secret_store=secrets, transport=transport
            ),
        )

    path = tmp_path / "synthetic-v3-root"
    before = open_env(path, old=True, initialize=True)
    reports, export_bytes = {}, {}
    old_settings = {
        "oa_id": "synthetic-legacy-oa",
        "group_id": "synthetic-legacy-group",
        "enabled": True,
        "auto_generate_daily": True,
        "scheduled_actor_id": before.actor.id,
        "auto_activated_on": "2026-11-01",
        "timezone": "Asia/Ho_Chi_Minh",
        "send_at": "18:00",
        "attachments_enabled": True,
        "daily_book_ids": [],
        "daily_export_formats": ["pdf", "xlsx", "txt"],
        "restore_review": None,
    }
    for index, state in enumerate(OLD_STATES, 1):
        day = f"2026-11-{index:02}"
        report, items = make_report(
            before, day, formats=("pdf", "xlsx", "txt") if index == 1 else ("txt",)
        )
        reports[state] = report
        for item in items:
            with before.runtime.files.read(item["file_id"]) as stream:
                export_bytes[item["id"]] = (item, stream.read())
        now = utc_now()
        payload = canonical_json(
            {
                "date_range_contract": models.DATE_RANGE_CONTRACT,
                "text": "Frozen synthetic legacy payload " + state,
                "snapshot_sha256": report["sha256"],
            }
        )

        def seed(conn):
            conn.execute(
                legacy.OUTBOX.insert().values(
                    id="old-" + state,
                    report_id=report["id"],
                    destination="synthetic-legacy-group",
                    oa_id="synthetic-legacy-oa",
                    config_version=7,
                    payload_json=payload,
                    attachment_export_id=items[0]["id"] if index == 1 else None,
                    state=state,
                    phase="attachment" if index == 1 else "text",
                    version=3,
                    attempts=2,
                    message_id="123",
                    file_message_id="456" if state in {"UNKNOWN", "SENT"} else None,
                    error_code="SYNTHETIC_OLD_ERROR" if state != "SENT" else None,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                legacy.ATTEMPTS.insert().values(
                    id="attempt-" + state,
                    outbox_id="old-" + state,
                    phase="text",
                    outcome="SENT" if state == "SENT" else "UNKNOWN",
                    code="SYNTHETIC_HISTORY",
                    message_id="123",
                    created_at=now,
                )
            )
            conn.execute(
                DAILY_RUNS.insert().values(
                    id="run-" + state,
                    profile_id="delivery",
                    business_on=day,
                    state={
                        "SENT": "COMPLETED",
                        "SENDING": "RUNNING",
                        "FAILED": "FAILED",
                        "UNKNOWN": "BLOCKED",
                    }.get(state, "PENDING"),
                    phase="queue",
                    pins_json=canonical_json(old_settings),
                    actor_id=before.actor.id,
                    config_version=7,
                    report_id=report["id"],
                    outbox_id="old-" + state,
                    policy="SYNTHETIC_OLD_PIN",
                    attempts=2,
                    error_code=None,
                    created_at=now,
                    updated_at=now,
                )
            )

        before.runtime.writer.run(seed)
    # A newer saved revision in an old delivery's series must also stay out of automatic catch-up.
    newer, newer_exports = make_report(before, "2026-11-01", suffix="-revision-2")
    for item in newer_exports:
        with before.runtime.files.read(item["file_id"]) as stream:
            export_bytes[item["id"]] = (item, stream.read())
    before.runtime.writer.run(
        lambda conn: conn.execute(
            legacy.SETTINGS.insert().values(
                id="delivery",
                version=7,
                config_json=canonical_json(old_settings),
                updated_at=utc_now(),
            )
        )
    )
    frozen = {
        "reports": all_rows(before.runtime, legacy.REPORTS),
        "exports": all_rows(before.runtime, legacy.EXPORTS),
        "outbox": all_rows(before.runtime, legacy.OUTBOX),
        "attempts": all_rows(before.runtime, legacy.ATTEMPTS),
        "runs": all_rows(before.runtime, DAILY_RUNS),
    }
    with before.runtime.reader() as conn:
        old_schema = [
            dict(row)
            for row in conn.execute(
                select(SCHEMA).where(SCHEMA.c.namespace == "reporting")
            ).mappings()
        ]
    before.runtime.close()
    env = open_env(path)
    env.service.clock = lambda: datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    yield SimpleNamespace(
        env=env,
        source=source,
        secrets=secrets,
        transport=transport,
        open_env=open_env,
        frozen=frozen,
        exports=export_bytes,
        reports=reports,
        newer=newer,
        old_schema=old_schema,
        tmp_path=tmp_path,
    )
    secrets.locked = transport.locked = False
    for runtime in reversed(runtimes):
        runtime.close()


def assert_frozen_history(lab, env):
    assert all_rows(env.runtime, legacy.REPORTS) == lab.frozen["reports"]
    assert all_rows(env.runtime, legacy.EXPORTS) == lab.frozen["exports"]
    for identity, old in lab.frozen["attempts"].items():
        current = all_rows(env.runtime, ATTEMPTS)[identity]
        assert {key: current[key] for key in old} == old
        assert current["provider"] == "zalo_legacy"
        assert current["bot_id"] is None and current["chat_id"] is None
    for item, content in lab.exports.values():
        with env.runtime.files.read(item["file_id"]) as stream:
            assert stream.read() == content


def test_real_v3_upgrade_preserves_frozen_reports_files_payloads_and_legacy_provenance(upgraded):
    lab, env = upgraded, upgraded.env
    assert_frozen_history(lab, env)
    assert not lab.secrets.calls and not lab.transport.verifications
    rows = all_rows(env.runtime, OUTBOX)
    for identity, old in lab.frozen["outbox"].items():
        row = rows[identity]
        unchanged = set(old) - {"state", "error_code", "version", "updated_at"}
        assert {key: row[key] for key in unchanged} == {key: old[key] for key in unchanged}
        assert row["provider"] == "zalo_legacy"
        assert all(
            row[key] is None
            for key in (
                "bot_id",
                "chat_id",
                "message_chat_id",
                "file_message_chat_id",
                "retry_not_before",
            )
        )
        if old["state"] == "SENT":
            assert {key: row[key] for key in old} == old
        else:
            assert row["state"] == "UNKNOWN" and row["error_code"] == TRANSITION_CODE
            assert row["version"] == old["version"] + 1
    for row in env.service.list("deliveries")["items"]:
        assert row["provider"] == "zalo_legacy" and "oa_id" not in row
        history = env.service.attempts(row["id"], 1, 25)
        assert history["total"] == 1 and history["items"][0]["provider"] == "zalo_legacy"


def test_upgrade_disables_old_targets_and_daily_work_without_losing_nonsecret_preferences(upgraded):
    env = upgraded.env
    settings = env.service.public_settings()
    assert settings["version"] == 8 and settings["provider"] == "telegram"
    assert settings["chat_id"] == "" and settings["bot_id"] is None
    assert settings["bot_verified_at"] is None and settings["credential_configured"] is False
    assert settings["enabled"] is False and settings["auto_generate_daily"] is False
    assert settings["scheduled_actor_id"] is None and settings["auto_activated_on"] is None
    assert settings["timezone"] == "Asia/Ho_Chi_Minh" and settings["send_at"] == "18:00"
    assert settings["daily_export_formats"] == ["pdf", "xlsx", "txt"]
    assert "oa_id" not in settings and "group_id" not in settings
    assert not upgraded.secrets.calls
    runs = all_rows(env.runtime, DAILY_RUNS)
    for identity, old in upgraded.frozen["runs"].items():
        row = runs[identity]
        if old["state"] == "COMPLETED":
            assert row == old
        else:
            assert row["state"] == "NEEDS_MANUAL" and row["error_code"] == TRANSITION_CODE
            assert row["pins_json"] == old["pins_json"]
            assert row["report_id"] == old["report_id"] and row["outbox_id"] == old["outbox_id"]


def test_historical_migration_checksums_and_applied_receipts_stay_unchanged(upgraded):
    with upgraded.env.runtime.reader() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                select(SCHEMA).where(SCHEMA.c.namespace == "reporting").order_by(SCHEMA.c.version)
            ).mappings()
        ]
    assert len(rows) == 4
    assert rows[:3] == sorted(upgraded.old_schema, key=lambda row: row["version"])
    assert {row["version"]: row["checksum"] for row in rows[:3]} == FROZEN_CHECKSUMS


def python_process(code, *arguments, hash_seed):
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = str(hash_seed)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "backend")
    completed = subprocess.run(
        [sys.executable, "-c", code, *map(str, arguments)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=environment,
    )
    return json.loads(completed.stdout)


def test_migration_fingerprints_are_stable_across_fresh_python_hash_seeds():
    code = """
import json
from cafe_fin.reporting.module import module_manifest
print(json.dumps({item.version: item.fingerprint for item in module_manifest().migrations}))
"""
    expected = {str(item.version): item.fingerprint for item in module_manifest().migrations}
    for seed in (0, 1, 7, 42):
        assert python_process(code, hash_seed=seed) == expected


def test_real_v3_upgrade_reopens_in_another_process_without_checksum_drift(upgraded):
    env = upgraded.env
    frozen = all_rows(env.runtime, OUTBOX)
    path = env.runtime.root.path
    env.runtime.close()  # Release Windows' actual root lock before the next process opens it.
    code = """
import json
import sys
from sqlalchemy import select
from cafe_fin.core.db import SCHEMA
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.telegram_migrations import OUTBOX

runtime = Runtime(sys.argv[1], modules=ModuleRegistry((module_manifest(),)))
try:
    with runtime.reader() as conn:
        rows = {row['id']: dict(row) for row in conn.execute(select(OUTBOX)).mappings()}
        schema = {str(row.version): row.checksum for row in conn.execute(
            select(SCHEMA).where(SCHEMA.c.namespace == 'reporting')).mappings()}
    print(json.dumps({'outbox': rows, 'schema': schema}))
finally:
    runtime.close()
"""
    expected_schema = {str(item.version): item.fingerprint for item in module_manifest().migrations}
    for seed in (3, 91):
        reopened = python_process(code, path, hash_seed=seed)
        assert reopened["schema"] == expected_schema
        assert reopened["outbox"] == frozen


def test_reopening_upgrade_does_not_quarantine_again_or_repeat_transition_audit(upgraded):
    lab, env = upgraded, upgraded.env
    frozen_rows = all_rows(env.runtime, OUTBOX)
    settings = env.service.settings()
    with env.runtime.reader() as conn:
        audits = [
            dict(row)
            for row in conn.execute(
                select(AUDIT).where(AUDIT.c.actor == "reporting.provider-transition")
            ).mappings()
        ]
    env.runtime.close()
    reopened = lab.open_env(env.runtime.root.path)
    assert all_rows(reopened.runtime, OUTBOX) == frozen_rows
    assert reopened.service.settings() == settings
    with reopened.runtime.reader() as conn:
        assert [
            dict(row)
            for row in conn.execute(
                select(AUDIT).where(AUDIT.c.actor == "reporting.provider-transition")
            ).mappings()
        ] == audits
    assert_frozen_history(lab, reopened)
    assert not lab.secrets.calls


@pytest.mark.parametrize("identity", ["old-" + state for state in OLD_STATES])
def test_legacy_rows_cannot_be_retried_after_new_configuration(upgraded, identity):
    lab, env = upgraded, upgraded.env
    set_telegram(env)
    before = all_rows(env.runtime, OUTBOX)
    with pytest.raises(CoreError, match="LEGACY_DELIVERY_READ_ONLY"):
        env.service.retry(
            env.actor,
            identity,
            models.Retry(
                request_key="reject-old-" + identity, expected_version=before[identity]["version"]
            ),
        )
    assert all_rows(env.runtime, OUTBOX) == before
    assert not lab.transport.texts and not lab.transport.files
    assert_frozen_history(lab, env)


@pytest.mark.parametrize("automatic", [False, True])
def test_configuration_changes_and_other_bot_never_automatically_replay_legacy_series(
    upgraded, automatic
):
    lab, env = upgraded, upgraded.env
    before = all_rows(env.runtime, OUTBOX)
    for bot_id, chat_id in ((BOT_ID, CHAT_ID), ("999999", "-1009999999999")):
        # Automatic generation is anchored to this held day; manual catch-up sees all old days.
        when = datetime(2026, 11, 1 if automatic else 7, 12, tzinfo=timezone.utc)
        env.service.clock = lambda: when
        set_telegram(env, bot_id=bot_id, chat_id=chat_id, automatic=automatic)
        env.service.recover()
        assert env.service.catch_up(when) == 0
        env.service.tick(when)
        assert all_rows(env.runtime, OUTBOX) == before
        assert not lab.transport.texts and not lab.transport.files
    assert_frozen_history(lab, env)
    assert all("/telegram/" in key for _, key in lab.secrets.calls)


def test_explicit_new_work_creates_telegram_row_without_reusing_legacy_delivery(upgraded):
    lab, env = upgraded, upgraded.env
    set_telegram(env)
    old = all_rows(env.runtime, OUTBOX)
    queued = env.service.enqueue(
        env.actor,
        lab.reports["WAITING"]["id"],
        models.Enqueue(request_key="explicit-new-telegram-work"),
    )
    assert queued["id"] not in old and queued["provider"] == "telegram"
    assert queued["chat_id"] == CHAT_ID and queued["bot_id"] == BOT_ID
    assert queued["message_id"] is None and queued["message_chat_id"] is None
    assert sender.dispatch_one(env.service)["state"] == "SENT"
    assert len(lab.transport.texts) == 1
    rows = all_rows(env.runtime, OUTBOX)
    assert {identity: rows[identity] for identity in old} == old
    assert_frozen_history(lab, env)


@pytest.mark.parametrize("mutation", ["payload", "provider", "attempt-update", "attempt-delete"])
def test_upgrade_keeps_payload_and_attempt_history_immutable(upgraded, mutation):
    env = upgraded.env
    if mutation == "payload":
        statement = OUTBOX.update().where(OUTBOX.c.id == "old-WAITING").values(payload_json="{}")
    elif mutation == "provider":
        statement = OUTBOX.update().where(OUTBOX.c.id == "old-WAITING").values(provider="telegram")
    elif mutation == "attempt-update":
        statement = (
            ATTEMPTS.update().where(ATTEMPTS.c.id == "attempt-WAITING").values(provider="telegram")
        )
    else:
        statement = ATTEMPTS.delete().where(ATTEMPTS.c.id == "attempt-WAITING")
    with pytest.raises(IntegrityError, match="immutable"):
        env.runtime.writer.run(lambda conn: conn.execute(statement))


def test_upgraded_current_version_backup_restores_dormant_and_never_relabels_old_proofs(upgraded):
    lab, env = upgraded, upgraded.env
    set_telegram(env)
    backup = lab.tmp_path / "actual-upgraded-v4-backup"
    env.runtime.backups.create(backup)
    operation_id, generation = str(uuid4()), str(uuid4())
    env.runtime.quiesce(operation_id, access_token=env.token)
    selected = lab.tmp_path / "restore-target"
    selected.mkdir()
    destination = selected / ("CafeFinData-" + operation_id)
    result = MaintenanceOperations(env.runtime, generation=generation).prepare(
        operation_id,
        "restore",
        access_token=env.token,
        origin_generation=generation,
        destination=destination,
        backup_source=backup,
    )
    assert result["state"] == "PREPARED"
    candidate = lab.open_env(destination)
    assert candidate.runtime.maintenance.status()["state"] == "DORMANT"
    lab.secrets.calls.clear()
    verifications = list(lab.transport.verifications)
    lab.secrets.locked = lab.transport.locked = True
    activated = MaintenanceOperations(candidate.runtime, generation=str(uuid4())).activate(
        operation_id,
        access_token=candidate.token,
        origin_generation=generation,
    )
    assert activated["state"] == "ACTIVE"
    assert not lab.secrets.calls and not lab.transport.texts and not lab.transport.files
    assert lab.transport.verifications == verifications
    assert_frozen_history(lab, candidate)
    rows = all_rows(candidate.runtime, OUTBOX)
    for identity, old in lab.frozen["outbox"].items():
        row = rows[identity]
        assert row["provider"] == "zalo_legacy"
        assert (
            row["message_id"] == old["message_id"]
            and row["file_message_id"] == old["file_message_id"]
        )
        assert row["state"] == ("SENT" if old["state"] == "SENT" else "UNKNOWN")
        if old["state"] != "SENT":
            assert row["error_code"] == REVIEW_CODE
    assert candidate.service.settings()["restore_review"]["required"] is True
    lab.secrets.locked = lab.transport.locked = False
    set_telegram(candidate, bot_id="999999", chat_id="-1009999999999")
    assert candidate.service.catch_up(datetime(2026, 11, 7, 12, tzinfo=timezone.utc)) == 0
    assert sender.dispatch_one(candidate.service)["state"] in {"IDLE", "EMPTY"}
    assert not lab.transport.texts and not lab.transport.files
