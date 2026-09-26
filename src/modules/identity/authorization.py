from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar, cast
from uuid import UUID

from fastapi import HTTPException, status


@dataclass(frozen=True)
class CurrentActor:
    user_id: UUID
    roles: frozenset[str]


P = ParamSpec("P")
R = TypeVar("R")

_ROLE_POLICY_ATTRIBUTE = "__csms_allowed_roles__"


def allow_roles(
    *roles: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    if not roles:
        raise ValueError("Policy phải có ít nhất một vai trò")

    allowed_roles = frozenset(roles)

    def decorator(handler: Callable[P, R]) -> Callable[P, R]:
        setattr(handler, _ROLE_POLICY_ATTRIBUTE, allowed_roles)
        return handler

    return decorator


def get_allowed_roles(
    handler: Callable[..., object],
) -> frozenset[str] | None:
    policy = getattr(handler, _ROLE_POLICY_ATTRIBUTE, None)
    return cast(frozenset[str] | None, policy)


def enforce_role_policy(
    handler: Callable[..., object],
    actor: CurrentActor,
) -> None:
    allowed_roles = get_allowed_roles(handler)

    if allowed_roles is None or actor.roles.isdisjoint(allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền truy cập",
        )
