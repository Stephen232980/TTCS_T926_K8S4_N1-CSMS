from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from src.modules.identity.authorization import (
    ActorScope,
    CurrentActor,
    build_actor_scope,
    enforce_role_policy,
    get_allowed_roles,
    user_policy,
)


def test_allow_roles_marks_handler_with_allowed_roles() -> None:
    @user_policy("test.manage", "all", "admin", "operator")
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) == frozenset({"admin", "operator"})


def test_handler_without_policy_is_detected() -> None:
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) is None


def test_allow_roles_rejects_empty_policy() -> None:
    with pytest.raises(ValueError, match="User policy requires"):
        user_policy("test.manage", "all")


def test_policy_rejects_admin_when_handler_has_no_policy() -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )

    def handler() -> None:
        pass

    with pytest.raises(HTTPException) as error:
        enforce_role_policy(handler, actor)

    assert error.value.status_code == status.HTTP_403_FORBIDDEN


def test_policy_rejects_actor_without_allowed_role() -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    @user_policy("test.manage", "all", "admin", "operator")
    def handler() -> None:
        pass

    with pytest.raises(HTTPException) as error:
        enforce_role_policy(handler, actor)

    assert error.value.status_code == status.HTTP_403_FORBIDDEN


def test_policy_allows_actor_with_matching_role() -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"operator"}),
    )

    @user_policy("test.manage", "all", "admin", "operator")
    def handler() -> None:
        pass

    enforce_role_policy(handler, actor)


@pytest.mark.parametrize(
    "roles",
    [
        {"station_owner"},
        {"admin", "station_owner"},
        {"operator", "station_owner"},
        {"accountant", "station_owner"},
    ],
)
def test_endpoint_scope_overrides_role_union(roles: set[str]) -> None:
    actor = CurrentActor(uuid4(), frozenset(roles))
    assert build_actor_scope(actor, "owned") == ActorScope(actor.user_id, actor.user_id)
    assert build_actor_scope(actor, "all") == ActorScope(actor.user_id, None)
