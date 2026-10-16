"""Bounded public projections, with no per-station database round trips."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.models import ChargingSession
from src.modules.ocpp.monitoring import expired
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.reservations.models import ReservationCapability
from src.modules.reservations.service import holds_connector
from src.modules.stations.models import ChargePoint, Connector, Station


def available_connector(now: datetime) -> ColumnElement[bool]:
    occupied = exists().where(
        ChargingSession.connector_id == Connector.id,
        or_(
            ChargingSession.ended_at.is_(None),
            (ChargingSession.billing_lifecycle_version == 1)
            & ChargingSession.connector_released_at.is_(None),
        ),
    )
    pending = exists().where(
        DriverStartRequest.connector_id == Connector.id,
        DriverStartRequest.status.in_(("Pending", "Accepted")),
        DriverStartRequest.lease_until > now,
    )
    return (
        (ChargePoint.status == "online")
        & ChargePoint.last_boot_at.is_not(None)
        & ~expired(now)
        & (ChargePoint.last_seen_at <= now)
        & or_(
            ChargePoint.raw_ocpp_status.is_(None),
            ChargePoint.raw_ocpp_status != "Faulted",
        )
        & or_(ChargePoint.error_code.is_(None), ChargePoint.error_code == "NoError")
        & (Connector.status == "Available")
        & ~occupied
        & ~pending
        & ~holds_connector()
    )


async def reservation_alternatives(
    db: AsyncSession, connector: Connector, station: Station, now: datetime
) -> list[dict[str, object]]:
    """Read-only hints; admission must still recheck on the next booking."""
    if station.status != "active" or station.archived_at is not None:
        return []
    # Booking admission conservatively rejects any unresolved start intent,
    # including one whose lease elapsed; don't suggest a known blocked target.
    unresolved_start = exists().where(
        DriverStartRequest.connector_id == Connector.id,
        DriverStartRequest.status.in_(("Pending", "Accepted")),
    )
    rows = (
        await db.execute(
            select(Connector.id, ChargePoint.code, Connector.connector_number)
            .join(ChargePoint, Connector.charge_point_id == ChargePoint.id)
            .join(
                ReservationCapability,
                ReservationCapability.charge_point_id == ChargePoint.id,
            )
            .where(
                ChargePoint.station_id == station.id,
                ChargePoint.archived_at.is_(None),
                Connector.archived_at.is_(None),
                Connector.id != connector.id,
                Connector.connector_type == connector.connector_type,
                Connector.current_type == connector.current_type,
                available_connector(now),
                ~unresolved_start,
                ReservationCapability.supported.is_(True),
                ReservationCapability.checked_at.is_not(None),
                ReservationCapability.boot_at == ChargePoint.last_boot_at,
            )
            .order_by(ChargePoint.code, Connector.connector_number, Connector.id)
            .limit(3)
        )
    ).all()
    return [
        {
            "connector_id": str(row.id),
            "charge_point_code": row.code,
            "connector_number": row.connector_number,
        }
        for row in rows
    ]


async def summaries(
    db: AsyncSession, stations: list[Station], now: datetime
) -> dict[UUID, dict[str, object]]:
    if not stations:
        return {}
    ids = [station.id for station in stations]
    rows = (
        await db.execute(
            select(
                ChargePoint.station_id,
                Connector,
                available_connector(now).label("available"),
                (
                    (ReservationCapability.supported == True)
                    & ReservationCapability.checked_at.is_not(None)
                    & (ReservationCapability.boot_at == ChargePoint.last_boot_at)
                ).label("reservation_supported"),
            )
            .join(ChargePoint, Connector.charge_point_id == ChargePoint.id)
            .outerjoin(
                ReservationCapability,
                ReservationCapability.charge_point_id == ChargePoint.id,
            )
            .where(
                ChargePoint.station_id.in_(ids),
                ChargePoint.archived_at.is_(None),
                Connector.archived_at.is_(None),
            )
            .order_by(ChargePoint.station_id, Connector.connector_type, Connector.id)
        )
    ).all()
    result: dict[UUID, dict[str, object]] = {
        station.id: {
            "available_connectors": 0,
            "total_connectors": 0,
            "connectors": [],
            "energy_rate_vnd_per_kwh": None,
            "idle_rate_vnd_per_minute": None,
            "grace_minutes": None,
        }
        for station in stations
    }
    for station_id, connector, free, reservation_supported in rows:
        projection = result[station_id]
        projection["total_connectors"] = int(projection["total_connectors"]) + 1  # type: ignore[call-overload]
        projection["available_connectors"] = int(
            projection["available_connectors"]
        ) + int(bool(free))  # type: ignore[call-overload]
        details = projection["connectors"]
        assert isinstance(details, list)
        details.append(
            {
                "id": connector.id,
                "connector_type": connector.connector_type,
                "current_type": connector.current_type,
                "max_power_kw": connector.max_power_kw,
                "available": bool(free),
                "reservation_supported": bool(reservation_supported),
            }
        )
    effective = (
        select(
            Tariff.id,
            Tariff.station_id,
            Tariff.idle_rate_vnd_per_minute,
            Tariff.grace_minutes,
            func.row_number()
            .over(
                partition_by=Tariff.station_id,
                order_by=Tariff.effective_from.desc(),
            )
            .label("rank"),
        )
        .join(Station, Station.id == Tariff.station_id)
        .where(
            Tariff.station_id.in_(ids),
            Tariff.effective_from
            <= cast(func.timezone(Station.timezone, literal(now)), Date),
        )
        .subquery()
    )
    prices = (
        await db.execute(
            select(effective, TariffBand)
            .join(TariffBand, TariffBand.tariff_id == effective.c.id)
            .where(effective.c.rank == 1)
        )
    ).all()
    minutes = {
        station.id: now.astimezone(ZoneInfo(station.timezone)).hour * 60
        + now.astimezone(ZoneInfo(station.timezone)).minute
        for station in stations
    }
    for row in prices:
        band = row[-1]
        station_id = row.station_id
        if band.start_min <= minutes[station_id] < band.end_min:
            result[station_id].update(
                energy_rate_vnd_per_kwh=band.energy_rate_vnd_per_kwh,
                idle_rate_vnd_per_minute=row.idle_rate_vnd_per_minute,
                grace_minutes=row.grace_minutes,
            )
    return result
