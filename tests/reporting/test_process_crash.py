"""Real process death after a fake outbound side effect; never contacts Zalo."""

import os
import subprocess
import sys
from pathlib import Path

from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting.models import Enqueue
from cafe_fin.reporting.sender import dispatch_one
from cafe_fin.reporting.service import ReportingService

from tests.reporting.conftest import configure, saved


def test_process_dies_after_transport_send_restart_is_unknown_not_sent_or_retried(env, tmp_path):
    configure(env)
    report = saved(env)
    env.service.enqueue(env.actor, report["id"], Enqueue(request_key="queue"))
    env.runtime.close()
    proof = tmp_path / "synthetic-transport-effect.txt"
    code = """
import os, sys, time
from pathlib import Path
from cafe_fin.core.runtime import Runtime
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.sender import dispatch_one
from tests.reporting.conftest import SyntheticSource, MemorySecrets, FakeTransport
class CrashTransport(FakeTransport):
    def send_text(self, token, group, text):
        with Path(sys.argv[2]).open("x", encoding="utf-8") as stream:
            stream.write("synthetic-send-accepted-but-no-receipt")
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(37)
source, store, transport = SyntheticSource(), MemorySecrets(), CrashTransport()
registry = ModuleRegistry((module_manifest(source=source, secret_store=store, transport=transport),))
runtime = Runtime(sys.argv[1], modules=registry)
service = ReportingService(runtime, source=source, secret_store=store, transport=transport)
store.put(service.secret_key(service.settings()), {"app_id":"demo", "app_secret":"SYNTHETIC",
    "refresh_token":"SYNTHETIC", "access_token":"SYNTHETIC", "expires_at":int(time.time())+90000})
dispatch_one(service)
raise AssertionError("transport did not exit")
"""
    root = Path(__file__).resolve().parents[2]
    process_env = os.environ.copy()
    process_env["PYTHONPATH"] = os.pathsep.join((str(root / "backend"), str(root)))
    child = subprocess.run(
        [sys.executable, "-c", code, str(env.root), str(proof)],
        cwd=root,
        env=process_env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 37, child.stderr
    assert proof.read_text() == "synthetic-send-accepted-but-no-receipt"
    runtime = Runtime(env.root, modules=env.registry)
    try:
        service = ReportingService(
            runtime, source=env.source, secret_store=env.secrets, transport=env.transport
        )
        service.recover()
        item = service.list("deliveries")["items"][0]
        assert item["state"] == "UNKNOWN" and item["message_id"] is None
        assert dispatch_one(service)["state"] == "IDLE"
        assert not env.transport.texts
    finally:
        runtime.close()
