from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import LoginIpAttempt, Session, User
from src.modules.identity.repository import IdentityRepository
from src.modules.identity.security import hash_password, hash_session_token
from src.modules.identity.service import (
    AuthService,
    InvalidCredentialsError,
    LoginLockedError,
)

TEST_EMAIL_PREFIX = "t05-test-"
TEST_IP_PREFIX = "2001:db8:"


def make_service(db_session: AsyncSession) -> AuthService:
    return AuthService(
        db_session,
        IdentityRepository(db_session),
        max_failed_attempts=5,
        lock_seconds=900,
        session_ttl_seconds=3600,
    )


async def clean_test_data(db_session: AsyncSession) -> None:
    await db_session.rollback()
    await db_session.execute(
        delete(User).where(User.email.like(f"{TEST_EMAIL_PREFIX}%"))
    )
    await db_session.execute(
        delete(LoginIpAttempt).where(
            LoginIpAttempt.ip_address.like(f"{TEST_IP_PREFIX}%")
        )
    )
    await db_session.commit()


@pytest_asyncio.fixture(autouse=True)
async def cleanup_auth_test_data(
    db_session: AsyncSession,
) -> AsyncIterator[None]:
    await clean_test_data(db_session)
    yield
    await clean_test_data(db_session)


async def create_user(
    db_session: AsyncSession,
    *,
    email: str,
    password: str,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_successful_login_creates_hashed_session(
    db_session: AsyncSession,
) -> None:
    user = await create_user(
        db_session,
        email="t05-test-success@example.com",
        password="mat-khau-dung",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)

    result = await make_service(db_session).login(
        user.email,
        "mat-khau-dung",
        "2001:db8::1",
        now=now,
    )

    stored_session = await db_session.scalar(
        select(Session).where(Session.user_id == user.id)
    )

    assert stored_session is not None
    assert stored_session.token_hash == hash_session_token(result.token)
    assert stored_session.token_hash != result.token
    assert result.expires_at == now + timedelta(hours=1)
    assert stored_session.expires_at == result.expires_at


@pytest.mark.asyncio
async def test_wrong_password_increases_user_and_ip_counters(
    db_session: AsyncSession,
) -> None:
    user = await create_user(
        db_session,
        email="t05-test-wrong@example.com",
        password="mat-khau-dung",
    )
    ip_address = "2001:db8::2"

    with pytest.raises(InvalidCredentialsError):
        await make_service(db_session).login(
            user.email,
            "mat-khau-sai",
            ip_address,
        )

    await db_session.refresh(user)
    ip_attempt = await db_session.get(LoginIpAttempt, ip_address)

    assert user.failed_login_count == 1
    assert ip_attempt is not None
    assert ip_attempt.failed_login_count == 1


@pytest.mark.asyncio
async def test_unknown_email_still_increases_ip_counter(
    db_session: AsyncSession,
) -> None:
    ip_address = "2001:db8::3"

    with pytest.raises(InvalidCredentialsError):
        await make_service(db_session).login(
            "t05-test-missing@example.com",
            "mat-khau-sai",
            ip_address,
        )

    ip_attempt = await db_session.get(LoginIpAttempt, ip_address)

    assert ip_attempt is not None
    assert ip_attempt.failed_login_count == 1


@pytest.mark.asyncio
async def test_five_failures_lock_login_and_lock_survives_new_service(
    db_session: AsyncSession,
) -> None:
    user = await create_user(
        db_session,
        email="t05-test-locked@example.com",
        password="mat-khau-dung",
    )
    ip_address = "2001:db8::4"
    now = datetime(2026, 1, 1, tzinfo=UTC)
    service = make_service(db_session)

    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await service.login(
                user.email,
                "mat-khau-sai",
                ip_address,
                now=now,
            )

    await db_session.refresh(user)
    ip_attempt = await db_session.get(LoginIpAttempt, ip_address)

    assert user.failed_login_count == 5
    assert user.locked_until == now + timedelta(minutes=15)
    assert ip_attempt is not None
    assert ip_attempt.failed_login_count == 5
    assert ip_attempt.locked_until == now + timedelta(minutes=15)

    # Service mới mô phỏng ứng dụng vừa restart.
    restarted_service = make_service(db_session)

    with pytest.raises(LoginLockedError):
        await restarted_service.login(
            user.email,
            "mat-khau-dung",
            ip_address,
            now=now,
        )


@pytest.mark.asyncio
async def test_login_succeeds_after_lock_expires_and_resets_counters(
    db_session: AsyncSession,
) -> None:
    user = await create_user(
        db_session,
        email="t05-test-expired@example.com",
        password="mat-khau-dung",
    )
    ip_address = "2001:db8::5"
    locked_at = datetime(2026, 1, 1, tzinfo=UTC)
    service = make_service(db_session)

    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await service.login(
                user.email,
                "mat-khau-sai",
                ip_address,
                now=locked_at,
            )

    await service.login(
        user.email,
        "mat-khau-dung",
        ip_address,
        now=locked_at + timedelta(minutes=15, seconds=1),
    )

    await db_session.refresh(user)
    ip_attempt = await db_session.get(LoginIpAttempt, ip_address)

    assert user.failed_login_count == 0
    assert user.locked_until is None
    assert ip_attempt is not None
    assert ip_attempt.failed_login_count == 0
    assert ip_attempt.locked_until is None


@pytest.mark.asyncio
async def test_logout_deletes_stored_session(
    db_session: AsyncSession,
) -> None:
    user = await create_user(
        db_session,
        email="t05-test-logout@example.com",
        password="mat-khau-dung",
    )
    service = make_service(db_session)
    result = await service.login(
        user.email,
        "mat-khau-dung",
        "2001:db8::6",
    )

    await service.logout(result.token)

    stored_session = await db_session.scalar(
        select(Session).where(Session.token_hash == hash_session_token(result.token))
    )

    assert stored_session is None


@pytest.mark.asyncio
async def test_logout_without_token_does_nothing(
    db_session: AsyncSession,
) -> None:
    await make_service(db_session).logout(None)
