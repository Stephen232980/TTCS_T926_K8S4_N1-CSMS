"""Driver-facing station locations; excludes management and owner data."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import authorize_request
from src.modules.stations.models import Station
from src.platform.database.session import get_db_session

router = APIRouter(
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


class DiscoveryResponse(BaseModel):
    items: list[DiscoveryStation]
    page: int
    total: int
    total_pages: int


@router.get("", response_model=DiscoveryResponse)
@allow_roles("driver")
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
    stations = await session.scalars(
        statement.order_by(Station.name, Station.id)
        .offset((query.page - 1) * query.page_size)
        .limit(query.page_size)
    )
    return DiscoveryResponse(
        items=[DiscoveryStation.model_validate(s) for s in stations],
        page=query.page,
        total=total,
        total_pages=(total + query.page_size - 1) // query.page_size,
    )
