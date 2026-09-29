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
from src.modules.stations.models import ChargePoint, Station
from src.modules.stations.repository import StationRepository
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


async def create_charge_point(db_session: AsyncSession, code: str) -> ChargePoint:
    owner = User(
        email=f"availability-{uuid4()}@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Tram kiem tra ma tru",
        address="Dia chi kiem tra",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()

    charge_point = ChargePoint(station_id=station.id, code=code)
    db_session.add(charge_point)
    await db_session.flush()
    return charge_point


@pytest.mark.asyncio
async def test_repository_checks_charge_point_code_globally(
    db_session: AsyncSession,
) -> None:
    await create_charge_point(db_session, "CP-GLOBAL-001")
    repository = StationRepository(db_session)

    assert not await repository.is_charge_point_code_available("CP-GLOBAL-001")
    assert await repository.is_charge_point_code_available("CP-GLOBAL-002")


@pytest.mark.asyncio
async def test_owner_checks_available_code_through_http(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with charge_point_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/charge-points/code-availability",
            params={"code": "  CP-AVAILABLE-001  "},
        )

    assert response.status_code == 200
    assert response.json() == {
        "code": "CP-AVAILABLE-001",
        "available": True,
    }


@pytest.mark.asyncio
async def test_owner_sees_code_from_another_station_as_unavailable(
    db_session: AsyncSession,
) -> None:
    await create_charge_point(db_session, "CP-EXISTING-001")
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with charge_point_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/charge-points/code-availability",
            params={"code": "CP-EXISTING-001"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "code": "CP-EXISTING-001",
        "available": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["", " ", "x" * 65])
async def test_code_availability_rejects_invalid_code(
    db_session: AsyncSession,
    code: str,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"station_owner"}),
    )

    async with charge_point_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/charge-points/code-availability",
            params={"code": code},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_driver_cannot_check_code_availability(
    db_session: AsyncSession,
) -> None:
    actor = CurrentActor(
        user_id=uuid4(),
        roles=frozenset({"driver"}),
    )

    async with charge_point_api_client(db_session, actor) as client:
        response = await client.get(
            "/api/v1/charge-points/code-availability",
            params={"code": "CP-DENIED-001"},
        )

    assert response.status_code == 403
