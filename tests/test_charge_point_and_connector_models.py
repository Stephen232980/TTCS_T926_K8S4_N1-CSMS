from typing import cast
from uuid import uuid4

from sqlalchemy import CheckConstraint, Table, UniqueConstraint

from src.modules.stations.models import ChargePoint, Connector


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
    assert station_fk.ondelete == "CASCADE"


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
    assert charge_point_fk.ondelete == "CASCADE"
