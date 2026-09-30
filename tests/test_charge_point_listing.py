import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import get_db_session


@asynccontextmanager
async def api_client(
    db_session: AsyncSession,
    actor: CurrentActor,
) -> AsyncIterator[AsyncClient]:
    async def override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_current_actor] = lambda: actor
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def create_owner_and_station(
    db_session: AsyncSession,
    prefix: str,
) -> tuple[User, Station]:
    owner = User(
        email=f"{prefix}-{uuid4()}@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()
    station = Station(
        owner_id=owner.id,
        name=f"Station {prefix}",
        address="Ho Chi Minh City",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()
    return owner, station


def actor(user_id: UUID, role: str) -> CurrentActor:
    return CurrentActor(user_id=user_id, roles=frozenset({role}))


@pytest.mark.asyncio
async def test_owner_lists_paginated_charge_points_with_sorted_connectors(
    db_session: AsyncSession,
) -> None:
    owner, station = await create_owner_and_station(db_session, "list-owner")
    first = ChargePoint(
        station_id=station.id,
        code=f"CP-LIST-A-{uuid4()}",
        connectors=[Connector(connector_number=2), Connector(connector_number=1)],
    )
    second = ChargePoint(
        station_id=station.id,
        code=f"CP-LIST-B-{uuid4()}",
        connectors=[Connector(connector_number=1)],
    )
    db_session.add_all([first, second])
    await db_session.flush()

    async with api_client(db_session, actor(owner.id, "station_owner")) as client:
        response = await client.get(
            f"/api/v1/stations/{station.id}/charge-points",
            params={"page": 1, "page_size": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] == 2
    assert payload["total_pages"] == 2
    assert len(payload["items"]) == 1
    assert payload["items"][0]["station_id"] == str(station.id)

    async with api_client(db_session, actor(owner.id, "station_owner")) as client:
        full_response = await client.get(
            f"/api/v1/stations/{station.id}/charge-points",
            params={"page_size": 10},
        )

    items_by_code = {item["code"]: item for item in full_response.json()["items"]}
    assert [
        connector["connector_number"]
        for connector in items_by_code[first.code]["connectors"]
    ] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "admin"])
async def test_global_roles_can_list_station_charge_points(
    db_session: AsyncSession,
    role: str,
) -> None:
    _, station = await create_owner_and_station(db_session, f"list-{role}")
    db_session.add(ChargePoint(station_id=station.id, code=f"CP-{role}-{uuid4()}"))
    await db_session.flush()

    async with api_client(db_session, actor(uuid4(), role)) as client:
        response = await client.get(f"/api/v1/stations/{station.id}/charge-points")

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.asyncio
async def test_cross_owner_list_returns_403_and_logs(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a, _ = await create_owner_and_station(db_session, "list-owner-a")
    _, station_b = await create_owner_and_station(db_session, "list-owner-b")
    caplog.set_level(logging.WARNING, logger="csms.security")

    async with api_client(db_session, actor(owner_a.id, "station_owner")) as client:
        response = await client.get(f"/api/v1/stations/{station_b.id}/charge-points")

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text


@pytest.mark.asyncio
async def test_missing_station_returns_404(db_session: AsyncSession) -> None:
    owner, _ = await create_owner_and_station(db_session, "list-missing")

    async with api_client(db_session, actor(owner.id, "station_owner")) as client:
        response = await client.get(f"/api/v1/stations/{uuid4()}/charge-points")

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.asyncio
async def test_driver_cannot_list_charge_points(db_session: AsyncSession) -> None:
    async with api_client(db_session, actor(uuid4(), "driver")) as client:
        response = await client.get(f"/api/v1/stations/{uuid4()}/charge-points")

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parameter", "value"),
    [("page", 0), ("page_size", 0), ("page_size", 101)],
)
async def test_list_rejects_invalid_pagination(
    db_session: AsyncSession,
    parameter: str,
    value: int,
) -> None:
    owner, station = await create_owner_and_station(db_session, "list-validation")

    async with api_client(db_session, actor(owner.id, "station_owner")) as client:
        response = await client.get(
            f"/api/v1/stations/{station.id}/charge-points",
            params={parameter: value},
        )

    assert response.status_code == 422
