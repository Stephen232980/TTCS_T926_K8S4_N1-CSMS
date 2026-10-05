from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.models import (
    LoginIpAttempt,
    Role,
    Session,
    User,
    UserRole,
)
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


@pytest.mark.asyncio
async def test_current_user_through_http(
    db_session: AsyncSession,
) -> None:
    await clean_test_data(db_session)

    role_result = await db_session.scalars(
        select(Role).where(
            Role.code.in_(["operator", "station_owner"]),
        )
    )
    roles = {role.code: role for role in role_result}
    assert set(roles) == {"operator", "station_owner"}

    user = User(
        email=TEST_EMAIL,
        password_hash=hash_password("mat-khau-dung"),
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add_all(
        [
            UserRole(
                user_id=user.id,
                role_id=roles["operator"].id,
            ),
            UserRole(
                user_id=user.id,
                role_id=roles["station_owner"].id,
            ),
        ]
    )
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

            response = await client.get("/api/v1/auth/me")

            assert response.status_code == 200
            assert response.json() == {
                "id": str(user.id),
                "email": TEST_EMAIL,
                "roles": ["operator", "station_owner"],
                "default_role": None,
            }
            assert response.headers["cache-control"] == "no-store"
    finally:
        await clean_test_data(db_session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_token",
    [
        None,
        "session-token-khong-hop-le",
    ],
)
async def test_current_user_rejects_missing_or_invalid_session(
    db_session: AsyncSession,
    session_token: str | None,
) -> None:
    async with api_client(db_session) as client:
        if session_token is not None:
            client.cookies.set("session", session_token)

        response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_current_user_rejects_expired_session(
    db_session: AsyncSession,
) -> None:
    await clean_test_data(db_session)

    session_token = "expired-session-token-t59"
    user = User(
        email=TEST_EMAIL,
        password_hash=hash_password("mat-khau-dung"),
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Session(
            user_id=user.id,
            token_hash=hash_session_token(session_token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    try:
        async with api_client(db_session) as client:
            client.cookies.set("session", session_token)

            response = await client.get("/api/v1/auth/me")

        assert response.status_code == 401
    finally:
        await clean_test_data(db_session)
