"""Read-only connection/boot view for operators and owners."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles, build_actor_scope
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/ocpp/connections",
    tags=["OCPP monitoring"],
    dependencies=[Depends(authorize_request)],
)


class MonitorQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class ConnectionResponse(BaseModel):
    id: UUID
    code: str
    station_name: str
    connected: bool
    boot_accepted: bool
    connected_at: datetime | None
    last_boot_at: datetime | None
    vendor: str | None
    model: str | None
    firmware_version: str | None


class MonitorResponse(BaseModel):
    items: list[ConnectionResponse]
    total: int
    page: int
    total_pages: int


@router.get("", response_model=MonitorResponse)
@allow_roles("station_owner", "operator", "admin")
async def list_connections(
    query: Annotated[MonitorQuery, Query()],
    actor: CurrentActorDependency,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MonitorResponse:
    scope = build_actor_scope(actor)
    statement = (
        select(ChargePoint, Station.name)
        .join(Station)
        .where(ChargePoint.archived_at.is_(None), Station.archived_at.is_(None))
    )
    if scope.owner_id is not None:
        statement = statement.where(Station.owner_id == scope.owner_id)
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    rows = (
        await session.execute(
            statement.order_by(ChargePoint.code, ChargePoint.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    ).all()
    connections = await ocpp_connections.snapshot()
    items = []
    for charge_point, station_name in rows:
        connection = connections.get(charge_point.id)
        items.append(
            ConnectionResponse(
                id=charge_point.id,
                code=charge_point.code,
                station_name=station_name,
                connected=connection is not None,
                boot_accepted=connection.boot_accepted if connection else False,
                connected_at=connection.connected_at if connection else None,
                last_boot_at=charge_point.last_boot_at,
                vendor=charge_point.vendor,
                model=charge_point.model,
                firmware_version=charge_point.firmware_version,
            )
        )
    return MonitorResponse(
        items=items,
        total=total,
        page=query.page,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )
