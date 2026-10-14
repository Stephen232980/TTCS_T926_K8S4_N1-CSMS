"""Driver-facing station locations; excludes management and owner data."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.ocpp.monitoring import database_time
from src.modules.stations.discovery import summaries
from src.modules.stations.models import Station
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/driver/stations",
    tags=["driver"],
    dependencies=[Depends(authorize_request)],
)


class DiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=100)
    search: str = Field(default="", max_length=100)


class DiscoveryStation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    address: str
    latitude: float
    longitude: float
    available_connectors: int = 0
    total_connectors: int = 0
    connectors: list["DiscoveryConnector"] = Field(default_factory=list)
    energy_rate_vnd_per_kwh: int | None = None
    idle_rate_vnd_per_minute: int | None = None
    grace_minutes: int | None = None


class DiscoveryConnector(BaseModel):
    id: UUID
    connector_type: str | None
    current_type: str | None
    max_power_kw: Decimal | None
    available: bool


class DiscoveryResponse(BaseModel):
    items: list[DiscoveryStation]
    page: int
    total: int
    total_pages: int
    generated_at: datetime
    refresh_after_seconds: int = 15
    search_too_broad: bool = False


@router.get("", response_model=DiscoveryResponse)
@user_policy("driver.discover_stations", "own", "driver")
async def discover_stations(
    query: Annotated[DiscoveryQuery, Query()],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DiscoveryResponse:
    statement = select(Station).where(
        Station.status == "active", Station.archived_at.is_(None)
    )
    if query.search:
        escaped = (
            query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        statement = statement.where(
            Station.name.ilike(pattern, escape="\\")
            | Station.address.ilike(pattern, escape="\\")
        )
    total = (
        await session.scalar(select(func.count()).select_from(statement.subquery()))
        or 0
    )
    now = await database_time(session)
    if total > 500:
        return DiscoveryResponse(
            items=[],
            page=query.page,
            total=total,
            total_pages=(total + query.page_size - 1) // query.page_size,
            generated_at=now,
            search_too_broad=True,
        )
    stations = list(
        await session.scalars(
            statement.order_by(Station.name, Station.id)
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
    )
    projection = await summaries(session, stations, now)
    return DiscoveryResponse(
        items=[
            DiscoveryStation.model_validate(
                {
                    "id": s.id,
                    "name": s.name,
                    "address": s.address,
                    "latitude": s.latitude,
                    "longitude": s.longitude,
                    **projection[s.id],
                }
            )
            for s in stations
        ],
        page=query.page,
        total=total,
        total_pages=(total + query.page_size - 1) // query.page_size,
        generated_at=now,
    )
