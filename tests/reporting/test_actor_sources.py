import pytest
from cafe_fin.core.errors import CoreError
from cafe_fin.reporting.module import module_manifest
from cafe_fin.reporting.service import ReportingService
from conftest import preview_command


def operator(env):
    env.runtime.auth.create_user(
        env.actor,
        username="scopedoperator",
        password="synthetic-scoped-password",
        role="operator",
        request_key="scoped-user",
    )
    login = env.runtime.auth.login("scopedoperator", "synthetic-scoped-password")
    return env.runtime.auth.authenticate(login["access_token"])


def test_actor_source_factory_is_fresh_per_capture_and_never_caches_admin(env):
    second = operator(env)
    observed = []

    def factory(runtime, actor):
        assert runtime is env.runtime
        observed.append(actor)
        return env.source

    service = ReportingService(env.runtime, actor_source_factory=factory)
    first = service.preview(env.actor, preview_command("admin"))
    service.preview(second, preview_command("operator", "Bổ sung"))
    service.preview(second, preview_command("operator-2", "Bổ sung"))
    assert [actor.id for actor in observed] == [env.actor.id, second.id, second.id]
    assert all(actor.role == "operator" for actor in observed[1:])
    # Replayed immutable capture does not resolve or read any source a second time.
    assert service.preview(env.actor, preview_command("admin"))["id"] == first["id"]
    assert len(observed) == 3


def test_revoked_actor_is_revalidated_before_factory_and_after_capture(env):
    second = operator(env)
    observed = []

    def factory(runtime, actor):
        observed.append(actor.id)
        runtime.auth.update_user(
            env.actor,
            second.id,
            role="operator",
            active=False,
            expected_version=second.version,
            request_key="deactivate-during-capture",
        )
        return env.source

    service = ReportingService(env.runtime, actor_source_factory=factory)
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        service.preview(second, preview_command("revoked"))
    assert service.list("reports")["total"] == 0
    with pytest.raises(CoreError, match="SESSION_EXPIRED"):
        service.preview(second, preview_command("revoked-again"))
    assert observed == [second.id]


def test_source_modes_are_exclusive(env):
    for options in (
        {"source": env.source, "actor_source_factory": lambda runtime, actor: env.source},
        {
            "source_factory": lambda runtime: env.source,
            "actor_source_factory": lambda runtime, actor: env.source,
        },
        {"source": env.source, "source_factory": lambda runtime: env.source},
    ):
        with pytest.raises(ValueError):
            module_manifest(**options)
