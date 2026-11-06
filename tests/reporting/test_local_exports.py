"""Real canonical bytes and Explorer copies, including partial progress and death."""

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.storage import FILES
from cafe_fin.reporting import exports, models
from cafe_fin.reporting.local_export_migrations import LOCAL_EXPORTS
from cafe_fin.reporting.local_exports import safe_key
from cafe_fin.reporting.migrations import EXPORTS, OUTBOX, REPORTS
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.schedule import list_runs
from cafe_fin.reporting.sender import dispatch_one
from cafe_fin.reporting.service import ReportingService
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.reporting.conftest import SyntheticSource, configure, saved
from tests.reporting.test_daily_generation import setup_auto


def count(runtime, table):
    with runtime.reader() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def no_render(*args, **kwargs):
    raise AssertionError("Existing canonical bytes must not be rendered again")


@pytest.mark.parametrize("format", ["pdf", "xlsx", "txt"])
def test_three_formats_named_copies_replay_and_missing_recreation_keep_canonical_identity(
    env, monkeypatch, format
):
    report = saved(env)
    command = models.Export(request_key="human", format=format)
    result = env.service.export(env.actor, report["id"], command)
    local = result["local_export"]
    assert local["state"] == "READY"
    assert (
        local["relative_key"] == f"reports/CafeFin-{report['from_on']}-v1-{report['id']}.{format}"
    )
    assert env.source.malicious not in local["relative_key"]
    path = env.runtime.root.resolve_key(local["relative_key"])
    content = path.read_bytes()
    assert hashlib.sha256(content).hexdigest() == result["sha256"]
    assert len(content) == result["size"]
    assert env.runtime.files.get(result["file_id"]).relative_key.endswith(".bin")
    monkeypatch.setattr(exports, "render", no_render)
    assert env.service.export(env.actor, report["id"], command) == result
    path.unlink()
    recreated = env.service.export(env.actor, report["id"], command)
    assert path.read_bytes() == content
    assert recreated["id"] == result["id"] and recreated["file_id"] == result["file_id"]
    assert recreated["local_export"]["attempts"] == 2
    assert env.source.calls == 1
    assert count(env.runtime, FILES) == count(env.runtime, EXPORTS) == 1


def test_changed_target_conflicts_without_overwrite_and_can_recover_from_canonical(
    env, monkeypatch
):
    report = saved(env)
    command = models.Export(request_key="human", format="txt")
    result = env.service.export(env.actor, report["id"], command)
    path = env.runtime.root.resolve_key(result["local_export"]["relative_key"])
    path.write_bytes(b"USER-existing-file-must-not-be-overwritten")
    monkeypatch.setattr(exports, "render", no_render)
    with pytest.raises(CoreError, match="LOCAL_EXPORT_CONFLICT"):
        env.service.export(env.actor, report["id"], command)
    assert path.read_bytes() == b"USER-existing-file-must-not-be-overwritten"
    state = env.service.detail(report["id"])["exports"][0]["local_export"]
    assert state["state"] == "CONFLICT" and state["error_code"] == "LOCAL_EXPORT_CONFLICT"
    assert count(env.runtime, FILES) == count(env.runtime, EXPORTS) == 1
    path.unlink()
    assert env.service.export(env.actor, report["id"], command)["local_export"]["state"] == "READY"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == result["sha256"]
    assert env.source.calls == 1


def test_daily_partial_filesystem_failure_keeps_outputs_receipts_then_resumes_without_recapture(
    env, monkeypatch
):
    service, source, clock, _ = setup_auto(env, formats=["pdf", "xlsx", "txt"])
    clock["now"] = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
    actual_export, render = env.runtime.files.export, exports.render
    rendered = []

    def observed_render(*args):
        rendered.append(args[-1])
        return render(*args)

    def fail_txt(file_id, destination):
        if destination.suffix == ".txt":
            raise OSError("SYNTHETIC-private-disk-error")
        return actual_export(file_id, destination)

    monkeypatch.setattr(exports, "render", observed_render)
    monkeypatch.setattr(env.runtime.files, "export", fail_txt)
    assert service.tick()["generation"]["state"] == "FAILED"
    report = service.list("reports")["items"][0]
    details = service.detail(report["id"])
    states = {x["format"]: x["local_export"] for x in details["exports"]}
    assert states["pdf"]["state"] == "READY" and states["txt"]["state"] == "FAILED"
    assert states["txt"]["error_code"] == "LOCAL_EXPORT_IO"
    assert "private" not in json.dumps(states)
    assert count(env.runtime, FILES) == count(env.runtime, EXPORTS) == 2
    assert count(env.runtime, OUTBOX) == 0
    monkeypatch.setattr(env.runtime.files, "export", actual_export)
    assert service.tick()["generation"]["state"] == "COMPLETED"
    assert source.calls == 1 and count(env.runtime, REPORTS) == 1
    assert Counter(rendered) == Counter(pdf=1, xlsx=1, txt=1)
    assert count(env.runtime, FILES) == count(env.runtime, EXPORTS) == 3
    for item in service.detail(report["id"])["exports"]:
        local = item["local_export"]
        path = env.runtime.root.resolve_key(local["relative_key"])
        assert local["state"] == "READY" and path.suffix == "." + item["format"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert service.list("deliveries")["items"][0]["state"] == "UNCONFIGURED"
    assert list_runs(service)["items"][0]["state"] == "COMPLETED"


def test_process_death_after_public_copy_reuses_it_after_restart_without_render(
    env, tmp_path, monkeypatch
):
    report = saved(env)
    actual = env.runtime.files.export
    monkeypatch.setattr(
        env.runtime.files, "export", lambda *args: (_ for _ in ()).throw(OSError("synthetic"))
    )
    with pytest.raises(CoreError, match="LOCAL_EXPORT_IO"):
        env.service.export(
            env.actor, report["id"], models.Export(request_key="first", format="txt")
        )
    canonical = env.service.detail(report["id"])["exports"][0]
    key = canonical["local_export"]["relative_key"]
    monkeypatch.setattr(env.runtime.files, "export", actual)
    env.runtime.close()
    code = r"""
import os, sys
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.models import Export
runtime = Runtime(sys.argv[1], modules=ModuleRegistry((module_manifest(),)))
service = ReportingService(runtime)
login = runtime.auth.login('reportadmin','synthetic-report-password')
actor = runtime.auth.authenticate(login['access_token'])
actual = runtime.files.export
def crash_after_copy(file_id, destination):
    actual(file_id, destination)
    os._exit(47)
runtime.files.export = crash_after_copy
service.export(actor,sys.argv[2],Export(request_key='child',format='txt'))
raise AssertionError('No crash')
"""
    root = Path(__file__).resolve().parents[2]
    process_env = os.environ.copy()
    process_env["PYTHONPATH"] = str(root / "backend")
    child = subprocess.run(
        [sys.executable, "-c", code, str(env.root), report["id"]],
        cwd=root,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 47, child.stderr
    runtime = Runtime(env.root, modules=env.registry)
    try:
        service = ReportingService(runtime)
        service.recover()
        assert service.detail(report["id"])["exports"][0]["local_export"]["state"] == "PENDING"
        before = runtime.root.resolve_key(key).read_bytes()
        monkeypatch.setattr(exports, "render", no_render)
        login = runtime.auth.login("reportadmin", "synthetic-report-password")
        actor = runtime.auth.authenticate(login["access_token"])
        item = service.export(
            actor, report["id"], models.Export(request_key="resume", format="txt")
        )
        assert item["id"] == canonical["id"] and item["file_id"] == canonical["file_id"]
        assert item["local_export"]["state"] == "READY"
        assert runtime.root.resolve_key(key).read_bytes() == before
        assert count(runtime, FILES) == count(runtime, EXPORTS) == count(runtime, REPORTS) == 1
        assert env.source.calls == 1
    finally:
        runtime.close()


def test_v2_upgrade_keeps_canonical_bytes_and_lazy_copy_without_render(tmp_path, monkeypatch):
    manifest = module_manifest(source=SyntheticSource())
    prior = Runtime(
        tmp_path / "upgrade-local",
        initialize=True,
        modules=ModuleRegistry((replace(manifest, migrations=manifest.migrations[:-1]),)),
    )
    try:
        login = prior.auth.setup("legacyadmin", "synthetic-legacy-password")
        actor = prior.auth.authenticate(login["access_token"])
        service = ReportingService(prior, source=SyntheticSource())
        preview = service.preview(
            actor, models.Preview(request_key="old", from_on="2026-11-06", through_on="2026-11-06")
        )
        report = service.save(
            actor, preview["id"], models.Save(request_key="save", expected_version=1)
        )
        canonical = service._export(
            actor, report["id"], models.Export(request_key="old-export", format="txt")
        )
    finally:
        prior.close()
    runtime = Runtime(tmp_path / "upgrade-local", modules=ModuleRegistry((manifest,)))
    try:
        service = ReportingService(runtime)
        assert service.detail(report["id"])["exports"][0]["local_export"] is None
        monkeypatch.setattr(exports, "render", no_render)
        login = runtime.auth.login("legacyadmin", "synthetic-legacy-password")
        actor = runtime.auth.authenticate(login["access_token"])
        result = service.export(
            actor, report["id"], models.Export(request_key="old-export", format="txt")
        )
        assert result["file_id"] == canonical["file_id"] and result["sha256"] == canonical["sha256"]
        assert service.detail(report["id"])["sha256"] == report["sha256"]
        with pytest.raises(IntegrityError):
            runtime.writer.run(
                lambda conn: conn.execute(
                    LOCAL_EXPORTS.update().values(relative_key="reports/other.txt")
                )
            )
    finally:
        runtime.close()


def test_existing_destination_race_reuses_only_matching_bytes(env, monkeypatch):
    report = saved(env)
    actual = env.runtime.files.export

    def created_by_other_process(file_id, destination):
        with env.runtime.files.read(file_id) as source:
            destination.write_bytes(source.read())
        return actual(file_id, destination)  # genuine EXPORT_EXISTS, no replacement

    monkeypatch.setattr(env.runtime.files, "export", created_by_other_process)
    result = env.service.export(
        env.actor, report["id"], models.Export(request_key="race", format="txt")
    )
    assert result["local_export"]["state"] == "READY"
    assert count(env.runtime, FILES) == 1


def test_local_relative_key_never_enters_group_payload_or_upload_metadata(env):
    report = saved(env)
    item = env.service.export(
        env.actor, report["id"], models.Export(request_key="human", format="txt")
    )
    configure(env, attachments=True)
    env.service.enqueue(
        env.actor,
        report["id"],
        models.Enqueue(request_key="queue", attachment_export_id=item["id"]),
    )
    assert dispatch_one(env.service)["state"] == "SENT"
    with env.runtime.reader() as conn:
        payload = conn.execute(select(OUTBOX.c.payload_json)).scalar_one()
    key = item["local_export"]["relative_key"]
    assert key not in payload and "local_export" not in payload
    assert key not in json.dumps(env.transport.texts)
    assert env.transport.uploads[0][1] == "CafeFin-summary.txt"
    assert "reports/" not in env.transport.uploads[0][1]
    assert safe_key(report["id"], report["from_on"], 1, "txt") == key


def test_revoked_actor_after_copy_cannot_mark_ready_and_new_authorized_retry_reuses_file(
    env, monkeypatch
):
    from tests.reporting.test_review_recovery import second_user

    other_admin = second_user(env, "admin")
    report = saved(env)
    actual = env.runtime.files.export

    def revoke_after_copy(file_id, destination):
        result = actual(file_id, destination)
        env.runtime.auth.update_user(
            other_admin,
            env.actor.id,
            role="operator",
            active=False,
            expected_version=env.actor.version,
            request_key="disable-copy-actor",
        )
        return result

    monkeypatch.setattr(env.runtime.files, "export", revoke_after_copy)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.service.export(
            env.actor, report["id"], models.Export(request_key="revoked", format="txt")
        )
    item = env.service.detail(report["id"])["exports"][0]
    assert item["local_export"]["state"] == "FAILED"
    assert item["local_export"]["error_code"] == "SESSION_EXPIRED"
    path = env.runtime.root.resolve_key(item["local_export"]["relative_key"])
    before = path.read_bytes()
    monkeypatch.setattr(exports, "render", no_render)
    monkeypatch.setattr(
        env.runtime.files, "export", lambda *args: pytest.fail("Matching copy must be reused")
    )
    recovered = env.service.export(
        other_admin, report["id"], models.Export(request_key="other-admin", format="txt")
    )
    assert recovered["local_export"]["state"] == "READY"
    assert path.read_bytes() == before and recovered["file_id"] == item["file_id"]
    assert env.source.calls == 1 and count(env.runtime, FILES) == 1


def test_real_backup_restore_recreates_derived_copy_from_preserved_canonical(
    env, tmp_path, monkeypatch
):
    from cafe_fin.core.backup import BackupService

    report = saved(env)
    item = env.service.export(
        env.actor, report["id"], models.Export(request_key="backup-copy", format="txt")
    )
    key = item["local_export"]["relative_key"]
    expected = env.runtime.root.resolve_key(key).read_bytes()
    backup = tmp_path / "synthetic-backup"
    env.runtime.backups.create(backup)
    BackupService.verify(backup)
    restored_root = BackupService.restore(backup, tmp_path / "restored-root")
    assert not restored_root.resolve_key(key).exists()
    runtime = Runtime(restored_root.path, modules=env.registry)
    try:
        service = ReportingService(runtime)
        monkeypatch.setattr(exports, "render", no_render)
        login = runtime.auth.login("reportadmin", "synthetic-report-password")
        actor = runtime.auth.authenticate(login["access_token"])
        result = service.export(
            actor, report["id"], models.Export(request_key="restored-copy", format="txt")
        )
        assert result["id"] == item["id"] and result["file_id"] == item["file_id"]
        assert restored_root.resolve_key(key).read_bytes() == expected
        assert count(runtime, FILES) == count(runtime, EXPORTS) == 1
        assert service.detail(report["id"])["sha256"] == report["sha256"]
        assert env.source.calls == 1
    finally:
        runtime.close()
