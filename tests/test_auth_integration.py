from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.models import LoginIpAttempt, Session, User
from src.modules.identity.security import hash_password, hash_session_token
from src.platform.database.session import get_db_session

TEST_EMAIL = "t05-http-test@example.com"


@asynccontextmanager
async def api_client(
    db_session: AsyncSession,
) -> AsyncIterator[AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session

    transport = ASGITransport(
        app=app,
        client=("2001:db8::20", 12345),
    )

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def clean_test_data(db_session: AsyncSession) -> None:
    await db_session.rollback()
    await db_session.execute(delete(User).where(User.email == TEST_EMAIL))
    await db_session.execute(
        delete(LoginIpAttempt).where(LoginIpAttempt.ip_address == "2001:db8::20")
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_login_and_logout_through_http(
    db_session: AsyncSession,
) -> None:
    await clean_test_data(db_session)

    user = User(
        email=TEST_EMAIL,
        password_hash=hash_password("mat-khau-dung"),
    )
    db_session.add(user)
    await db_session.commit()

    try:
        async with api_client(db_session) as client:
            login_response = await client.post(
                "/api/v1/auth/login",
                json={
                    "email": TEST_EMAIL,
                    "password": "mat-khau-dung",
                },
            )

            assert login_response.status_code == 200
            assert login_response.json() == {"status": "authenticated"}

            token = client.cookies.get("session")
            assert token is not None

            stored_session = await db_session.scalar(
                select(Session).where(Session.token_hash == hash_session_token(token))
            )
            assert stored_session is not None
            assert stored_session.token_hash != token

            logout_response = await client.post("/api/v1/auth/logout")

            assert logout_response.status_code == 204

            stored_session = await db_session.scalar(
                select(Session).where(Session.token_hash == hash_session_token(token))
            )
            assert stored_session is None
    finally:
        await clean_test_data(db_session)
