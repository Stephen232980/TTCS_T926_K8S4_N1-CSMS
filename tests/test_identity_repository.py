from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import CurrentActor
from src.modules.identity.models import (
    LoginIpAttempt,
    Role,
    Session,
    User,
    UserRole,
)
from src.modules.identity.repository import IdentityRepository


@pytest.mark.asyncio
async def test_repository_finds_user_by_email_for_update(
    db_session: AsyncSession,
) -> None:
    user = User(
        email="repository@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    await db_session.flush()

    repository = IdentityRepository(db_session)

    found_user = await repository.get_user_for_update(user.email)

    assert found_user is user


@pytest.mark.asyncio
async def test_repository_adds_and_finds_ip_attempt(
    db_session: AsyncSession,
) -> None:
    repository = IdentityRepository(db_session)
    ip_attempt = LoginIpAttempt(ip_address="192.0.2.10")

    repository.add_ip_attempt(ip_attempt)
    await db_session.flush()

    found_attempt = await repository.get_ip_attempt_for_update(ip_attempt.ip_address)

    assert found_attempt is ip_attempt


@pytest.mark.asyncio
async def test_repository_adds_session(
    db_session: AsyncSession,
) -> None:
    user = User(
        email="session-repository@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    await db_session.flush()

    repository = IdentityRepository(db_session)
    login_session = Session(
        user_id=user.id,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    repository.add_session(login_session)
    await db_session.flush()

    stored_session = await db_session.scalar(
        select(Session).where(Session.id == login_session.id)
    )

    assert stored_session is login_session


@pytest.mark.asyncio
async def test_repository_deletes_session_by_token_hash(
    db_session: AsyncSession,
) -> None:
    user = User(
        email="logout-repository@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    await db_session.flush()

    login_session = Session(
        user_id=user.id,
        token_hash="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(login_session)
    await db_session.flush()

    repository = IdentityRepository(db_session)

    await repository.delete_session_by_token_hash(login_session.token_hash)
    await db_session.flush()

    stored_session = await db_session.scalar(
        select(Session).where(Session.id == login_session.id)
    )

    assert stored_session is None


@pytest.mark.asyncio
async def test_repository_finds_current_actor_from_valid_session(
    db_session: AsyncSession,
) -> None:
    role = await db_session.scalar(select(Role).where(Role.code == "admin"))
    assert role is not None

    user = User(
        email="current-actor-repository@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            Session(
                user_id=user.id,
                token_hash="c" * 64,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
        ]
    )
    await db_session.flush()

    actor = await IdentityRepository(db_session).get_current_actor_by_session_hash(
        "c" * 64,
        datetime.now(UTC),
    )

    assert actor == CurrentActor(
        user_id=user.id,
        roles=frozenset({"admin"}),
    )


@pytest.mark.asyncio
async def test_repository_rejects_expired_session(
    db_session: AsyncSession,
) -> None:
    user = User(
        email="expired-session-repository@example.com",
        password_hash="test-password-hash",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Session(
            user_id=user.id,
            token_hash="d" * 64,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    await db_session.flush()

    actor = await IdentityRepository(db_session).get_current_actor_by_session_hash(
        "d" * 64,
        datetime.now(UTC),
    )

    assert actor is None
