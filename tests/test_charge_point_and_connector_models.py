from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.models import User
from src.modules.stations.models import (
    ChargePoint,
    Connector,
    ConnectorError,
    Station,
)


def test_charge_point_model_fields_and_defaults() -> None:
    charge_point = ChargePoint(
        station_id=uuid4(),
        code="CP-TEST-001",
        name="Tru sac so 1",
    )

    assert charge_point.code == "CP-TEST-001"
    assert charge_point.name == "Tru sac so 1"

    status_column = ChargePoint.__table__.c.status
    assert status_column.default is not None
    assert status_column.default.arg == "offline"
    assert status_column.server_default is not None
    assert status_column.server_default.arg == "offline"


def test_charge_point_code_is_normalized_and_has_operational_fields() -> None:
    charge_point = ChargePoint(
        station_id=uuid4(),
        code="  cp-test-001  ",
        vendor="Open Charge Alliance",
        model="Simulator",
        firmware_version="1.0.0",
    )

    assert charge_point.code == "cp-test-001"
    assert charge_point.vendor == "Open Charge Alliance"
    assert charge_point.model == "Simulator"
    assert charge_point.firmware_version == "1.0.0"


def test_connector_model_fields_and_unknown_default() -> None:
    connector = Connector(
        charge_point_id=uuid4(),
        connector_number=1,
    )

    assert connector.connector_number == 1

    status_column = Connector.__table__.c.status
    assert status_column.default is not None
    assert status_column.default.arg == "unknown"
    assert status_column.server_default is not None
    assert status_column.server_default.arg == "unknown"


def test_charge_point_table_indexes_and_foreign_key() -> None:
    table = cast(Table, ChargePoint.__table__)
    code_index = next(
        index for index in table.indexes if str(index.name) == "ix_charge_points_code"
    )
    assert [column.name for column in code_index.columns] == ["code"]
    assert code_index.unique

    station_index = next(
        index
        for index in table.indexes
        if str(index.name) == "ix_charge_points_station_id"
    )
    assert [column.name for column in station_index.columns] == ["station_id"]
    assert not station_index.unique

    station_fk = next(iter(table.foreign_keys))
    assert station_fk.target_fullname == "stations.id"
    assert station_fk.ondelete == "RESTRICT"


def test_connector_table_constraints_and_foreign_key() -> None:
    table = cast(Table, Connector.__table__)
    charge_point_index = next(
        index
        for index in table.indexes
        if str(index.name) == "ix_connectors_charge_point_id"
    )
    assert [column.name for column in charge_point_index.columns] == ["charge_point_id"]
    assert not charge_point_index.unique

    unique_constraints = {
        constraint.name: constraint
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    connector_number_unique = unique_constraints["uq_connectors_cp_id_connector_number"]
    assert [column.name for column in connector_number_unique.columns] == [
        "charge_point_id",
        "connector_number",
    ]

    check_constraints = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_connectors_connector_number_gte_1" in check_constraints

    charge_point_fk = next(iter(table.foreign_keys))
    assert charge_point_fk.target_fullname == "charge_points.id"
    assert charge_point_fk.ondelete == "RESTRICT"


def test_connector_supports_raw_status_and_electrical_metadata() -> None:
    connector = Connector(
        charge_point_id=uuid4(),
        connector_number=1,
        raw_ocpp_status="SuspendedEVSE",
        connector_type="CCS2",
        max_power_kw=Decimal("150.000"),
        current_type="DC",
        voltage=Decimal("800.00"),
        amperage=Decimal("187.50"),
    )

    assert connector.raw_ocpp_status == "SuspendedEVSE"
    assert connector.connector_type == "CCS2"
    assert connector.max_power_kw == Decimal("150.000")
    assert connector.current_type == "DC"


def test_connector_error_has_history_index_and_restrictive_foreign_key() -> None:
    table = cast(Table, ConnectorError.__table__)
    history_index = next(
        index
        for index in table.indexes
        if str(index.name) == "ix_connector_errors_connector_id_occurred_at"
    )
    assert [column.name for column in history_index.columns] == [
        "connector_id",
        "occurred_at",
    ]

    connector_fk = next(iter(table.foreign_keys))
    assert connector_fk.target_fullname == "connectors.id"
    assert connector_fk.ondelete == "RESTRICT"


async def _create_station(
    db_session: AsyncSession,
    *,
    email: str,
    name: str,
) -> Station:
    owner = User(
        email=email,
        password_hash="hashed-test-password",
    )
    db_session.add(owner)
    await db_session.flush()

    station = Station(
        owner_id=owner.id,
        name=name,
        address="Dia chi kiem thu",
        latitude=Decimal("10.700000"),
        longitude=Decimal("106.700000"),
    )
    db_session.add(station)
    await db_session.flush()
    return station


@pytest.mark.asyncio
async def test_duplicate_charge_point_code_rejected_globally(
    db_session: AsyncSession,
) -> None:
    first_station = await _create_station(
        db_session,
        email="cp-code-first-owner@example.com",
        name="Tram thu nhat",
    )
    second_station = await _create_station(
        db_session,
        email="cp-code-second-owner@example.com",
        name="Tram thu hai",
    )

    db_session.add(
        ChargePoint(
            station_id=first_station.id,
            code="CP-GLOBAL-UNIQUE-001",
        )
    )
    await db_session.flush()

    db_session.add(
        ChargePoint(
            station_id=second_station.id,
            code="cp-global-unique-001",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_connector_defaults_to_unknown_after_persistence(
    db_session: AsyncSession,
) -> None:
    station = await _create_station(
        db_session,
        email="connector-default-owner@example.com",
        name="Tram thu default dau noi",
    )
    charge_point = ChargePoint(
        station_id=station.id,
        code="CP-CONNECTOR-DEFAULT-001",
    )
    db_session.add(charge_point)
    await db_session.flush()

    connector = Connector(
        charge_point_id=charge_point.id,
        connector_number=1,
    )
    db_session.add(connector)
    await db_session.flush()
    await db_session.refresh(connector)

    assert connector.status == "unknown"


@pytest.mark.asyncio
async def test_duplicate_connector_number_in_same_charge_point_rejected(
    db_session: AsyncSession,
) -> None:
    station = await _create_station(
        db_session,
        email="connector-duplicate-owner@example.com",
        name="Tram thu trung dau noi",
    )
    charge_point = ChargePoint(
        station_id=station.id,
        code="CP-CONNECTOR-DUPLICATE-001",
    )
    db_session.add(charge_point)
    await db_session.flush()

    db_session.add(
        Connector(
            charge_point_id=charge_point.id,
            connector_number=1,
        )
    )
    await db_session.flush()

    db_session.add(
        Connector(
            charge_point_id=charge_point.id,
            connector_number=1,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_connector_number_less_than_one_rejected(
    db_session: AsyncSession,
) -> None:
    station = await _create_station(
        db_session,
        email="connector-number-owner@example.com",
        name="Tram thu so dau noi",
    )
    charge_point = ChargePoint(
        station_id=station.id,
        code="CP-CONNECTOR-NUMBER-001",
    )
    db_session.add(charge_point)
    await db_session.flush()

    db_session.add(
        Connector(
            charge_point_id=charge_point.id,
            connector_number=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
