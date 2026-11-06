"""Fresh Admin-only source identity before any operation, intent or filesystem work."""

import hashlib
from uuid import uuid4

import pytest
from cafe_fin.core.activation import location_fingerprint, root_identity
from cafe_fin.core.errors import CoreError
from cafe_fin.core.maintenance_protocol import ControlDispatcher, parse_command
from sqlalchemy import text

from tests.core.test_maintenance_operations import PASSWORD
from tests.core.test_maintenance_operations import make_env as make_env
from tests.core.test_maintenance_protocol import envelope


def snapshot(runtime):
    with runtime.reader() as conn:
        tables = (
            conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            .scalars()
            .all()
        )
        rows = {name: conn.execute(text('SELECT * FROM "' + name + '"')).all() for name in tables}
    files = {
        path.relative_to(runtime.root.path).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in runtime.root.path.rglob("*")
        if path.is_file() and path.name != ".instance.lock"
    }
    # Windows deliberately denies reads of the live exclusive instance-lock file.
    files[".instance.lock"] = (
        id(runtime.root._lock),
        runtime.root._lock.closed,
        (runtime.root.path / ".instance.lock").stat().st_size,
    )
    return rows, files, dict(runtime.auth._sessions), runtime.maintenance.status()


def test_fresh_admin_source_identity_is_validated_read_only_and_creates_no_operation(make_env):
    env = make_env()
    before = snapshot(env.runtime)
    result = env.ops.authorize_source_identity(env.token)
    assert result == {
        "root_id": root_identity(env.runtime.root),
        "source_fingerprint": location_fingerprint(env.runtime.root.path),
    }
    assert snapshot(env.runtime) == before


def test_source_identity_operator_logged_out_and_revoked_admin_fail_without_effects(make_env):
    env = make_env()
    operator = env.runtime.auth.login("operations-operator", PASSWORD)["access_token"]
    before = snapshot(env.runtime)
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        env.ops.authorize_source_identity(operator)
    assert snapshot(env.runtime) == before
    env.runtime.auth.logout(env.token)
    before = snapshot(env.runtime)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.ops.authorize_source_identity(env.token)
    assert snapshot(env.runtime) == before
    token = env.runtime.auth.login("operations-admin", PASSWORD)["access_token"]
    other = env.runtime.auth.authenticate(
        env.runtime.auth.login("other-admin", PASSWORD)["access_token"]
    )
    env.runtime.auth.update_user(
        other,
        env.actor.id,
        role="operator",
        active=True,
        expected_version=1,
        request_key="revoke-source-identity",
    )
    before = snapshot(env.runtime)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        env.ops.authorize_source_identity(token)
    assert snapshot(env.runtime) == before


def test_source_identity_wire_generation_nonce_and_current_auth_are_rechecked(make_env):
    env = make_env()
    dispatcher = ControlDispatcher(env.runtime, env.generation, close=lambda: None)
    before = snapshot(env.runtime)
    stale = envelope(str(uuid4()), "maintenance.source_identity", access_token=env.token)
    denied = dispatcher.execute(parse_command(stale))
    assert denied["code"] == "MAINTENANCE_GENERATION_CONFLICT"
    assert "root_id" not in denied and "source_fingerprint" not in denied
    assert snapshot(env.runtime) == before
    request = envelope(env.generation, "maintenance.source_identity", access_token=env.token)
    result = dispatcher.execute(parse_command(request))
    assert result["status"] == "ok"
    assert result["root_id"] == root_identity(env.runtime.root)
    assert result["source_fingerprint"] == location_fingerprint(env.runtime.root.path)
    assert "operation_id" not in result and "allowed" not in result
    assert dispatcher.execute(parse_command(request))["code"] == "MAINTENANCE_REQUEST_REPLAY"
    assert snapshot(env.runtime) == before
    env.runtime.auth.logout(env.token)
    before = snapshot(env.runtime)
    fresh_nonce = envelope(env.generation, "maintenance.source_identity", access_token=env.token)
    assert dispatcher.execute(parse_command(fresh_nonce))["code"] == "SESSION_EXPIRED"
    assert snapshot(env.runtime) == before


@pytest.mark.parametrize(
    "field",
    [
        "operation_id",
        "origin_generation",
        "destination",
        "backup_source",
        "root_id",
        "source_fingerprint",
        "actor",
        "role",
    ],
)
def test_source_identity_strict_command_has_no_operation_origin_path_or_identity_input(field):
    request = envelope(str(uuid4()), "maintenance.source_identity")
    request[field] = "SYNTHETIC-rejected-input"
    with pytest.raises(CoreError, match="MAINTENANCE_PROTOCOL_INVALID"):
        parse_command(request)
