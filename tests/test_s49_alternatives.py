"""S-49 conflict recovery uses real PostgreSQL admission and public hints."""

# ruff: noqa: F401, F811
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.modules.ocpp.monitoring import database_time
from src.modules.reservations.models import (
    Reservation,
    ReservationCapability,
    ReservationCommand,
)
from src.modules.stations.discovery import reservation_alternatives
from src.modules.stations.models import ChargePoint, Connector
from tests.test_flat_tariff_api import api_db, committed_tariff_db
from tests.test_g5_reservations import book, fleet, request, reservation_fleet


async def add_connector(db, point, original, number):
    row = Connector(
        charge_point_id=point.id,
        connector_number=number,
        status="Available",
        connector_type=original.connector_type,
        current_type=original.current_type,
        max_power_kw=22,
    )
    db.add(row)
    await db.flush()
    return row


async def test_conflict_returns_three_ordered_public_hints_without_new_hold(
    reservation_fleet,
):
    factory, _, point, connector, _, other, *_ = reservation_fleet
    async with factory() as db, db.begin():
        candidates = [
            await add_connector(db, point, connector, n) for n in [5, 3, 2, 4]
        ]
    await book(reservation_fleet, actor=other.id)
    result = await request(
        "POST", body={"request_id": str(uuid4()), "connector_id": str(connector.id)}
    )
    assert result.status_code == 409
    detail = result.json()["detail"]
    assert detail["reason"] == "connector_reserved"
    assert detail["generated_at"]
    assert detail["alternatives"] == [
        {
            "connector_id": str(row.id),
            "charge_point_code": point.code,
            "connector_number": row.connector_number,
        }
        for row in sorted(candidates, key=lambda row: row.connector_number)[:3]
    ]
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Reservation)) == 1
        assert (
            await db.scalar(select(func.count()).select_from(ReservationCommand)) == 1
        )
    # Hints do not reserve: another driver can take one before a follow-up request.
    async with factory() as db, db.begin():
        chosen = await db.get(Connector, candidates[0].id)
        chosen.status = "Faulted"
    async with factory() as db:
        hints = await reservation_alternatives(
            db, connector, reservation_fleet[1], await database_time(db)
        )
        assert str(candidates[0].id) not in {str(row["connector_id"]) for row in hints}


@pytest.mark.parametrize(
    "blocked",
    [
        "wrong_type",
        "wrong_current",
        "archived",
        "faulted",
        "unsupported",
        "old_boot",
        "offline",
        "stale",
        "other_station",
    ],
)
async def test_hints_exclude_incompatible_or_unavailable_candidates(
    reservation_fleet, blocked
):
    factory, station, point, connector, *_ = reservation_fleet
    async with factory() as db, db.begin():
        candidate = await add_connector(db, point, connector, 2)
        live_point = await db.get(ChargePoint, point.id)
        capability = await db.get(ReservationCapability, point.id)
        if blocked == "wrong_type":
            candidate.connector_type = "CCS2"
        elif blocked == "wrong_current":
            candidate.current_type = "DC"
        elif blocked == "archived":
            candidate.archived_at = await database_time(db)
        elif blocked == "faulted":
            candidate.status = "Faulted"
        elif blocked == "unsupported":
            capability.supported = False
        elif blocked == "old_boot":
            capability.boot_at -= timedelta(minutes=1)
        elif blocked == "offline":
            live_point.status = "offline"
        elif blocked == "stale":
            live_point.last_seen_at -= timedelta(hours=1)
        elif blocked == "other_station":
            # A real second station from the existing charging fixture.
            from tests.test_charging_sessions import setup

            second_station, second_point, *_ = await setup(db)
            now = await database_time(db)
            second_point.status = "online"
            second_point.last_boot_at = second_point.last_seen_at = now
            db.add(
                ReservationCapability(
                    charge_point_id=second_point.id,
                    boot_at=now,
                    supported=True,
                    checked_at=now,
                    next_attempt_at=now,
                    outcome="supported",
                )
            )
            candidate.charge_point_id = second_point.id
            assert second_station.id != station.id
    async with factory() as db:
        assert (
            await reservation_alternatives(
                db, connector, station, await database_time(db)
            )
            == []
        )


async def test_conflict_without_candidates_has_explicit_empty_hints(reservation_fleet):
    _, _, _, connector, _, other, *_ = reservation_fleet
    await book(reservation_fleet, actor=other.id)
    result = await request(
        "POST", body={"request_id": str(uuid4()), "connector_id": str(connector.id)}
    )
    assert result.status_code == 409
    assert result.json()["detail"]["alternatives"] == []


async def test_hints_exclude_an_existing_hold_on_the_alternative(reservation_fleet):
    from src.modules.reservations.service import create_reservation
    from tests.test_g5_reservations import EVIDENCE

    factory, station, point, connector, driver, *_ = reservation_fleet
    async with factory() as db, db.begin():
        candidate = await add_connector(db, point, connector, 2)
        await create_reservation(db, driver.id, uuid4(), candidate.id, None, EVIDENCE)
    async with factory() as db:
        assert (
            await reservation_alternatives(
                db, connector, station, await database_time(db)
            )
            == []
        )
