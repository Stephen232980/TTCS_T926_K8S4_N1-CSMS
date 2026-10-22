from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import AuditEvidence, CurrentActorDependency
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.ocpp.monitoring import database_time
from src.modules.reservations.models import HOLDS, Reservation
from src.modules.reservations.service import (
    cancel_reservation,
    create_reservation,
    probe_capability,
)
from src.modules.stations.discovery import reservation_alternatives
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/driver/reservations", route_class=PolicyRoute, tags=["reservations"]
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class BookingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    connector_id: UUID
    arrival_at: AwareDatetime | None = Field(
        default=None,
        description="Omit or use null for a new immediate 15-minute hold. "
        "Explicit timestamps are only accepted when replaying an existing request.",
    )
    accepted_fee_vnd: Annotated[StrictInt, Field(ge=0, le=1000000)] | None = None
    accepted_policy_version: Annotated[StrictInt, Field(ge=0)] | None = None


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class CapabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_id: UUID


async def view(
    db: AsyncSession,
    reservation: Reservation,
    context: tuple[str, str, int] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    row = (
        context
        or (
            await db.execute(
                select(Station.name, ChargePoint.code, Connector.connector_number)
                .join(ChargePoint, ChargePoint.station_id == Station.id)
                .join(Connector, Connector.charge_point_id == ChargePoint.id)
                .where(Connector.id == reservation.connector_id)
            )
        ).one()
    )
    now = observed_at or await database_time(db)
    return {
        "id": reservation.id,
        "station_id": reservation.station_id,
        "station_name": row[0],
        "connector_id": reservation.connector_id,
        "charge_point_code": row[1],
        "connector_number": row[2],
        "status": reservation.status,
        "outcome": reservation.outcome,
        "created_at": reservation.created_at,
        "arrival_at": reservation.arrival_at,
        "expires_at": reservation.expires_at,
        "updated_at": reservation.updated_at,
        "cancel_requested_at": reservation.cancel_requested_at,
        "no_show_exempt": reservation.no_show_exempt,
        "session_id": reservation.session_id,
        "no_show_fee_vnd": str(reservation.fee_vnd),
        "fee_decision": reservation.fee_decision,
        "fee_reason": reservation.fee_reason,
        "fee_ledger_id": reservation.fee_ledger_id,
        "can_cancel": reservation.status in {"active", "uncertain"}
        and now < reservation.expires_at,
        "booking_fee_vnd": 0,
        "no_show_fee_enabled": reservation.fee_vnd > 0,
    }


@router.post("", status_code=202)
@user_policy("driver.reservations.create", "own", "driver")
async def book(
    body: BookingBody,
    actor: CurrentActorDependency,
    evidence: AuditEvidence,
    db: Database,
) -> dict[str, object]:
    try:
        result = await create_reservation(
            db,
            actor.user_id,
            body.request_id,
            body.connector_id,
            body.arrival_at,
            evidence,
            body.accepted_fee_vnd,
            body.accepted_policy_version,
        )
    except HTTPException as error:
        if error.status_code != 409 or error.detail != "connector_reserved":
            raise
        connector = await db.get(Connector, body.connector_id)
        point = (
            await db.get(ChargePoint, connector.charge_point_id) if connector else None
        )
        station = await db.get(Station, point.station_id) if point else None
        now = await database_time(db)
        alternatives = (
            await reservation_alternatives(db, connector, station, now)
            if connector is not None and station is not None
            else []
        )
        raise HTTPException(
            409,
            {
                "reason": "connector_reserved",
                "alternatives": alternatives,
                "generated_at": now.isoformat(),
            },
        ) from error
    return await view(db, result)


@router.post("/capabilities", status_code=202)
@user_policy("driver.reservations.probe_capability", "own", "driver")
async def probe(body: CapabilityBody, db: Database) -> dict[str, str]:
    return await probe_capability(db, body.connector_id)


@router.get("")
@user_policy("driver.reservations.read", "own", "driver")
async def list_reservations(
    actor: CurrentActorDependency, db: Database, page: Annotated[int, Query(ge=1)] = 1
) -> dict[str, object]:
    query = select(Reservation).where(Reservation.driver_id == actor.user_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    pages = max(1, (total + 19) // 20)
    page = min(page, pages)
    rows = (
        await db.execute(
            select(
                Reservation, Station.name, ChargePoint.code, Connector.connector_number
            )
            .join(Station, Station.id == Reservation.station_id)
            .join(ChargePoint, ChargePoint.id == Reservation.charge_point_id)
            .join(Connector, Connector.id == Reservation.connector_id)
            .where(Reservation.driver_id == actor.user_id)
            .order_by(
                case((Reservation.status.in_(HOLDS), 0), else_=1),
                Reservation.created_at.desc(),
                Reservation.id,
            )
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    now = await database_time(db)
    return {
        "items": [
            await view(db, row[0], (row[1], row[2], row[3]), now) for row in rows
        ],
        "page": page,
        "total_pages": pages,
        "total": total,
        "generated_at": now,
        "refresh_after_seconds": 5,
    }


@router.get("/policy")
@user_policy("driver.reservations.policy.read", "own", "driver")
async def read_quote(connector_id: UUID, db: Database) -> dict[str, int]:
    from src.modules.reservations.policy import quote

    row = (
        await db.execute(
            select(Station)
            .join(ChargePoint)
            .join(Connector)
            .where(
                Connector.id == connector_id,
                Connector.archived_at.is_(None),
                ChargePoint.archived_at.is_(None),
                Station.archived_at.is_(None),
                Station.status == "active",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "resource_not_found")
    return await quote(db, row.id)


@router.get("/{reservation_id}")
@user_policy("driver.reservations.read_one", "own", "driver")
async def read_one(
    reservation_id: UUID, actor: CurrentActorDependency, db: Database
) -> dict[str, object]:
    row = await db.get(Reservation, reservation_id)
    if row is None:
        raise HTTPException(404, "resource_not_found")
    if row.driver_id != actor.user_id:
        raise HTTPException(403, "permission_denied")
    return await view(db, row)


@router.post("/{reservation_id}/cancel", status_code=202)
@user_policy("driver.reservations.cancel", "own", "driver")
async def cancel(
    reservation_id: UUID,
    body: CancelBody,
    actor: CurrentActorDependency,
    evidence: AuditEvidence,
    db: Database,
) -> dict[str, object]:
    result = await cancel_reservation(
        db, actor.user_id, reservation_id, body.request_id, evidence
    )
    return await view(db, result)
