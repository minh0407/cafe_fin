"""Attachment ingress ownership and deliberate domain sharing use distinct scopes."""

from contextlib import contextmanager
from uuid import uuid4

import pytest
from cafe_fin.contracts.migrations.v001 import ATTACHMENTS
from cafe_fin.core.db import AUDIT, REQUESTS
from cafe_fin.core.errors import CoreError
from sqlalchemy import select
from test_api import PASSWORD, PREFIX, create, ok, running

PRIVATE_BYTES = b"%PDF-1.7\nsynthetic-private-source-attachment\n%%EOF\n"


@pytest.fixture
def scopes(tmp_path):
    with running(tmp_path / "Attachment scopes") as api:
        api.admin_authorization = api.client.headers["Authorization"]
        api.admin = api.runtime.auth.authenticate(api.admin_authorization[7:])
        api.users = {}
        api.authorizations = {"admin": api.admin_authorization}
        for username in ("source-owner", "other-operator"):
            api.users[username] = ok(
                api.client.post(
                    "/api/v1/users",
                    json={
                        "username": username,
                        "password": PASSWORD,
                        "role": "operator",
                        "request_key": "create-" + username,
                    },
                )
            )
            login = ok(
                api.client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": username,
                        "password": PASSWORD,
                    },
                )
            )
            api.authorizations[username] = "Bearer " + login["access_token"]
        api.contract = create(api)
        yield api


def acting(api, username):
    api.client.headers["Authorization"] = api.authorizations[username]


def upload(api, *, category="documents", filename="synthetic-private.pdf", key="upload"):
    return ok(
        api.client.post(
            "/api/v1/files",
            params={"category": category},
            content=PRIVATE_BYTES,
            headers={
                "X-File-Name": filename,
                "X-Request-Key": key,
                "Content-Type": "application/pdf",
            },
        )
    )


def attach(api, file_id, *, key="attach", contract=None):
    contract = contract or api.contract
    return api.client.post(
        f"{PREFIX}/{contract['id']}/attachments",
        json={
            "request_key": key,
            "file_id": file_id,
            "note": "Synthetic explicitly attached source",
            "status": "user_recorded_signed",
        },
    )


def linked_private_file(api):
    acting(api, "source-owner")
    stored = upload(api)
    acting(api, "admin")
    linked = ok(attach(api, stored["id"], key="admin-explicit-attach"))
    return stored, linked


def domain_path(api, linked, *, contract=None):
    return f"{PREFIX}/{(contract or api.contract)['id']}/attachments/{linked['id']}/content"


def attachment_state(api):
    with api.runtime.reader() as conn:
        return {
            "links": [dict(row) for row in conn.execute(select(ATTACHMENTS)).mappings()],
            "receipts": [
                dict(row)
                for row in conn.execute(
                    select(REQUESTS).where(REQUESTS.c.action == "contracts.attachments.add")
                ).mappings()
            ],
            "audit": [
                dict(row)
                for row in conn.execute(
                    select(AUDIT).where(AUDIT.c.entity == "contracts.attachment")
                ).mappings()
            ],
        }


def denied_without_bytes(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert "synthetic-private-source-attachment" not in response.text
    assert "content-disposition" not in response.headers
    assert "x-content-sha256" not in response.headers


@pytest.mark.parametrize(
    "category,filename",
    [
        ("documents", "synthetic-private.pdf"),
        ("workbooks", "synthetic-private.xlsx"),
    ],
)
def test_foreign_source_attachment_is_denied_before_file_open_without_link_or_receipt(
    scopes, monkeypatch, category, filename
):
    api = scopes
    acting(api, "source-owner")
    stored = upload(api, category=category, filename=filename)
    acting(api, "other-operator")
    before = attachment_state(api)
    opened = []

    def forbid_open(file_id):
        opened.append(file_id)
        raise AssertionError("Foreign source bytes must not be opened")

    monkeypatch.setattr(api.runtime.files, "read", forbid_open)
    response = attach(api, stored["id"])
    denied_without_bytes(response, 403, "PERMISSION_DENIED")
    assert opened == []
    assert attachment_state(api) == before == {"links": [], "receipts": [], "audit": []}


def test_own_source_can_be_attached_and_replayed(scopes):
    api = scopes
    acting(api, "source-owner")
    stored = upload(api)
    linked = ok(attach(api, stored["id"]))
    assert linked["created_by"] == api.users["source-owner"]["id"]
    assert linked["file_id"] == stored["id"]
    assert linked["sha256"] == stored["sha256"]
    assert linked["signature_verification"] == "not_performed"
    assert ok(attach(api, stored["id"])) == linked
    state = attachment_state(api)
    assert len(state["links"]) == len(state["receipts"]) == len(state["audit"]) == 1


def test_admin_explicit_link_shares_domain_bytes_without_sharing_generic_file(scopes):
    api = scopes
    stored, linked = linked_private_file(api)
    acting(api, "other-operator")
    for suffix in ("", "/content"):
        denied_without_bytes(
            api.client.get("/api/v1/files/" + stored["id"] + suffix), 403, "PERMISSION_DENIED"
        )
    response = api.client.get(domain_path(api, linked))
    assert response.status_code == 200, response.text
    assert response.content == PRIVATE_BYTES
    assert response.headers["x-content-sha256"] == stored["sha256"] == linked["sha256"]
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in response.headers["content-disposition"]
    assert ok(api.client.get(f"{PREFIX}/{api.contract['id']}/attachments"))["items"] == [linked]
    # Reading a shared domain link does not grant ownership of its private source.
    denied_without_bytes(
        api.client.get("/api/v1/files/" + stored["id"] + "/content"), 403, "PERMISSION_DENIED"
    )
    assert len(attachment_state(api)["links"]) == 1


@pytest.mark.parametrize("mismatch", ["other_contract", "unknown_contract", "unknown_attachment"])
def test_attachment_domain_download_requires_matching_saved_reference_before_open(
    scopes, monkeypatch, mismatch
):
    api = scopes
    _, linked = linked_private_file(api)
    other_contract = create(api, key="other-contract")
    acting(api, "other-operator")
    if mismatch == "other_contract":
        path = domain_path(api, linked, contract=other_contract)
    elif mismatch == "unknown_contract":
        path = domain_path(api, linked, contract={"id": str(uuid4())})
    else:
        path = domain_path(api, {"id": str(uuid4())})
    opened = []

    def forbid_open(file_id):
        opened.append(file_id)
        raise AssertionError("Unlinked references must not open file bytes")

    monkeypatch.setattr(api.runtime.files, "read", forbid_open)
    denied_without_bytes(api.client.get(path), 404, "NOT_FOUND")
    assert opened == []


@pytest.mark.parametrize(
    "damage,code", [("missing", "FILE_MISSING"), ("modified", "FILE_HASH_MISMATCH")]
)
def test_attachment_domain_verifies_full_file_before_success_headers(scopes, damage, code):
    api = scopes
    stored, linked = linked_private_file(api)
    record = api.runtime.files.get(stored["id"])
    path = api.runtime.root.resolve_key(record.relative_key)
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(PRIVATE_BYTES[:-1] + b"X")
    acting(api, "other-operator")
    denied_without_bytes(api.client.get(domain_path(api, linked)), 409, code)


def test_attachment_writer_revalidates_actor_revoked_after_initial_file_checks(scopes, monkeypatch):
    api = scopes
    acting(api, "source-owner")
    stored = upload(api)
    before = attachment_state(api)
    owner = api.users["source-owner"]
    original_execute = api.runtime.writer.execute
    revoked = False

    def revoke_before_mutation(actor, action, *args, **kwargs):
        nonlocal revoked
        if action == "contracts.attachments.add":
            api.runtime.auth.update_user(
                api.admin,
                owner["id"],
                role="operator",
                active=False,
                expected_version=owner["version"],
                request_key="revoke-attachment-writer",
            )
            revoked = True
        return original_execute(actor, action, *args, **kwargs)

    monkeypatch.setattr(api.runtime.writer, "execute", revoke_before_mutation)
    denied_without_bytes(attach(api, stored["id"]), 401, "SESSION_EXPIRED")
    assert revoked
    assert attachment_state(api) == before


def test_attachment_domain_reauthenticates_after_hash_before_responding(scopes, monkeypatch):
    api = scopes
    stored, linked = linked_private_file(api)
    acting(api, "other-operator")
    reader = api.users["other-operator"]
    original_read = api.runtime.files.read
    verified = []

    @contextmanager
    def revoke_during_file_verification(file_id):
        with original_read(file_id) as source:
            verified.append(file_id)
            api.runtime.auth.update_user(
                api.admin,
                reader["id"],
                role="operator",
                active=False,
                expected_version=reader["version"],
                request_key="revoke-domain-reader",
            )
            yield source

    monkeypatch.setattr(api.runtime.files, "read", revoke_during_file_verification)
    denied_without_bytes(api.client.get(domain_path(api, linked)), 401, "SESSION_EXPIRED")
    assert verified == [stored["id"]]


def test_idempotent_attachment_replay_rechecks_owner_acl_in_writer_transaction(scopes, monkeypatch):
    api = scopes
    acting(api, "source-owner")
    stored = upload(api)
    linked = ok(attach(api, stored["id"]))
    before = attachment_state(api)
    original_authorize = api.runtime.auth.authorize
    original_acl = api.runtime.files.require_owner_or_admin
    events = []
    checks = []

    def tracked_authorize(conn, actor, permission):
        current = original_authorize(conn, actor, permission)
        events.append(("authorized", id(conn), current.id, permission))
        return current

    def changed_acl_inside_writer(conn, actor, file_id):
        assert events[-1] == ("authorized", id(conn), actor.id, "contracts.write")
        checks.append(id(conn))
        if len(checks) == 2:
            raise CoreError("PERMISSION_DENIED", "Synthetic ownership denial at writer", 403)
        return original_acl(conn, actor, file_id)

    monkeypatch.setattr(api.runtime.auth, "authorize", tracked_authorize)
    monkeypatch.setattr(api.runtime.files, "require_owner_or_admin", changed_acl_inside_writer)
    denied_without_bytes(attach(api, stored["id"]), 403, "PERMISSION_DENIED")
    assert len(checks) == 2
    assert attachment_state(api) == before
    assert before["links"] == [{k: v for k, v in linked.items() if k != "signature_verification"}]


def test_former_admin_replaying_foreign_attachment_receipt_is_denied_before_file_open(
    scopes, monkeypatch
):
    api = scopes
    stored, _ = linked_private_file(api)
    before = attachment_state(api)
    ok(
        api.client.post(
            "/api/v1/users",
            json={
                "username": "second-admin",
                "password": PASSWORD,
                "role": "admin",
                "request_key": "create-second-admin",
            },
        )
    )
    login = ok(
        api.client.post(
            "/api/v1/auth/login",
            json={
                "username": "second-admin",
                "password": PASSWORD,
            },
        )
    )
    api.client.headers["Authorization"] = "Bearer " + login["access_token"]
    ok(
        api.client.patch(
            "/api/v1/users/" + api.admin.id,
            json={
                "request_key": "demote-original-admin",
                "expected_version": api.admin.version,
                "role": "operator",
                "active": True,
            },
        )
    )
    login = ok(
        api.client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
    )
    api.client.headers["Authorization"] = "Bearer " + login["access_token"]
    opened = []

    def forbid_open(file_id):
        opened.append(file_id)
        raise AssertionError("An idempotency receipt must not bypass current owner ACL")

    monkeypatch.setattr(api.runtime.files, "read", forbid_open)
    denied_without_bytes(
        attach(api, stored["id"], key="admin-explicit-attach"), 403, "PERMISSION_DENIED"
    )
    assert opened == []
    assert attachment_state(api) == before
