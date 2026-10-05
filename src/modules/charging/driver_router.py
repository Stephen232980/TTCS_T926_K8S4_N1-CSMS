"""Driver reads are scoped by the authenticated account, never client identity."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver import remote_start, start_result
from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    AuditEvidence,
    CurrentActorDependency,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/driver",
    tags=["driver"],
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class StartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    connector_id: UUID


async def owned_session(
    session: AsyncSession, transaction: ChargingSession
) -> dict[str, object]:
    charger = await session.get(ChargePoint, transaction.charge_point_id)
    connector = await session.get(Connector, transaction.connector_id)
    station = await session.get(Station, charger.station_id) if charger else None
    latest = await session.scalar(
        select(MeterSample)
        .where(
            MeterSample.session_id == transaction.id,
            MeterSample.measurand == "Energy.Active.Import.Register",
            MeterSample.phase == "",
            MeterSample.location == "Outlet",
            MeterSample.unit == "Wh",
            MeterSample.timestamp >= transaction.started_at,
        )
        .order_by(MeterSample.timestamp.desc())
        .limit(1)
    )
    energy = transaction.energy_kwh
    if transaction.ended_at is None:
        energy = (
            max(Decimal(0), latest.value - transaction.meter_start_wh) / 1000
            if latest
            else Decimal(0)
        )
    return {
        "id": transaction.id,
        "station_name": station.name if station else "Trạm sạc",
        "charge_point_code": charger.code if charger else "",
        "connector_number": connector.connector_number if connector else None,
        "started_at": transaction.started_at,
        "ended_at": transaction.ended_at,
        "energy_kwh": energy,
        "latest_meter_at": latest.timestamp if latest else None,
        "elapsed_seconds": max(
            0,
            int(
                (
                    (transaction.ended_at or datetime.now(UTC)) - transaction.started_at
                ).total_seconds()
            ),
        ),
        "needs_attention": transaction.abnormal_since is not None
        or bool(transaction.review_reasons),
    }


@router.get("/charging/current")
@user_policy("driver.current", "own", "driver")
async def current(
    actor: CurrentActorDependency, session: Database
) -> dict[str, object]:
    transaction = await session.scalar(
        select(ChargingSession)
        .where(
            ChargingSession.driver_id == actor.user_id,
            ChargingSession.ended_at.is_(None),
        )
        .order_by(ChargingSession.started_at.desc())
        .limit(1)
    )
    request = await session.scalar(
        select(DriverStartRequest)
        .where(DriverStartRequest.driver_id == actor.user_id)
        .order_by(DriverStartRequest.created_at.desc())
        .limit(1)
    )
    return {
        "session": await owned_session(session, transaction) if transaction else None,
        "start_request": start_result(request) if request else None,
    }


@router.get("/charging/sessions/{session_id}")
@user_policy("driver.detail", "own", "driver")
async def detail(
    session_id: int, actor: CurrentActorDependency, session: Database
) -> dict[str, object]:
    transaction = await session.get(ChargingSession, session_id)
    if transaction is None:
        raise HTTPException(404, "Không tìm thấy phiên sạc.")
    if transaction.driver_id != actor.user_id:
        raise HTTPException(403, "Bạn không có quyền xem phiên sạc này.")
    return await owned_session(session, transaction)


@router.post("/charging/start")
@user_policy("driver.start", "own", "driver")
async def start(
    body: StartBody,
    actor: CurrentActorDependency,
    authorization: AuditEvidence,
    session: Database,
) -> dict[str, object]:
    await session.commit()  # Release authentication connection during the OCPP wait.
    return await remote_start(
        actor.user_id, body.request_id, body.connector_id, authorization=authorization
    )


@router.get("/stations/{station_id}/connectors")
@user_policy("driver.connectors", "own", "driver")
async def connectors(station_id: UUID, session: Database) -> dict[str, object]:
    station = await session.get(Station, station_id)
    if station is None or station.status != "active" or station.archived_at is not None:
        raise HTTPException(404, "Trạm hiện không khả dụng.")
    rows = await session.execute(
        select(Connector, ChargePoint)
        .join(ChargePoint, Connector.charge_point_id == ChargePoint.id)
        .where(
            ChargePoint.station_id == station_id,
            ChargePoint.archived_at.is_(None),
            Connector.archived_at.is_(None),
        )
        .order_by(ChargePoint.code, Connector.connector_number)
    )
    return {
        "items": [
            {
                "id": row[0].id,
                "charge_point_code": row[1].code,
                "connector_number": row[0].connector_number,
                "status": row[0].status,
            }
            for row in rows
        ]
    }
