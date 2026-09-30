import pytest
from sqlalchemy import Index, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import Role, User


def test_user_email_is_normalized() -> None:
    user = User(
        email="  Owner@Example.COM  ",
        password_hash="not-a-real-password-hash",
    )

    assert user.email == "owner@example.com"


def test_user_operational_defaults_and_case_insensitive_email_index() -> None:
    assert User.__table__.c.status.default is not None
    assert User.__table__.c.status.default.arg == "active"
    assert User.__table__.c.status.server_default is not None

    indexes = {
        index.name: index
        for index in User.__table__.indexes
        if isinstance(index, Index)
    }
    assert indexes["uq_users_email_ci"].unique


@pytest.mark.asyncio
async def test_duplicate_normalized_email_is_rejected(
    db_session: AsyncSession,
) -> None:
    first_user = User(
        email="owner@example.com",
        password_hash="first-test-password-hash",
    )
    db_session.add(first_user)
    await db_session.flush()

    duplicate_user = User(
        email="  OWNER@EXAMPLE.COM ",
        password_hash="second-test-password-hash",
    )
    db_session.add(duplicate_user)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_database_contains_required_roles(
    db_session: AsyncSession,
) -> None:
    result = await db_session.execute(select(Role.code))
    role_codes = set(result.scalars().all())

    assert role_codes == {
        "driver",
        "station_owner",
        "operator",
        "accountant",
        "admin",
    }
