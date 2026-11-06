import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting.schedule import list_runs
from cafe_fin.reporting.service import ReportingService
from test_daily_generation import setup_auto


def test_process_crash_after_capture_resumes_frozen_snapshot_next_day_without_source_read(env):
    service, _, _, _ = setup_auto(env)
    env.runtime.close()
    root = Path(__file__).resolve().parents[2]
    code = """
import os, sys
from datetime import datetime, timezone
from cafe_fin.core.modules import ModuleRegistry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from conftest import TypedSyntheticSource
class CrashAfterCapture(ReportingService):
    def preview(self, *args, **kwargs):
        result = super().preview(*args, **kwargs)
        os._exit(41)
runtime = Runtime(sys.argv[1], modules=ModuleRegistry((module_manifest(source=TypedSyntheticSource()),)))
service = CrashAfterCapture(runtime, source=TypedSyntheticSource(),
    clock=lambda: datetime(2026,11,6,11,15,tzinfo=timezone.utc))
service.tick()
raise AssertionError("did not crash")
"""
    process_env = os.environ.copy()
    process_env["PYTHONPATH"] = os.pathsep.join(
        (str(root / "backend"), str(root / "tests/reporting"))
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(env.root)],
        env=process_env,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 41, result.stderr
    runtime = Runtime(env.root, modules=env.registry)
    try:
        # Deliberately UNBOUND sources: any attempted recapture must fail.
        restored = ReportingService(
            runtime, clock=lambda: datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
        )
        restored.recover()
        assert restored.tick()["generation"]["state"] == "COMPLETED"
        reports = restored.list("reports")
        assert reports["total"] == 1 and reports["items"][0]["version"] == 1
        report = restored.detail(reports["items"][0]["id"])
        assert report["state"] == "SAVED" and report["from_on"] == "2026-11-06"
        assert report["snapshot"]["cutoff"] == "2026-11-06T11:15:00+00:00"
        assert restored.list("deliveries")["total"] == 1
        assert list_runs(restored)["items"][0]["state"] == "COMPLETED"
        restored.tick()
        assert restored.list("reports")["total"] == restored.list("deliveries")["total"] == 1
    finally:
        runtime.close()
