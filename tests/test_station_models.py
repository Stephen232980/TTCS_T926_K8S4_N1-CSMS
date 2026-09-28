from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.identity.models import User
from src.modules.stations.models import Station


def test_station_model_default_status() -> None:
    station = Station(
        owner_id=uuid4(),
        name="Trạm Sạc Trung Tâm",
        address="123 Nguyễn Huệ, Quận 1, TP.HCM",
        latitude=Decimal("10.773100"),
        longitude=Decimal("106.703200"),
    )

    assert station.status == "inactive"
    assert station.name == "Trạm Sạc Trung Tâm"
    assert station.address == "123 Nguyễn Huệ, Quận 1, TP.HCM"
    assert station.latitude == Decimal("10.773100")
    assert station.longitude == Decimal("106.703200")


def test_station_table_indexes_and_foreign_keys() -> None:
    index_names = {idx.name for idx in Station.__table__.indexes}
    assert "ix_stations_owner_id" in index_names

    owner_index = next(
        idx for idx in Station.__table__.indexes if idx.name == "ix_stations_owner_id"
    )
    indexed_columns = [col.name for col in owner_index.columns]
    assert indexed_columns == ["owner_id"]
    assert not owner_index.unique

    fk = next(iter(Station.__table__.foreign_keys))
    assert fk.target_fullname == "users.id"
    assert fk.ondelete == "RESTRICT"


@pytest.mark.asyncio
async def test_station_creation_persists_in_database(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="station-owner-test@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Sạc Bến Thành",
        address="Số 1 Lê Lợi, Bến Thành, Quận 1",
        latitude=Decimal("10.771900"),
        longitude=Decimal("106.698300"),
    )
    db_session.add(station)
    await db_session.flush()

    query = (
        select(Station)
        .options(selectinload(Station.owner))
        .where(Station.id == station.id)
    )
    result = await db_session.execute(query)
    persisted_station = result.scalar_one()

    assert persisted_station.id == station.id
    assert persisted_station.owner_id == owner.id
    assert persisted_station.owner.id == owner.id
    assert persisted_station.name == "Trạm Sạc Bến Thành"
    assert persisted_station.status == "inactive"


@pytest.mark.asyncio
async def test_delete_station_owner_blocked_by_foreign_key(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="blocked-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Không Thể Mồ Côi",
        address="456 Hai Bà Trưng, Quận 3",
        latitude=Decimal("10.789000"),
        longitude=Decimal("106.692000"),
    )
    db_session.add(station)
    await db_session.flush()

    await db_session.delete(owner)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_station_invalid_latitude_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="latitude-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    invalid_station = Station(
        owner_id=owner.id,
        name="Trạm Toạ Độ Sai Latitude",
        address="Địa chỉ mẫu",
        latitude=Decimal("95.000000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(invalid_station)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_station_invalid_longitude_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="longitude-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    invalid_station = Station(
        owner_id=owner.id,
        name="Trạm Toạ Độ Sai Longitude",
        address="Địa chỉ mẫu",
        latitude=Decimal("10.700000"),
        longitude=Decimal("190.000000"),
    )
    db_session.add(invalid_station)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_station_invalid_status_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="status-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    invalid_station = Station(
        owner_id=owner.id,
        name="Trạm Trạng Thái Sai",
        address="Địa chỉ mẫu",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
        status="broken_status",
    )
    db_session.add(invalid_station)

    with pytest.raises(IntegrityError):
        await db_session.flush()
