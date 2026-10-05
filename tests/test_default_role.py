import importlib
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.role_assignment import (
    assign_user_roles,
    get_default_role,
    set_default_role,
)
from src.platform.database.session import get_db_session


async def create_user(db):
    user = User(email=f"default-{uuid4()}@example.com", password_hash="unused")
    db.add(user)
    await db.flush()
    return user


async def test_migration_backfills_only_single_role_and_round_trips(
    db_session, monkeypatch
):
    schema = f"default_migration_{uuid4().hex}"
    await db_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    await db_session.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    await db_session.execute(
        text(
            "CREATE TABLE user_roles (user_id integer NOT NULL, role_id integer NOT NULL, PRIMARY KEY (user_id, role_id))"
        )
    )
    await db_session.execute(
        text("INSERT INTO user_roles VALUES (1, 10), (2, 10), (2, 20)")
    )
    migration = importlib.import_module("migrations.versions.e030007a2026_default_role")

    def upgrade(connection):
        monkeypatch.setattr(
            migration, "op", Operations(MigrationContext.configure(connection))
        )
        migration.upgrade()

    connection = await db_session.connection()
    await connection.run_sync(upgrade)
    result = (
        await db_session.execute(
            text("SELECT user_id, is_default FROM user_roles ORDER BY user_id, role_id")
        )
    ).all()
    assert result == [(1, True), (2, False), (2, False)]
    await connection.run_sync(lambda connection: migration.downgrade())
    await connection.run_sync(upgrade)
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM user_roles WHERE is_default")
        )
    ).scalar() == 1


async def test_assignment_preserves_default_and_clears_removed_role(db_session):
    user = await create_user(db_session)
    await assign_user_roles(db_session, user.id, ["station_owner"])
    assert await get_default_role(db_session, user.id) == "station_owner"
    await assign_user_roles(db_session, user.id, ["admin"], replace=False)
    assert await get_default_role(db_session, user.id) == "station_owner"
    await set_default_role(db_session, user.id, "admin")
    await assign_user_roles(db_session, user.id, ["station_owner", "driver"])
    assert await get_default_role(db_session, user.id) is None


async def test_multiple_roles_never_pick_an_implicit_default(db_session):
    user = await create_user(db_session)
    await assign_user_roles(db_session, user.id, ["admin", "station_owner"])
    assert await get_default_role(db_session, user.id) is None
    with pytest.raises(HTTPException) as error:
        await set_default_role(db_session, user.id, "operator")
    assert error.value.status_code == 422
    assert await get_default_role(db_session, user.id) is None
    await set_default_role(db_session, user.id, "admin")
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                update(UserRole)
                .where(UserRole.user_id == user.id)
                .values(is_default=True)
            )
    assert await get_default_role(db_session, user.id) == "admin"


async def test_default_role_endpoint_is_own_preference_not_authorization(db_session):
    user = await create_user(db_session)
    other = await create_user(db_session)
    await assign_user_roles(db_session, user.id, ["admin", "station_owner"])
    await assign_user_roles(db_session, other.id, ["driver"])

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        user.id, frozenset({"admin", "station_owner"})
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            rejected = await client.put(
                "/api/v1/auth/default-role", json={"role": "operator"}
            )
            assert rejected.status_code == 422
            spoofed = await client.put(
                "/api/v1/auth/default-role",
                json={"role": "admin", "user_id": str(other.id)},
            )
            assert spoofed.status_code == 422
            result = await client.put(
                "/api/v1/auth/default-role", json={"role": "station_owner"}
            )
            assert result.status_code == 200
            assert result.json()["default_role"] == "station_owner"
            assert set(result.json()["roles"]) == {"admin", "station_owner"}
            assert await get_default_role(db_session, other.id) == "driver"
            assert (await client.get("/api/v1/auth/me")).json()[
                "default_role"
            ] == "station_owner"
            codes = await db_session.scalars(
                select(Role.code).join(UserRole).where(UserRole.user_id == user.id)
            )
            assert set(codes) == {"admin", "station_owner"}
    finally:
        app.dependency_overrides.clear()
