import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import get_db_session


@asynccontextmanager
async def charge_point_api_client(
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


async def create_station(
    db_session: AsyncSession,
    *,
    owner: User,
    name: str = "Tram tao tru sac",
) -> Station:
    station = Station(
        owner_id=owner.id,
        name=name,
        address="Dia chi tao tru sac",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()
    return station


async def create_owner(db_session: AsyncSession, prefix: str) -> User:
    owner = User(
        email=f"{prefix}-{uuid4()}@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()
    return owner


def owner_actor(owner_id: UUID) -> CurrentActor:
    return CurrentActor(
        user_id=owner_id,
        roles=frozenset({"station_owner"}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_count", [1, 4])
async def test_owner_creates_charge_point_with_requested_connectors(
    db_session: AsyncSession,
    connector_count: int,
) -> None:
    owner = await create_owner(db_session, "charge-point-create")
    station = await create_station(db_session, owner=owner)
    code = f"CP-CREATE-{connector_count}-{uuid4()}"

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.post(
            f"/api/v1/stations/{station.id}/charge-points",
            json={"code": f"  {code}  ", "connector_count": connector_count},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["station_id"] == str(station.id)
    assert payload["code"] == code
    assert payload["name"] is None
    assert payload["status"] == "offline"
    assert [item["connector_number"] for item in payload["connectors"]] == list(
        range(1, connector_count + 1)
    )
    assert {item["status"] for item in payload["connectors"]} == {"unknown"}

    charge_point = await db_session.scalar(
        select(ChargePoint).where(ChargePoint.code == code)
    )
    assert charge_point is not None
    connector_total = await db_session.scalar(
        select(func.count(Connector.id)).where(
            Connector.charge_point_id == charge_point.id
        )
    )
    assert connector_total == connector_count


@pytest.mark.asyncio
async def test_duplicate_code_is_rejected_when_posted_directly(
    db_session: AsyncSession,
) -> None:
    owner = await create_owner(db_session, "charge-point-duplicate")
    station = await create_station(db_session, owner=owner)
    code = f"CP-DUPLICATE-{uuid4()}"
    request = {"code": code, "connector_count": 2}

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        first_response = await client.post(
            f"/api/v1/stations/{station.id}/charge-points",
            json=request,
        )
        duplicate_response = await client.post(
            f"/api/v1/stations/{station.id}/charge-points",
            json=request,
        )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {"detail": "charge_point_code_already_exists"}
    charge_point_total = await db_session.scalar(
        select(func.count(ChargePoint.id)).where(ChargePoint.code == code)
    )
    assert charge_point_total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("connector_count", [0, 5])
async def test_create_charge_point_rejects_invalid_connector_count(
    db_session: AsyncSession,
    connector_count: int,
) -> None:
    owner = await create_owner(db_session, "charge-point-validation")
    station = await create_station(db_session, owner=owner)

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.post(
            f"/api/v1/stations/{station.id}/charge-points",
            json={"code": f"CP-INVALID-{uuid4()}", "connector_count": connector_count},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_charge_point_for_missing_station_returns_404(
    db_session: AsyncSession,
) -> None:
    owner = await create_owner(db_session, "charge-point-missing")

    async with charge_point_api_client(db_session, owner_actor(owner.id)) as client:
        response = await client.post(
            f"/api/v1/stations/{uuid4()}/charge-points",
            json={"code": f"CP-MISSING-{uuid4()}", "connector_count": 2},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "resource_not_found"}


@pytest.mark.asyncio
async def test_cross_owner_charge_point_create_returns_403_and_logs(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a = await create_owner(db_session, "charge-point-owner-a")
    owner_b = await create_owner(db_session, "charge-point-owner-b")
    station_b = await create_station(db_session, owner=owner_b)
    caplog.set_level(logging.WARNING, logger="csms.security")

    async with charge_point_api_client(db_session, owner_actor(owner_a.id)) as client:
        response = await client.post(
            f"/api/v1/stations/{station_b.id}/charge-points",
            json={"code": f"CP-DENIED-{uuid4()}", "connector_count": 2},
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "permission_denied"}
    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text


@pytest.mark.asyncio
async def test_driver_cannot_create_charge_point(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"driver"}),
    )

    async with charge_point_api_client(db_session, actor) as client:
        response = await client.post(
            f"/api/v1/stations/{uuid4()}/charge-points",
            json={"code": f"CP-DRIVER-{uuid4()}", "connector_count": 2},
        )

    assert response.status_code == 403
