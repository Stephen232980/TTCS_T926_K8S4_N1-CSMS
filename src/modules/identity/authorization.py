from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, ParamSpec, TypeVar, cast
from uuid import UUID

from fastapi import HTTPException, status


@dataclass(frozen=True)
class CurrentActor:
    user_id: UUID
    roles: frozenset[str]


@dataclass(frozen=True)
class ActorScope:
    actor_id: UUID
    owner_id: UUID | None


@dataclass(frozen=True)
class AuthorizationEvidence:
    permission: str
    roles: tuple[str, ...]


P = ParamSpec("P")
R = TypeVar("R")

_ROLE_POLICY_ATTRIBUTE = "__csms_allowed_roles__"
DataScope = Literal["owned", "own", "own_wallet", "all"]
AccessKind = Literal["user", "public", "device", "webhook"]
_ACCESS_POLICY_ATTRIBUTE = "__csms_access_policy__"


@dataclass(frozen=True)
class AccessPolicy:
    kind: AccessKind
    permission: str | None = None
    scope: DataScope | None = None
    roles: frozenset[str] = frozenset()
    note: str = ""


def access_policy(policy: AccessPolicy) -> Callable[[Callable[P, R]], Callable[P, R]]:
    if policy.kind not in {"user", "public", "device", "webhook"}:
        raise ValueError("Unknown access policy kind")
    if policy.kind == "user" and (
        not policy.permission or not policy.scope or not policy.roles
    ):
        raise ValueError("User policy requires permission, scope and roles")
    if policy.kind != "user" and (policy.permission or policy.scope or policy.roles):
        raise ValueError("Non-user policy cannot declare user permissions")

    def decorator(handler: Callable[P, R]) -> Callable[P, R]:
        if get_access_policy(handler) is not None:
            raise ValueError("Endpoint must have exactly one access policy")
        setattr(handler, _ACCESS_POLICY_ATTRIBUTE, policy)
        if policy.kind == "user":
            setattr(handler, _ROLE_POLICY_ATTRIBUTE, policy.roles)
        return handler

    return decorator


def user_policy(
    permission: str, scope: DataScope, *roles: str
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return access_policy(AccessPolicy("user", permission, scope, frozenset(roles)))


def get_access_policy(handler: Callable[..., object]) -> AccessPolicy | None:
    return cast(AccessPolicy | None, getattr(handler, _ACCESS_POLICY_ATTRIBUTE, None))


def build_actor_scope(actor: CurrentActor, scope: DataScope) -> ActorScope:
    # The authorized endpoint chooses the scope, never the actor's role union.
    return ActorScope(
        actor_id=actor.user_id, owner_id=None if scope == "all" else actor.user_id
    )


def get_allowed_roles(
    handler: Callable[..., object],
) -> frozenset[str] | None:
    policy = getattr(handler, _ROLE_POLICY_ATTRIBUTE, None)
    return cast(frozenset[str] | None, policy)


def enforce_role_policy(
    handler: Callable[..., object],
    actor: CurrentActor,
) -> None:
    policy = get_access_policy(handler)
    allowed_roles = (
        policy.roles if policy is not None and policy.kind == "user" else None
    )

    if allowed_roles is None or actor.roles.isdisjoint(allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền truy cập",
        )
