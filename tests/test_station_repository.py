import logging
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.identity.models import User
from src.modules.stations.exceptions import StationOwnershipDeniedError
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


@pytest.mark.asyncio
async def test_get_station_by_id_returns_station_for_owner(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-get-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm được phép truy cập",
        address="Địa chỉ hợp lệ",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner.id, owner_id=owner.id)

    result = await repository.get_station_by_id(station.id, scope)

    assert result is not None
    assert result.id == station.id


@pytest.mark.asyncio
async def test_get_station_by_id_returns_none_when_station_does_not_exist(
    db_session: AsyncSession,
) -> None:
    actor_id = uuid4()
    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=actor_id, owner_id=actor_id)

    result = await repository.get_station_by_id(uuid4(), scope)

    assert result is None


@pytest.mark.asyncio
async def test_get_station_by_id_denies_cross_owner_and_logs_security_event(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner_a = User(
        email="station-cross-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-cross-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    station_b = Station(
        owner_id=owner_b.id,
        name="Trạm của chủ B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add(station_b)
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner_a.id, owner_id=owner_a.id)
    caplog.set_level(logging.WARNING, logger="csms.security")

    with pytest.raises(StationOwnershipDeniedError):
        await repository.get_station_by_id(station_b.id, scope)

    assert "cross_owner_station_access_denied" in caplog.text
    assert str(owner_a.id) in caplog.text
    assert str(station_b.id) in caplog.text
    assert owner_a.email not in caplog.text
    assert owner_b.email not in caplog.text


@pytest.mark.asyncio
async def test_list_stations_page_applies_owner_scope_and_pagination(
    db_session: AsyncSession,
) -> None:
    owner_a = User(
        email="station-page-owner-a@example.com",
        password_hash="hashed-password",
    )
    owner_b = User(
        email="station-page-owner-b@example.com",
        password_hash="hashed-password",
    )
    db_session.add_all([owner_a, owner_b])
    await db_session.flush()

    owner_a_stations = [
        Station(
            owner_id=owner_a.id,
            name=f"Trạm phân trang A{index}",
            address=f"Địa chỉ A{index}",
            latitude=Decimal("10.700000"),
            longitude=Decimal("106.700000"),
        )
        for index in range(1, 4)
    ]
    owner_b_station = Station(
        owner_id=owner_b.id,
        name="Trạm phân trang B",
        address="Địa chỉ B",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.800000"),
    )
    db_session.add_all([*owner_a_stations, owner_b_station])
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner_a.id, owner_id=owner_a.id)

    page_one = await repository.list_stations_page(
        scope,
        page=1,
        page_size=2,
        status=None,
        search=None,
    )
    page_two = await repository.list_stations_page(
        scope,
        page=2,
        page_size=2,
        status=None,
        search=None,
    )

    returned_ids = {station.id for station in [*page_one.items, *page_two.items]}

    assert page_one.total == 3
    assert page_two.total == 3
    assert len(page_one.items) == 2
    assert len(page_two.items) == 1
    assert returned_ids == {station.id for station in owner_a_stations}
    assert owner_b_station.id not in returned_ids


@pytest.mark.asyncio
async def test_list_stations_page_applies_status_and_search_filters(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-page-filter-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    matching_station = Station(
        owner_id=owner.id,
        name="Trạm T09Unique Trung Tâm",
        address="Quận 1",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
        status="active",
    )
    inactive_station = Station(
        owner_id=owner.id,
        name="Trạm T09Unique Dự Phòng",
        address="Quận 1",
        latitude=Decimal("10.710000"),
        longitude=Decimal("106.710000"),
        status="inactive",
    )
    unrelated_station = Station(
        owner_id=owner.id,
        name="Trạm Ngoại Thành",
        address="Quận 9",
        latitude=Decimal("10.720000"),
        longitude=Decimal("106.720000"),
        status="active",
    )
    db_session.add_all(
        [
            matching_station,
            inactive_station,
            unrelated_station,
        ]
    )
    await db_session.flush()

    repository = StationRepository(db_session)
    scope = ActorScope(actor_id=owner.id, owner_id=owner.id)

    result = await repository.list_stations_page(
        scope,
        page=1,
        page_size=20,
        status="active",
        search="t09unique",
    )

    assert result.total == 1
    assert [station.id for station in result.items] == [matching_station.id]


@pytest.mark.asyncio
async def test_create_station_persists_owner_and_default_status(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-create-owner@example.com",
        password_hash="hashed-password",
    )
    db_session.add(owner)
    await db_session.flush()

    repository = StationRepository(db_session)

    station = await repository.create_station(
        owner_id=owner.id,
        name="Trạm mới",
        address="123 Nguyễn Huệ, Quận 1",
        latitude=Decimal("10.773100"),
        longitude=Decimal("106.703200"),
    )

    await db_session.refresh(station)

    assert station.id is not None
    assert station.owner_id == owner.id
    assert station.name == "Trạm mới"
    assert station.address == "123 Nguyễn Huệ, Quận 1"
    assert station.latitude == Decimal("10.773100")
    assert station.longitude == Decimal("106.703200")
    assert station.status == "inactive"
    assert station.created_at is not None
    assert station.updated_at is not None
