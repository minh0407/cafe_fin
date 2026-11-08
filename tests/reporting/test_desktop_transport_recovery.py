"""Full-registry restart with test-only Telegram transport and memory credentials.

These are source integration cases, not frozen/tray or live Telegram evidence.
Production source bridges, migrations, startup hooks and timer registration stay.
"""

import hashlib
from uuid import uuid4

import pytest
from cafe_fin import registry
from cafe_fin.core.runtime import Runtime
from cafe_fin.reporting import models, sender
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram import DeliveryError

from tests.reporting.conftest import BOT_TOKEN, CHAT_ID, FakeTransport, MemorySecrets
from tests.reporting.native_probe import until


@pytest.mark.parametrize(
    "outcome", ["sent", "timeout_text", "timeout_document", "offline_preflight"]
)
def test_full_registry_startup_preserves_receipts_unknown_and_local_files(
    tmp_path, monkeypatch, outcome
):
    monkeypatch.setenv("CAFE_FIN_MARKET_NETWORK", "0")
    transport, secrets = FakeTransport(), MemorySecrets()
    reporting_manifest = registry.reporting_manifest

    def injected_reporting(**kwargs):
        return reporting_manifest(**{**kwargs, "secret_store": secrets, "transport": transport})

    monkeypatch.setattr(registry, "reporting_manifest", injected_reporting)
    root = tmp_path / "Synthetic desktop transport"

    def service(runtime):
        return ReportingService(
            runtime,
            actor_source_factory=registry._report_sources,
            secret_store=secrets,
            transport=transport,
        )

    def drain_startup(runtime, actor):
        job = runtime.jobs.submit(
            actor.id, "foundation.sample", {}, "startup-barrier-" + str(uuid4())
        )
        until(lambda: runtime.jobs.status(job["job_id"])["state"] == "COMPLETED")

    runtime = Runtime(root, initialize=True)
    try:
        assert set(runtime.periodic.tasks) == {"records.market", "reporting.tick"}
        assert runtime.periodic.tasks["records.market"].interval_seconds == 10
        assert runtime.periodic.tasks["reporting.tick"].interval_seconds == 60
        actor = runtime.auth.authenticate(
            runtime.auth.setup("desktop-transport", "synthetic-desktop-password")["access_token"]
        )
        reports = service(runtime)
        reports.update_settings(
            actor,
            models.DeliverySettings(
                request_key="config",
                expected_version=0,
                enabled=True,
                chat_id=CHAT_ID,
                send_at="00:00",
                attachments_enabled=True,
            ),
        )
        reports.set_credentials(actor, models.Credentials(bot_token=BOT_TOKEN))
        assert sender.check_connection(reports, actor)["state"] == "CONNECTED"
        if outcome == "timeout_text":
            transport.send_error = DeliveryError("TELEGRAM_NETWORK_ERROR", unknown=True)
        elif outcome == "timeout_document":
            transport.file_error = DeliveryError("TELEGRAM_NETWORK_ERROR", unknown=True)
        elif outcome == "offline_preflight":
            transport.verify_error = DeliveryError("TELEGRAM_NETWORK_ERROR")
        # Save and all three exports still work after test WAN failure is armed.
        preview = reports.preview(
            actor,
            models.Preview(request_key="preview", from_on="2026-11-06", through_on="2026-11-06"),
        )
        report = reports.save(
            actor,
            preview["id"],
            models.Save(request_key="save", expected_version=preview["version"]),
        )
        exports = [
            reports.export(actor, report["id"], models.Export(request_key=format, format=format))
            for format in ("pdf", "xlsx", "txt")
        ]
        pins = {item["local_export"]["relative_key"]: item["sha256"] for item in exports}
        item = reports.enqueue(
            actor,
            report["id"],
            models.Enqueue(request_key="queue", attachment_export_id=exports[0]["id"]),
        )
        assert item["state"] == "WAITING"
        runtime.start()  # Exactly the production startup dispatch; no manual first tick.
        drain_startup(runtime, actor)
        prior = reports.list("deliveries")["items"][0]
        expected = (
            "SENT"
            if outcome == "sent"
            else "FAILED"
            if outcome == "offline_preflight"
            else "UNKNOWN"
        )
        assert prior["state"] == expected
        assert prior["message_id"] == ("101" if outcome in {"sent", "timeout_document"} else None)
        assert prior["message_chat_id"] == (CHAT_ID if prior["message_id"] else None)
        assert prior["file_message_id"] == ("102" if outcome == "sent" else None)
        assert prior["file_message_chat_id"] == (CHAT_ID if outcome == "sent" else None)
        assert len(transport.texts) == (0 if outcome == "offline_preflight" else 1)
        assert len(transport.files) == (1 if outcome in {"sent", "timeout_document"} else 0)
        assert reports.detail(report["id"])["state"] == "SAVED"
    finally:
        runtime.close()

    # Network comes back after exit. Unknown POSTs and acknowledged receipts must
    # not be sent again by either reopen catch-up or the next timer callback.
    transport.send_error = transport.file_error = transport.verify_error = None
    effects = (len(transport.texts), len(transport.files), len(transport.verifications))
    runtime = Runtime(root)
    try:
        runtime.start()
        drain_startup(runtime, actor)
        for _ in range(2):
            runtime.periodic.tasks["reporting.tick"].run(runtime)
        restored = service(runtime)
        assert restored.list("deliveries")["items"][0] == prior
        assert restored.list("reports")["total"] == restored.list("deliveries")["total"] == 1
        assert (len(transport.texts), len(transport.files), len(transport.verifications)) == effects
        for relative_key, sha256 in pins.items():
            assert hashlib.sha256((root / relative_key).read_bytes()).hexdigest() == sha256
    finally:
        runtime.close()
