"""Real core timer, SQLite and process recovery; no UI and no real network."""

import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleManifest, ModuleRegistry
from cafe_fin.core.periodic import PeriodicTask
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.sender import dispatch_one
from cafe_fin.reporting.service import ReportingService

from tests.reporting.conftest import TypedSyntheticSource, configure, saved


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("Expected reporting lifecycle result before bounded deadline")


def test_real_production_60_second_timer_generates_without_ui_while_job_worker_is_busy(tmp_path):
    source = TypedSyntheticSource()
    captured_by = []
    entered, release = threading.Event(), threading.Event()

    def actor_source(runtime, actor):
        captured_by.append((threading.current_thread().name, actor.id))
        return source

    def busy_import(context, payload):
        entered.set()
        assert release.wait(80)
        context.finalize(lambda conn: {"released": True})

    reporting = module_manifest(actor_source_factory=actor_source, heartbeat_bound=False)
    assert reporting.periodic_tasks["reporting.tick"].interval_seconds == 60
    registry = ModuleRegistry(
        (
            reporting,
            ModuleManifest(
                "sample", "/sample", job_handlers={"sample.parse": JobHandler(busy_import)}
            ),
        )
    )
    runtime = Runtime(tmp_path / "actual-periodic", initialize=True, modules=registry)
    service = ReportingService(runtime)
    auth = runtime.auth.setup("periodicadmin", "synthetic-periodic-password")
    actor = runtime.auth.authenticate(auth["access_token"])
    service.update_settings(
        actor,
        models.DeliverySettings(
            request_key="auto",
            expected_version=0,
            enabled=True,
            auto_generate_daily=True,
            send_at="00:00",
            daily_export_formats=["txt"],
            daily_book_ids=["cash"],
        ),
    )
    runtime.jobs.submit(actor.id, "sample.parse", {}, "busy")
    try:
        assert service.public_settings()["scheduler_status"]["state"] == "NEW"
        started = time.monotonic()
        runtime.start()
        assert entered.wait(5)
        assert service.list("reports")["total"] == 0
        until(lambda: runtime.periodic.status()["runs"]["reporting.tick"] >= 1, 70)
        assert time.monotonic() - started >= 59
        assert not release.is_set()
        status = service.public_settings()["scheduler_status"]
        assert status["registered"] and status["running"] and not status["error_code"]
        assert status["runs"] == 1 and status["failures"] == 0
        report = service.list("reports")["items"][0]
        assert report["state"] == "SAVED" and report["version"] == 1
        assert len(service.detail(report["id"])["exports"]) == 1
        assert service.list("deliveries")["items"][0]["state"] == "UNCONFIGURED"
        assert captured_by == [("cafe-fin-periodic", actor.id)]
    finally:
        release.set()
        runtime.close()
    assert not runtime.periodic.status()["running"]
    assert runtime.periodic.status()["state"] == "STOPPED"
    reopened = Runtime(tmp_path / "actual-periodic", modules=registry)
    try:
        reopened.start()
        restored = ReportingService(reopened)
        assert restored.list("reports")["total"] == restored.list("deliveries")["total"] == 1
        assert source.calls == 1
    finally:
        reopened.close()


def test_legacy_heartbeat_flag_cannot_claim_unregistered_timer(tmp_path):
    manifest = replace(module_manifest(), periodic_tasks={})
    runtime = Runtime(tmp_path / "unbound", initialize=True, modules=ModuleRegistry((manifest,)))
    try:
        settings = ReportingService(runtime, heartbeat_bound=True).public_settings()
        assert settings["scheduler_mode"] == "MANUAL"
        assert settings["scheduler_status"] == {
            "registered": False,
            "state": "UNBOUND",
            "running": False,
            "active": False,
            "error_code": None,
            "last_error_code": None,
            "task_error_code": None,
            "runs": 0,
            "failures": 0,
        }
    finally:
        runtime.close()


def test_timer_errors_are_sanitized_visible_and_next_tick_recovers(tmp_path, monkeypatch):
    original = ReportingService.tick
    calls = []

    def flaky(self, now=None):
        if threading.current_thread().name == "cafe-fin-periodic":
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("PRIVATE-token path C:/private/account")
        return original(self, now)

    monkeypatch.setattr(ReportingService, "tick", flaky)
    manifest = module_manifest()
    task = manifest.periodic_tasks["reporting.tick"]
    manifest = replace(manifest, periodic_tasks={"reporting.tick": PeriodicTask(task.run, 1)})
    runtime = Runtime(tmp_path / "errors", initialize=True, modules=ModuleRegistry((manifest,)))
    service = ReportingService(runtime)
    try:
        runtime.start()
        until(lambda: runtime.periodic.status()["runs"]["reporting.tick"] == 1)
        failed = service.public_settings()["scheduler_status"]
        assert failed["error_code"] == failed["task_error_code"] == "PERIODIC_TASK_FAILED"
        assert failed["last_error_code"] == "PERIODIC_TASK_FAILED"
        assert "PRIVATE" not in str(failed) and "C:/" not in str(failed)
        until(lambda: runtime.periodic.status()["runs"]["reporting.tick"] >= 2)
        recovered = service.public_settings()["scheduler_status"]
        assert recovered["error_code"] is recovered["task_error_code"] is None
        assert recovered["last_error_code"] == "PERIODIC_TASK_FAILED"
        assert recovered["failures"] == 1
    finally:
        runtime.close()


def test_killed_process_during_timer_send_recovers_unknown_without_resend(env, tmp_path):
    configure(env)
    report = saved(env)
    env.service.enqueue(env.actor, report["id"], models.Enqueue(request_key="periodic-queue"))
    env.runtime.close()
    proof = tmp_path / "synthetic-periodic-effect.txt"
    code = r"""
import os, sys, time, threading
from dataclasses import replace
from pathlib import Path
from cafe_fin.core.jobs import JobHandler
from cafe_fin.core.modules import ModuleRegistry, ModuleManifest
from cafe_fin.core.periodic import PeriodicTask
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from tests.reporting.conftest import SyntheticSource, MemorySecrets, FakeTransport, BOT_TOKEN
class BlockAfterEffect(FakeTransport):
    def send_text(self, token, group, text, bot_id):
        with Path(sys.argv[2]).open("x", encoding="utf-8") as stream:
            stream.write(threading.current_thread().name)
            stream.flush()
            os.fsync(stream.fileno())
        threading.Event().wait(90)
        return "not-observed-receipt"
source, secrets, transport = SyntheticSource(), MemorySecrets(), BlockAfterEffect()
manifest = module_manifest(source=source, secret_store=secrets, transport=transport)
task = manifest.periodic_tasks['reporting.tick']
manifest = replace(manifest, periodic_tasks={'reporting.tick':PeriodicTask(task.run, 1)})
def busy(context, payload):
    threading.Event().wait(90)
registry = ModuleRegistry((manifest, ModuleManifest('sample','/sample',job_handlers={'sample.parse':JobHandler(busy)})))
runtime = Runtime(sys.argv[1], modules=registry)
service = ReportingService(runtime, secret_store=secrets)
secrets.put(service.secret_key(service.settings()), {'bot_token': BOT_TOKEN})
runtime.jobs.submit('synthetic-actor','sample.parse',{},'busy-before-timer')
runtime.start()
threading.Event().wait(90)
"""
    root = Path(__file__).resolve().parents[2]
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = os.pathsep.join((str(root / "backend"), str(root)))
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(env.root), str(proof)],
        cwd=root,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        until(proof.exists, 15)
        assert proof.read_text() == "cafe-fin-periodic"
    finally:
        child.kill()
        _, error = child.communicate(timeout=10)
    assert child.returncode != 0, error
    runtime = Runtime(env.root, modules=env.registry)
    try:
        runtime.start()
        restored = ReportingService(runtime, secret_store=env.secrets, transport=env.transport)
        item = restored.list("deliveries")["items"][0]
        assert item["state"] == "UNKNOWN" and item["message_id"] is None

        def idle_after_startup():
            state = dispatch_one(restored)["state"]
            # The finite startup job may briefly own the singleton sender lock.
            assert state in {"BUSY", "IDLE"}
            return state == "IDLE"

        until(idle_after_startup)
        assert restored.list("deliveries")["items"][0]["state"] == "UNKNOWN"
        assert not env.transport.texts
        assert restored.list("reports")["total"] == restored.list("deliveries")["total"] == 1
    finally:
        runtime.close()
