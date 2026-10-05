from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import (
    ActorScope,
    AuthorizationEvidence,
    CurrentActor,
    build_actor_scope,
    enforce_role_policy,
    get_access_policy,
)
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.security import hash_session_token
from src.platform.database.session import get_db_session

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_actor(
    db_session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
) -> CurrentActor:
    if session_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập",
        )

    actor = await IdentityRepository(db_session).get_current_actor_by_session_hash(
        hash_session_token(session_token),
        datetime.now(UTC),
    )

    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn",
        )

    return actor


CurrentActorDependency = Annotated[
    CurrentActor,
    Depends(get_current_actor),
]


async def authorize_request(
    request: Request,
    actor: CurrentActorDependency,
) -> None:
    endpoint = request.scope.get("endpoint")

    if not callable(endpoint):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền truy cập",
        )

    handler = cast(Callable[..., object], endpoint)
    enforce_role_policy(handler, actor)


async def get_request_scope(
    request: Request, actor: CurrentActorDependency
) -> ActorScope:
    endpoint = request.scope.get("endpoint")
    policy = get_access_policy(endpoint) if callable(endpoint) else None
    if (
        not callable(endpoint)
        or policy is None
        or policy.kind != "user"
        or policy.scope is None
    ):
        raise HTTPException(403, "Không có phạm vi truy cập dữ liệu")
    enforce_role_policy(endpoint, actor)
    return build_actor_scope(actor, policy.scope)


RequestScope = Annotated[ActorScope, Depends(get_request_scope)]


async def get_authorization_evidence(
    request: Request, actor: CurrentActorDependency
) -> AuthorizationEvidence:
    endpoint = request.scope.get("endpoint")
    policy = get_access_policy(endpoint) if callable(endpoint) else None
    if (
        not callable(endpoint)
        or policy is None
        or policy.kind != "user"
        or policy.permission is None
    ):
        raise HTTPException(403, "Không có quyền truy cập")
    enforce_role_policy(endpoint, actor)
    return AuthorizationEvidence(policy.permission, tuple(sorted(actor.roles)))


AuditEvidence = Annotated[AuthorizationEvidence, Depends(get_authorization_evidence)]
