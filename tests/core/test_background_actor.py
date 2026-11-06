"""Persisted background identities use real current users, permissions and transactions."""

import threading
from uuid import uuid4

import pytest
from cafe_fin.core import auth, jobs
from cafe_fin.core.audit import AuditService
from cafe_fin.core.auth import USERS, AuthService
from cafe_fin.core.db import AUDIT, REQUESTS, Database, WriteCoordinator
from cafe_fin.core.errors import CoreError
from cafe_fin.core.jobs import JobContext, JobHandler, JobRunner, JobService
from sqlalchemy import Column, Integer, MetaData, Table, insert, select


@pytest.fixture
def background(tmp_path):
    database = Database(tmp_path / "background-actor.sqlite3")
    database.migrate(auth.MIGRATIONS + jobs.MIGRATIONS)
    writer = WriteCoordinator(database)
    service = AuthService(database, writer)
    session = service.setup("config-admin", "synthetic-config-admin-password")
    manager = service.authenticate(session["access_token"])
    actors = {}
    for role in ("admin", "operator"):
        actors[role] = service.create_user(
            manager,
            username=f"background-{role}",
            password=f"synthetic-background-{role}-password",
            role=role,
            request_key=f"configure-{role}-actor",
        )
    try:
        yield database, writer, service, manager, actors
    finally:
        writer.close()
        database.close()


def persisted_state(database, *extra_tables):
    with database.read() as conn:
        return {
            table.name: conn.execute(select(table)).all()
            for table in (USERS, AUDIT, REQUESTS, jobs.JOBS, jobs.RECEIPTS, *extra_tables)
        }


def resolve(database, service, actor_id, permission):
    with database.read() as conn:
        conn.exec_driver_sql("BEGIN")
        return service.resolve_actor(conn, actor_id, permission)


def test_resolve_current_admin_and_operator_permissions_without_sessions_or_side_effects(
    background,
):
    database, _, service, _, actors = background
    before, sessions = persisted_state(database), dict(service._sessions)
    admin = resolve(database, service, actors["admin"]["id"], "core.manage")
    operator = resolve(database, service, actors["operator"]["id"], "reporting.read")
    assert (admin.id, admin.role, admin.version, admin.permissions) == (
        actors["admin"]["id"],
        "admin",
        1,
        ("*",),
    )
    assert (operator.id, operator.role, operator.version) == (
        actors["operator"]["id"],
        "operator",
        1,
    )
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        resolve(database, service, operator.id, "core.manage")
    assert persisted_state(database) == before
    assert service._sessions == sessions


@pytest.mark.parametrize("actor_id", [str(uuid4()), "unknown-background-actor"])
def test_unknown_background_identity_fails_closed_with_sanitized_error_and_no_side_effects(
    background, actor_id
):
    database, _, service, _, _ = background
    before, sessions = persisted_state(database), dict(service._sessions)
    with pytest.raises(CoreError, match="BACKGROUND_ACTOR_UNAVAILABLE") as caught:
        resolve(database, service, actor_id, "reporting.write")
    error = caught.value
    assert error.status == 403 and error.details == {} and error.field_errors == []
    assert actor_id not in error.message
    assert persisted_state(database) == before
    assert service._sessions == sessions


def test_disabled_actor_is_unavailable_and_demotion_uses_current_permissions(background):
    database, _, service, manager, actors = background
    service.update_user(
        manager,
        actors["operator"]["id"],
        role="operator",
        active=False,
        expected_version=1,
        request_key="disable-background-operator",
    )
    before, sessions = persisted_state(database), dict(service._sessions)
    with pytest.raises(CoreError, match="BACKGROUND_ACTOR_UNAVAILABLE"):
        resolve(database, service, actors["operator"]["id"], "reporting.read")
    assert persisted_state(database) == before and service._sessions == sessions
    service.update_user(
        manager,
        actors["admin"]["id"],
        role="operator",
        active=True,
        expected_version=1,
        request_key="demote-background-admin",
    )
    current = resolve(database, service, actors["admin"]["id"], "reporting.read")
    assert current.role == "operator" and current.version == 2
    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        resolve(database, service, actors["admin"]["id"], "core.manage")


@pytest.mark.parametrize("change", ["disable", "demote", "version"])
@pytest.mark.parametrize("phase", ["chunk", "finalize"])
def test_captured_actor_change_rolls_back_real_job_effect_audit_and_progress(
    background, change, phase
):
    database, writer, service, manager, actors = background
    captured = resolve(database, service, actors["admin"]["id"], "reporting.write")
    table = Table(
        "background_scope_effect",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("value", Integer, nullable=False),
    )
    writer.run(lambda conn: table.create(conn))
    writer.run(lambda conn: conn.execute(insert(table).values(id=1, value=0)))
    job_service = JobService(
        database, writer, {"reporting.backgroundproof": JobHandler(lambda context, payload: None)}
    )
    job_id = job_service.submit(
        captured.id,
        "reporting.backgroundproof",
        {},
        "configured-background-job",
        authorize=lambda conn: service.authorize(conn, captured, "reporting.write"),
    )["job_id"]
    # A real core claim supplies the lease; no worker is started so the race boundary
    # stays deterministic while the administrator changes the persisted account.
    claimed = writer.run(JobRunner(job_service)._claim)
    context = JobContext(job_service, job_id, threading.Event(), generation=claimed["generation"])
    service.update_user(
        manager,
        captured.id,
        role="operator" if change == "demote" else "admin",
        active=change != "disable",
        expected_version=1,
        request_key=f"actor-{change}",
    )
    before, sessions = persisted_state(database, table), dict(service._sessions)

    def effect(conn):
        # Deliberately check late here to prove SQLite rolls back already-started
        # work as well. Production effects should authorize before their writes.
        conn.execute(table.update().values(value=99))
        AuditService.record(
            conn,
            actor=captured.id,
            entity="synthetic_background",
            entity_id="1",
            action=phase,
            after={"value": 99},
        )
        service.authorize(conn, captured, "reporting.write")
        return {"value": 99}

    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        if phase == "chunk":
            context.commit_chunk(
                "chunk-1",
                {},
                checkpoint={"next": 1},
                counts={"done": 1},
                phase="reporting.backgroundproof",
                effect=effect,
            )
        else:
            context.finalize(effect)
    assert persisted_state(database, table) == before
    assert service._sessions == sessions
    assert job_service.status(job_id)["state"] == "RUNNING"


def test_password_version_rotation_resolves_current_identity_but_invalidates_capture(background):
    database, writer, service, manager, actors = background
    captured = resolve(database, service, actors["operator"]["id"], "reporting.write")
    sessions = dict(service._sessions)
    new_hash = service._hasher.hash("synthetic-rotated-background-password")

    def rotate_fixture_credential(conn):
        # Trusted fixture for a future administrator credential-rotation flow;
        # this helper adds no password-reset API or login behavior.
        service.authorize(conn, manager, "core.manage")
        conn.execute(
            USERS.update()
            .where(USERS.c.id == captured.id)
            .values(password_hash=new_hash, version=2)
        )

    writer.run(rotate_fixture_credential)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        writer.run(lambda conn: service.authorize(conn, captured, "reporting.write"))
    current = resolve(database, service, captured.id, "reporting.write")
    assert current.role == "operator" and current.version == 2
    assert writer.run(lambda conn: service.authorize(conn, current, "reporting.write")) == current
    assert service._sessions == sessions


def test_logged_out_configured_actor_can_resolve_without_recreating_login_session(background):
    database, _, service, _, actors = background
    token = service.login("background-operator", "synthetic-background-operator-password")[
        "access_token"
    ]
    service.logout(token)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        service.authenticate(token)
    sessions = dict(service._sessions)
    current = resolve(database, service, actors["operator"]["id"], "reporting.read")
    assert current.id == actors["operator"]["id"]
    assert service._sessions == sessions


def test_resolve_uses_uncommitted_account_state_on_the_supplied_connection(background):
    database, writer, service, manager, actors = background
    actor_id = actors["admin"]["id"]
    before = persisted_state(database)

    def attempted_change(conn):
        service.authorize(conn, manager, "core.manage")
        conn.execute(
            USERS.update().where(USERS.c.id == actor_id).values(role="operator", version=2)
        )
        # A resolver opening another read connection would incorrectly see Admin.
        service.resolve_actor(conn, actor_id, "core.manage")

    with pytest.raises(CoreError, match="PERMISSION_DENIED"):
        writer.run(attempted_change)
    assert persisted_state(database) == before
