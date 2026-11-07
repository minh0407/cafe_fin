import ctypes
import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cafe_fin.core import secrets
from cafe_fin.core.errors import CoreError
from cafe_fin.core.secrets import MAX_CREDENTIAL_BYTES, WindowsCredentialStore


def key():
    return f"cafe_fin/reporting/{uuid.uuid4()}/test-{uuid.uuid4().hex}"


def same(actual, expected):
    if actual != expected:
        raise AssertionError("Credential mismatch; contents intentionally omitted")


@pytest.fixture
def windows_store():
    if sys.platform != "win32":
        pytest.skip("Real Windows Credential Manager requires Windows")
    store, target_key = WindowsCredentialStore(), key()
    assert store.available
    assert not store.has(target_key)
    try:
        yield store, target_key
    finally:
        # Only the exact unique key owned by this fixture. Never enumerate credentials.
        store.delete(target_key)
        assert store.get(target_key) is None


@pytest.mark.parametrize(
    "target_key",
    [
        "Microsoft:unrelated",
        "CafeFin:reporting:v1:anything",
        "cafe_fin/reporting/not-a-uuid/oa",
        f"cafe_fin/reporting/{uuid.uuid4()}/../oa",
        f"cafe_fin/reporting/{uuid.uuid4()}/oa/extra",
        f"cafe_fin/reporting/{uuid.uuid4()}/oa\x00suffix",
        f"cafe_fin/reporting/{uuid.uuid4()}/",
        f"cafe_fin/reporting/{str(uuid.uuid4()).upper()}/oa",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/0",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/0123",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/-123",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/{2**52}",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/123:token",
        f"cafe_fin/reporting/{uuid.uuid4()}/telegram/123/extra",
        f"cafe_fin/reporting/{uuid.uuid4()}/other/123",
    ],
)
def test_rejects_other_namespaces_before_accessing_os(target_key):
    store = WindowsCredentialStore()
    for operation in (
        lambda: store.has(target_key),
        lambda: store.get(target_key),
        lambda: store.put(target_key, {}),
        lambda: store.delete(target_key),
    ):
        with pytest.raises(CoreError, match="SECRET_KEY_INVALID"):
            operation()


def test_target_is_scoped_hashed_and_deterministic():
    target_key = key()
    target = secrets._target_for(target_key)
    assert target.startswith("CafeFin:reporting:v1:")
    assert len(target) == len("CafeFin:reporting:v1:") + 64
    assert target == secrets._target_for(target_key)
    assert target != secrets._target_for(key())
    assert target_key not in target


def test_telegram_target_is_separate_from_legacy_and_other_bots():
    root = uuid.uuid4()
    target_key = f"cafe_fin/reporting/{root}/telegram/123456789"
    target = secrets._target_for(target_key)
    assert target.startswith("CafeFin:reporting:telegram:v1:")
    assert len(target) == len("CafeFin:reporting:telegram:v1:") + 64
    assert target == secrets._target_for(target_key)
    assert target != secrets._target_for(f"cafe_fin/reporting/{root}/123456789")
    assert target != secrets._target_for(f"cafe_fin/reporting/{root}/telegram/123456790")
    assert target_key not in target


def test_real_windows_telegram_and_legacy_credentials_are_isolated(windows_store):
    store, legacy_key = windows_store
    root = legacy_key.split("/")[2]
    telegram_key = f"cafe_fin/reporting/{root}/telegram/123456789"
    first = {"access_token": "SYNTHETIC-LEGACY"}
    token = {"bot_token": "123456789:SYNTHETIC-TELEGRAM"}
    assert not store.has(telegram_key)
    try:
        store.put(legacy_key, first)
        store.put(telegram_key, token)
        same(WindowsCredentialStore().get(telegram_key), token)
        same(store.get(legacy_key), first)
        store.delete(telegram_key)
        assert not store.has(telegram_key)
        same(store.get(legacy_key), first)
    finally:
        store.delete(telegram_key)


def test_non_windows_has_no_plaintext_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets.sys, "platform", "linux")
    monkeypatch.chdir(tmp_path)
    store, target_key = WindowsCredentialStore(), key()
    assert not store.available
    assert not store.has(target_key)
    assert store.get(target_key) is None
    for operation in (
        lambda: store.put(target_key, {"access_token": "SYNTHETIC"}),
        lambda: store.delete(target_key),
    ):
        with pytest.raises(CoreError, match="SECRET_STORE_UNAVAILABLE"):
            operation()
    assert list(tmp_path.iterdir()) == []


def test_real_windows_roundtrip_replace_and_exact_delete(windows_store):
    store, target_key = windows_store
    first = {"access_token": "SYNTHETIC-A", "refresh_token": "SYNTHETIC-R", "note": "Tiếng Việt"}
    second = {"access_token": "SYNTHETIC-B", "refresh_token": "SYNTHETIC-S", "expires_at": 123}
    store.put(target_key, first)
    assert store.has(target_key)
    same(WindowsCredentialStore().get(target_key), first)
    store.put(target_key, second)
    same(store.get(target_key), second)
    # Deleting twice is idempotent and never selects targets by wildcard/prefix.
    store.delete(target_key)
    store.delete(target_key)
    assert not store.has(target_key)


def test_real_windows_byte_limit_and_invalid_write_preserve_previous(windows_store):
    store, target_key = windows_store
    overhead = len(json.dumps({"token": ""}, separators=(",", ":")).encode("utf-8"))
    boundary = {"token": "x" * (MAX_CREDENTIAL_BYTES - overhead)}
    store.put(target_key, boundary)
    same(store.get(target_key), boundary)
    rejected = [
        ({"token": boundary["token"] + "x"}, "SECRET_VALUE_TOO_LARGE"),
        ({"token": "ệ" * 1000}, "SECRET_VALUE_TOO_LARGE"),
        ({"token": float("nan")}, "SECRET_VALUE_INVALID"),
        ({"token": object()}, "SECRET_VALUE_INVALID"),
        ({1: "synthetic"}, "SECRET_VALUE_INVALID"),
        ([], "SECRET_VALUE_INVALID"),
    ]
    for value, code in rejected:
        with pytest.raises(CoreError, match=code) as error:
            store.put(target_key, value)
        assert error.value.details == {}
        same(store.get(target_key), boundary)


def test_real_windows_concurrent_readers_see_complete_token_pairs(windows_store):
    store, target_key = windows_store

    def pair(tag):
        return {"generation": tag, "access_token": tag + "-a", "refresh_token": tag + "-r"}

    store.put(target_key, pair("initial"))
    barrier = threading.Barrier(4)

    def writer(name):
        independent = WindowsCredentialStore()
        barrier.wait(timeout=10)
        for index in range(20):
            independent.put(target_key, pair(f"{name}-{index}"))

    def reader():
        independent = WindowsCredentialStore()
        barrier.wait(timeout=10)
        for _ in range(80):
            current = independent.get(target_key)
            if current is None:
                raise AssertionError("Credential was absent during concurrent replacement")
            if not current or current != pair(current["generation"]):
                raise AssertionError("Observed an incomplete credential pair; contents omitted")

    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(writer, "one"), pool.submit(writer, "two")]
        tasks += [pool.submit(reader), pool.submit(reader)]
        for task in tasks:
            task.result(timeout=30)


def test_real_windows_os_failure_is_sanitized_and_keeps_existing_value(windows_store, monkeypatch):
    store, target_key = windows_store
    original = {"access_token": "SYNTHETIC-OLD", "refresh_token": "SYNTHETIC-OLD-R"}
    store.put(target_key, original)

    def failure(*_args):
        ctypes.set_last_error(5)
        return 0

    with monkeypatch.context() as patch:
        patch.setattr(store._api, "write", failure)
        with pytest.raises(CoreError, match="SECRET_STORE_UNAVAILABLE") as error:
            store.put(target_key, {"access_token": "SYNTHETIC-NEW"})
        assert error.value.details == {}
        assert "SYNTHETIC" not in str(error.value.envelope("synthetic-request"))
        same(store.get(target_key), original)
    with monkeypatch.context() as patch:
        patch.setattr(store._api, "read", failure)
        with pytest.raises(CoreError, match="SECRET_STORE_UNAVAILABLE"):
            store.has(target_key)
    with monkeypatch.context() as patch:
        patch.setattr(store._api, "delete", failure)
        with pytest.raises(CoreError, match="SECRET_STORE_UNAVAILABLE"):
            store.delete(target_key)
    same(store.get(target_key), original)


def test_real_windows_mutex_timeout_keeps_previous_value(windows_store, monkeypatch):
    store, target_key = windows_store
    original = {"access_token": "SYNTHETIC-OLD", "refresh_token": "SYNTHETIC-OLD-R"}
    store.put(target_key, original)
    with monkeypatch.context() as patch:
        patch.setattr(store._api, "wait", lambda *_args: 258)
        with pytest.raises(CoreError, match="SECRET_STORE_BUSY"):
            store.put(target_key, {"access_token": "SYNTHETIC-NEW"})
    same(store.get(target_key), original)
