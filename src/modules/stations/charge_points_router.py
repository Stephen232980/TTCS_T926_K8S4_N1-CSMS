from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles
from src.modules.identity.dependencies import authorize_request
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import (
    ChargePointCodeAvailabilityQuery,
    ChargePointCodeAvailabilityResponse,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/charge-points",
    tags=["charge-points"],
    dependencies=[Depends(authorize_request)],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
CodeAvailabilityQuery = Annotated[ChargePointCodeAvailabilityQuery, Query()]


@router.get(
    "/code-availability",
    response_model=ChargePointCodeAvailabilityResponse,
)
@allow_roles("station_owner")
async def get_code_availability(
    query: CodeAvailabilityQuery,
    db_session: DatabaseSession,
) -> ChargePointCodeAvailabilityResponse:
    available = await StationRepository(db_session).is_charge_point_code_available(
        query.code
    )
    return ChargePointCodeAvailabilityResponse(
        code=query.code,
        available=available,
    )
