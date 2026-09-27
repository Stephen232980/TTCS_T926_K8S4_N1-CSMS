from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from src.modules.identity.authorization import (
    ActorScope,
    CurrentActor,
    allow_roles,
    build_actor_scope,
    enforce_role_policy,
    get_allowed_roles,
)


def test_allow_roles_marks_handler_with_allowed_roles() -> None:
    @allow_roles("admin", "operator")
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) == frozenset({"admin", "operator"})


def test_handler_without_policy_is_detected() -> None:
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) is None


def test_allow_roles_rejects_empty_policy() -> None:
    with pytest.raises(ValueError, match="ít nhất một vai trò"):
        allow_roles()


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

    @allow_roles("admin", "operator")
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

    @allow_roles("admin", "operator")
    def handler() -> None:
        pass

    enforce_role_policy(handler, actor)


def test_station_owner_scope_is_limited_to_own_data() -> None:
    user_id = uuid4()
    actor = CurrentActor(
        user_id=user_id,
        roles=frozenset({"station_owner"}),
    )

    scope = build_actor_scope(actor)

    assert scope == ActorScope(
        actor_id=user_id,
        owner_id=user_id,
    )


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_operator_and_admin_scope_can_access_all_data(role: str) -> None:
    user_id = uuid4()
    actor = CurrentActor(
        user_id=user_id,
        roles=frozenset({role}),
    )

    scope = build_actor_scope(actor)

    assert scope == ActorScope(
        actor_id=user_id,
        owner_id=None,
    )


def test_global_role_takes_precedence_over_station_owner_role() -> None:
    user_id = uuid4()
    actor = CurrentActor(
        user_id=user_id,
        roles=frozenset({"station_owner", "operator"}),
    )

    scope = build_actor_scope(actor)

    assert scope == ActorScope(
        actor_id=user_id,
        owner_id=None,
    )


@pytest.mark.parametrize("role", ["driver", "accountant"])
def test_role_without_ownership_scope_is_rejected(role: str) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({role}),
    )

    with pytest.raises(HTTPException) as error:
        build_actor_scope(actor)

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
