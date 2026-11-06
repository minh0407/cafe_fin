"""Explicit report sharing grants summary exports, never arbitrary source files."""

import hashlib
import io
from contextlib import contextmanager
from dataclasses import replace

import pytest
from cafe_fin.core.api import create_app
from cafe_fin.core.errors import CoreError
from cafe_fin.core.storage import FILES
from cafe_fin.reporting import models
from conftest import saved
from fastapi.testclient import TestClient
from sqlalchemy import func, select

SESSION = "synthetic-report-download-0123456789abcdef"


def user(env, name, role="operator"):
    env.runtime.auth.create_user(
        env.actor,
        username=name,
        password="synthetic-download-password",
        role=role,
        request_key="create-" + name,
    )
    login = env.runtime.auth.login(name, "synthetic-download-password")
    return env.runtime.auth.authenticate(login["access_token"]), {
        "X-App-Session": SESSION,
        "Origin": "http://tauri.localhost",
        "Authorization": "Bearer " + login["access_token"],
    }


def url(report, exported):
    return f"/api/v1/reporting/reports/{report['id']}/exports/{exported['id']}/content"


def client_for(env):
    return TestClient(
        create_app(env.runtime, SESSION, port=48961), base_url="http://127.0.0.1:48961"
    )


def exported(env, format="txt"):
    report = saved(env)
    item = env.service.export(
        env.actor, report["id"], models.Export(request_key="export", format=format)
    )
    return report, item


def test_operator_cross_actor_retry_has_one_file_and_shared_route_while_generic_is_private(
    env, monkeypatch
):
    actor_a, headers_a = user(env, "downloadusera")
    actor_b, headers_b = user(env, "downloaduserb")
    report = saved(env)
    command = env.service.command

    def fail_receipt(actor, action, *args, **kwargs):
        if action == "export":
            raise CoreError("SYNTHETIC_RECEIPT_FAILURE", "Synthetic failure", 503)
        return command(actor, action, *args, **kwargs)

    monkeypatch.setattr(env.service, "command", fail_receipt)
    with pytest.raises(CoreError, match="SYNTHETIC_RECEIPT_FAILURE"):
        env.service.export(actor_a, report["id"], models.Export(request_key="a", format="txt"))
    monkeypatch.setattr(env.service, "command", command)
    item = env.service.export(actor_b, report["id"], models.Export(request_key="b", format="txt"))
    with env.runtime.reader() as conn:
        assert conn.execute(select(func.count()).select_from(FILES)).scalar_one() == 1
    with client_for(env) as client:
        for headers in (headers_a, headers_b):
            response = client.get(url(report, item), headers=headers)
            assert response.status_code == 200, response.text
            assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
            assert int(response.headers["content-length"]) == item["size"]
            assert response.headers["x-content-sha256"] == item["sha256"]
            assert (
                response.headers["content-disposition"]
                == 'attachment; filename="CafeFin-tong-hop.txt"'
            )
            assert response.headers["cache-control"] == "no-store"
            for suffix in ("", "/content"):
                generic = client.get(f"/api/v1/files/{item['file_id']}{suffix}", headers=headers)
                assert generic.status_code == 403, generic.text


@pytest.mark.parametrize("format", ["pdf", "xlsx"])
def test_binary_formats_have_verified_hash_and_correct_media_type(env, format):
    report, item = exported(env, format)
    _, headers = user(env, "binaryreader")
    with client_for(env) as client:
        response = client.get(url(report, item), headers=headers)
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == item["sha256"]
        assert response.headers["content-type"].startswith("application/")
        assert response.content.startswith(b"%PDF" if format == "pdf" else b"PK")


def test_other_report_export_and_raw_private_source_id_do_not_grant_access(env, monkeypatch):
    report, item = exported(env)
    second = saved(env, "other", reason="Synthetic new version")
    private = env.runtime.files.put(
        io.BytesIO(b"PRIVATE-synthetic-book-source"),
        category="workbooks",
        original_name="synthetic.xlsx",
        actor=env.actor.id,
        request_key="private-source",
    )
    _, headers = user(env, "guessedreader")

    def no_read(*args):
        raise AssertionError("Unmatched domain reference must not open any file")

    monkeypatch.setattr(env.runtime.files, "read", no_read)
    with client_for(env) as client:
        for path in (url(second, item), url(report, {"id": private.id})):
            response = client.get(path, headers=headers)
            assert response.status_code == 404
            assert "x-content-sha256" not in response.headers
        assert client.get(f"/api/v1/files/{private.id}/content", headers=headers).status_code == 403


@pytest.mark.parametrize("change", ["disable", "demote"])
def test_account_change_during_byte_hash_is_denied_before_headers_and_closes_source(
    env, monkeypatch, change
):
    report, item = exported(env)
    principal, headers = user(env, "revokedreader", "admin" if change == "demote" else "operator")
    original = env.runtime.files.read
    sources = []

    class ChangingReader:
        changed = False

        def __init__(self, source):
            self.source = source

        def read(self, size):
            value = self.source.read(size)
            if value and not self.changed:
                self.changed = True
                env.runtime.auth.update_user(
                    env.actor,
                    principal.id,
                    role="operator",
                    active=change != "disable",
                    expected_version=principal.version,
                    request_key="revoke-reader",
                )
            return value

    @contextmanager
    def revoke_during_hash(file_id):
        with original(file_id) as source:
            sources.append(source)
            yield ChangingReader(source)

    monkeypatch.setattr(env.runtime.files, "read", revoke_during_hash)
    with client_for(env) as client:
        response = client.get(url(report, item), headers=headers)
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == "SESSION_EXPIRED"
        assert "x-content-sha256" not in response.headers
        assert "content-disposition" not in response.headers
        assert sources and all(source.closed for source in sources)


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_file_is_409_before_download_headers(env, damage):
    report, item = exported(env)
    _, headers = user(env, "damagereader")
    stored = env.runtime.files.get(item["file_id"])
    path = env.runtime.root.resolve_key(stored.relative_key)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"corrupted-synthetic-export")
    with client_for(env) as client:
        response = client.get(url(report, item), headers=headers)
        assert response.status_code == 409
        assert "x-content-sha256" not in response.headers
        assert "content-disposition" not in response.headers


def test_actual_outgoing_bytes_are_hashed_even_after_filestore_verification(env, monkeypatch):
    report, item = exported(env)
    _, headers = user(env, "bytereader")
    original = env.runtime.files.read
    sources = []

    class ChangedBytes:
        def __init__(self, source):
            self.source = source

        def read(self, size):
            value = self.source.read(size)
            return bytes([value[0] ^ 1]) + value[1:] if value else value

    @contextmanager
    def change_verified_bytes(file_id):
        with original(file_id) as source:
            sources.append(source)
            yield ChangedBytes(source)

    monkeypatch.setattr(env.runtime.files, "read", change_verified_bytes)
    with client_for(env) as client:
        response = client.get(url(report, item), headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "REPORT_EXPORT_UNAVAILABLE"
        assert "x-content-sha256" not in response.headers
        assert all(source.closed for source in sources)


def test_saved_reference_metadata_is_checked_before_read_and_rechecked_after_hash(env, monkeypatch):
    report, item = exported(env)
    _, headers = user(env, "metadatareader")
    original_get, original_read = env.runtime.files.get, env.runtime.files.read
    changed = False

    def get_changed(file_id, **kwargs):
        record = original_get(file_id, **kwargs)
        return replace(record, category="workbooks") if changed else record

    @contextmanager
    def change_after_read(file_id):
        nonlocal changed
        with original_read(file_id) as source:
            yield source
        changed = True

    monkeypatch.setattr(env.runtime.files, "get", get_changed)
    monkeypatch.setattr(env.runtime.files, "read", change_after_read)
    with client_for(env) as client:
        response = client.get(url(report, item), headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "REPORT_EXPORT_UNAVAILABLE"
        assert "x-content-sha256" not in response.headers
        # Now the invalid metadata is already present at the first reference check.
        monkeypatch.setattr(
            env.runtime.files, "read", lambda _: pytest.fail("No unauthorized read")
        )
        assert client.get(url(report, item), headers=headers).status_code == 409
