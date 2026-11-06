"""Reporting integration with genuine Windows Credential Manager; fake WAN only."""

import json
import sys

import pytest
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.secrets import WindowsCredentialStore
from cafe_fin.reporting import models
from cafe_fin.reporting.sender import dispatch_one
from cafe_fin.reporting.service import ReportingService
from conftest import configure, saved
from sqlalchemy import select


@pytest.mark.skipif(sys.platform != "win32", reason="Genuine Windows credential test")
def test_reporting_admin_credentials_refresh_atomic_pair_and_cleanup_real_os_store(env):
    configure(env)
    store = WindowsCredentialStore()
    assert store.available
    service = ReportingService(
        env.runtime, source=env.source, secret_store=store, transport=env.transport
    )
    key = service.secret_key(service.settings())
    assert not store.has(key)
    try:
        command = models.Credentials(
            app_id="demo-app",
            app_secret="SYNTHETIC-WINDOWS-SECRET",
            refresh_token="SYNTHETIC-WINDOWS-REFRESH",
        )
        service.set_credentials(env.actor, command)
        assert service.public_settings()["credential_configured"]
        original = store.get(key)
        with pytest.raises(CoreError, match="SECRET_VALUE_TOO_LARGE"):
            service.set_credentials(
                env.actor,
                models.Credentials(
                    app_id="demo-app",
                    app_secret="SYNTHETIC-WINDOWS-SECRET",
                    refresh_token="x" * 3000,
                ),
            )
        assert store.get(key) == original  # rejected replacement preserves old pair
        row = saved(env)
        service.enqueue(env.actor, row["id"], models.Enqueue(request_key="windows-queue"))
        result = dispatch_one(service)  # injected fake transport, never real Zalo
        assert result["state"] == "SENT" and result["message_id"] == "text-receipt"
        replacement = WindowsCredentialStore().get(key)
        assert replacement["access_token"] == "SYNTHETIC-access-rotated"
        assert replacement["refresh_token"] == "SYNTHETIC-refresh-rotated"
        assert replacement["refresh_state"] == "READY"
        with env.runtime.reader() as conn:
            data = json.dumps([list(x) for x in conn.execute(select(REQUESTS))])
            data += json.dumps([list(x) for x in conn.execute(select(AUDIT))])
        assert "SYNTHETIC-WINDOWS-SECRET" not in data
        assert "SYNTHETIC-WINDOWS-REFRESH" not in data
        assert "SYNTHETIC-access-rotated" not in data
    finally:
        store.delete(key)  # exact random data-root test key only, never enumerate
    assert not store.has(key)
