from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import (
    CurrentActor,
    enforce_role_policy,
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
