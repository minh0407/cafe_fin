"""Real Windows Credential Manager integration; Telegram WAN remains injected fake."""

import json
import sys

import pytest
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from cafe_fin.core.secrets import WindowsCredentialStore
from cafe_fin.reporting import models
from cafe_fin.reporting.sender import check_connection, dispatch_one
from cafe_fin.reporting.service import ReportingService
from cafe_fin.reporting.telegram_migrations import ATTEMPTS
from sqlalchemy import select

from tests.reporting.conftest import BOT_ID, BOT_TOKEN, CHAT_ID, configure, saved


@pytest.mark.skipif(sys.platform != "win32", reason="Genuine Windows credential test")
def test_reporting_bot_token_real_os_store_namespace_replacement_proof_and_cleanup(env):
    configure(env)
    store = WindowsCredentialStore()
    assert store.available
    service = ReportingService(
        env.runtime,
        source=env.source,
        secret_store=store,
        transport=env.transport,
    )
    config = service.settings()
    root_id = json.loads(
        env.runtime.root.resolve_key(".cafe-fin-root.json").read_text(encoding="utf-8")
    )["root_id"]
    key = service.secret_key(config)
    assert key == f"cafe_fin/reporting/{root_id}/telegram/{BOT_ID}"
    assert not store.has(key)
    replacement_token = BOT_ID + ":" + "B" * 35
    try:
        command = models.Credentials(bot_token=BOT_TOKEN)
        assert BOT_TOKEN not in repr(command)
        service.set_credentials(env.actor, command)
        assert service.public_settings()["credential_configured"]
        assert service.public_settings()["sender_status"] == "UNCONFIGURED"
        assert service.settings()["bot_verified_at"] is None
        original = store.get(key)
        assert original == {"bot_token": BOT_TOKEN}
        assert WindowsCredentialStore().get(key) == original
        assert check_connection(service, env.actor)["state"] == "CONNECTED"
        assert not env.transport.texts and not env.transport.files
        proof = service.settings()["bot_verified_at"]
        with pytest.raises(CoreError, match="SECRET_VALUE_TOO_LARGE"):
            store.put(key, {"bot_token": "x" * 3000})
        assert store.get(key) == original  # Atomic OS rejection preserves old bytes.
        assert service.settings()["bot_verified_at"] == proof
        version = service.settings()["version"]
        service.set_credentials(env.actor, models.Credentials(bot_token=replacement_token))
        assert WindowsCredentialStore().get(key) == {"bot_token": replacement_token}
        assert service.settings()["version"] == version + 1
        assert service.settings()["bot_verified_at"] is None
        assert service.public_settings()["sender_status"] == "UNCONFIGURED"
        row = saved(env)
        item = service.enqueue(env.actor, row["id"], models.Enqueue(request_key="windows-queue"))
        assert item["state"] == "UNCONFIGURED" and item["attempts"] == 0
        assert dispatch_one(service)["state"] == "UNCONFIGURED"
        assert not env.transport.texts and not env.transport.files
        assert check_connection(service, env.actor)["state"] == "CONNECTED"
        service.retry(
            env.actor,
            item["id"],
            models.Retry(request_key="windows-verified", expected_version=item["version"]),
        )
        result = dispatch_one(service)  # Fake Telegram transport, never WAN.
        assert result["state"] == "SENT" and result["message_id"] == "101"
        assert result["message_chat_id"] == CHAT_ID
        assert store.get(key) == {"bot_token": replacement_token}  # No refresh/OAuth mutation.
        with env.runtime.reader() as conn:
            data = json.dumps([list(x) for x in conn.execute(select(REQUESTS))])
            data += json.dumps([list(x) for x in conn.execute(select(AUDIT))])
            data += json.dumps([list(x) for x in conn.execute(select(ATTEMPTS))])
        assert BOT_TOKEN not in data and replacement_token not in data
        assert "bot_token" not in json.dumps(service.public_settings())
    finally:
        store.delete(key)  # Exact random test-root Telegram key only; never enumerate.
    assert not store.has(key)
