from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Connector, Station


def test_charge_point_and_connector_model_defaults() -> None:
    cp = ChargePoint(
        station_id=uuid4(),
        code="CP-TEST-001",
        name="Trụ sạc số 1",
    )
    assert cp.status == "offline"
    assert cp.code == "CP-TEST-001"
    assert cp.name == "Trụ sạc số 1"

    conn = Connector(
        charge_point_id=cp.id,
        connector_number=1,
    )
    assert conn.status == "Available"
    assert conn.connector_number == 1


def test_charge_point_and_connector_table_constraints() -> None:
    cp_indexes = {idx.name for idx in ChargePoint.__table__.indexes}
    assert "ix_charge_points_code" in cp_indexes
    assert "ix_charge_points_station_id" in cp_indexes

    code_index = next(
        idx
        for idx in ChargePoint.__table__.indexes
        if idx.name == "ix_charge_points_code"
    )
    assert code_index.unique

    conn_indexes = {idx.name for idx in Connector.__table__.indexes}
    assert "ix_connectors_charge_point_id" in conn_indexes

    conn_uqs = {uq.name for uq in Connector.__table__.constraints if uq.name}
    assert "uq_connectors_cp_id_connector_number" in conn_uqs


@pytest.mark.asyncio
async def test_duplicate_charge_point_code_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="cp-code-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Kiểm Thử Code Trụ",
        address="789 Điện Biên Phủ, Bình Thạnh",
        latitude=Decimal("10.800000"),
        longitude=Decimal("106.710000"),
    )
    db_session.add(station)
    await db_session.flush()

    first_cp = ChargePoint(
        station_id=station.id,
        code="CP-DUPLICATE-001",
        name="Trụ Sạc Đầu Tiên",
    )
    db_session.add(first_cp)
    await db_session.flush()

    duplicate_cp = ChargePoint(
        station_id=station.id,
        code="CP-DUPLICATE-001",
        name="Trụ Sạc Trùng Mã",
    )
    db_session.add(duplicate_cp)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_duplicate_connector_number_in_same_charge_point_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="conn-dup-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Kiểm Thử Connector Trùng",
        address="100 Võ Văn Kiệt, Quận 1",
        latitude=Decimal("10.760000"),
        longitude=Decimal("106.690000"),
    )
    db_session.add(station)
    await db_session.flush()

    cp = ChargePoint(
        station_id=station.id,
        code="CP-CONN-DUP-001",
        name="Trụ Sạc 2 Cổng",
    )
    db_session.add(cp)
    await db_session.flush()

    first_conn = Connector(
        charge_point_id=cp.id,
        connector_number=1,
    )
    db_session.add(first_conn)
    await db_session.flush()

    duplicate_conn = Connector(
        charge_point_id=cp.id,
        connector_number=1,
    )
    db_session.add(duplicate_conn)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_connector_number_less_than_1_rejected(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="conn-number-gte1-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Kiểm Thử Connector >= 1",
        address="200 Nguyễn Thị Minh Khai, Quận 3",
        latitude=Decimal("10.775000"),
        longitude=Decimal("106.685000"),
    )
    db_session.add(station)
    await db_session.flush()

    cp = ChargePoint(
        station_id=station.id,
        code="CP-CONN-ZERO-001",
        name="Trụ Sạc Thử Connector 0",
    )
    db_session.add(cp)
    await db_session.flush()

    invalid_conn = Connector(
        charge_point_id=cp.id,
        connector_number=0,
    )
    db_session.add(invalid_conn)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_cascade_deletion_deletes_child_connectors(
    db_session: AsyncSession,
) -> None:
    owner = User(
        email="cascade-cp-test-owner@example.com",
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name="Trạm Kiểm Thử Cascade",
        address="300 Lý Tự Trọng, Quận 1",
        latitude=Decimal("10.772000"),
        longitude=Decimal("106.695000"),
    )
    db_session.add(station)
    await db_session.flush()

    cp = ChargePoint(
        station_id=station.id,
        code="CP-CASCADE-001",
        name="Trụ Xoá Theo Trạm",
    )
    db_session.add(cp)
    await db_session.flush()

    conn = Connector(
        charge_point_id=cp.id,
        connector_number=1,
    )
    db_session.add(conn)
    await db_session.flush()

    await db_session.delete(cp)
    await db_session.flush()

    conn_query = select(Connector).where(Connector.id == conn.id)
    res = await db_session.execute(conn_query)
    assert res.scalar_one_or_none() is None
