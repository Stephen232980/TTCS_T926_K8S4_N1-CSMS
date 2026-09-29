import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.stations.models import Station
from src.platform.database.session import get_db_session


@asynccontextmanager
async def station_api_client(
    db_session: AsyncSession,
    actor: CurrentActor,
) -> AsyncIterator[AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_actor] = lambda: actor

    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_can_get_owned_station_through_http(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-http-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm HTTP hợp lệ",
        address="Địa chỉ hợp lệ",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner.id,
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{station.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(station.id)
    assert response.json()["owner_id"] == str(owner.id)
    assert response.json()["name"] == "Trạm HTTP hợp lệ"


@pytest.mark.asyncio
async def test_cross_owner_station_request_returns_403_and_logs(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a = User(
        email="station-http-cross-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-http-cross-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm HTTP của B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add(station_b)
    await db_session.flush()

    actor = CurrentActor(
        user_id=owner_a.id,
        roles=frozenset({"station_owner"}),
    )
    caplog.set_level(logging.WARNING, logger="csms.security")

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{station_b.id}")

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text
    assert owner_a.email not in caplog.text
    assert owner_b.email not in caplog.text


@pytest.mark.asyncio
async def test_missing_station_request_returns_404(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with station_api_client(db_session, actor) as client:
        response = await client.get(f"/api/v1/stations/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}
