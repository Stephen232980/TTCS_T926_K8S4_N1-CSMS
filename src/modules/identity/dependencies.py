from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor
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
