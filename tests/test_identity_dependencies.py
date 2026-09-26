from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor, allow_roles
from src.modules.identity.dependencies import authorize_request, get_current_actor
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.security import hash_session_token


@pytest.mark.asyncio
async def test_get_current_actor_rejects_missing_cookie() -> None:
    db_session = AsyncMock(spec=AsyncSession)

    with pytest.raises(HTTPException) as error:
        await get_current_actor(db_session, None)

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Chưa đăng nhập"


@pytest.mark.asyncio
async def test_get_current_actor_rejects_invalid_session() -> None:
    db_session = AsyncMock(spec=AsyncSession)

    with (
        patch.object(
            IdentityRepository,
            "get_current_actor_by_session_hash",
            new_callable=AsyncMock,
            return_value=None,
        ) as find_actor,
        pytest.raises(HTTPException) as error,
    ):
        await get_current_actor(db_session, "invalid-session-token")

    assert error.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert error.value.detail == "Phiên đăng nhập không hợp lệ hoặc đã hết hạn"

    token_hash, _current_time = find_actor.await_args.args
    assert token_hash == hash_session_token("invalid-session-token")


@pytest.mark.asyncio
async def test_get_current_actor_returns_actor_for_valid_session() -> None:
    db_session = AsyncMock(spec=AsyncSession)
    expected_actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )

    with patch.object(
        IdentityRepository,
        "get_current_actor_by_session_hash",
        new_callable=AsyncMock,
        return_value=expected_actor,
    ):
        actor = await get_current_actor(db_session, "valid-session-token")

    assert actor == expected_actor


@pytest.mark.asyncio
async def test_authorize_request_allows_matching_role() -> None:
    @allow_roles("admin")
    def handler() -> None:
        pass

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/protected",
            "headers": [],
            "endpoint": handler,
        }
    )
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )

    await authorize_request(request, actor)


@pytest.mark.asyncio
async def test_authorize_request_rejects_route_without_policy() -> None:
    def handler() -> None:
        pass

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/unconfigured",
            "headers": [],
            "endpoint": handler,
        }
    )
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"admin"}),
    )

    with pytest.raises(HTTPException) as error:
        await authorize_request(request, actor)

    assert error.value.status_code == status.HTTP_403_FORBIDDEN
