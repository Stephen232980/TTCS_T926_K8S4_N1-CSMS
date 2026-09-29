from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.identity.models import User
from src.modules.stations.models import Station
from src.modules.stations.repository import StationRepository


@pytest.mark.asyncio
async def test_list_stations_filters_by_owner_scope(
    db_session: AsyncSession,
) -> None:
    owner_a = User(
        email="station-repository-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-repository-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_a = Station(
        owner_id=owner_a.id,
        name="Trạm của chủ A",
        address="Địa chỉ A",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm của chủ B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add_all([station_a, station_b])
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner_a.id, owner_id=owner_a.id)

    stations = await repository.list_stations(scope)

    assert {station.id for station in stations} == {station_a.id}


@pytest.mark.asyncio
async def test_list_stations_returns_all_for_global_scope(
    db_session: AsyncSession,
) -> None:
    owner_a = User(
        email="station-repository-global-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-repository-global-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_a = Station(
        owner_id=owner_a.id,
        name="Trạm toàn cục A",
        address="Địa chỉ A",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm toàn cục B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add_all([station_a, station_b])
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner_a.id, owner_id=None)

    stations = await repository.list_stations(scope)

    assert {station.id for station in stations} == {
        station_a.id,
        station_b.id,
    }
