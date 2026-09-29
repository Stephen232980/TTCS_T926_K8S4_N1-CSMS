from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles, build_actor_scope
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    authorize_request,
)
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import (
    StationCreateRequest,
    StationListQuery,
    StationListResponse,
    StationResponse,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/stations",
    tags=["stations"],
    dependencies=[Depends(authorize_request)],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
StationListQueryDependency = Annotated[StationListQuery, Query()]


@router.get("", response_model=StationListResponse)
@allow_roles("station_owner", "operator", "admin")
async def list_stations(
    query: StationListQueryDependency,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> StationListResponse:
    scope = build_actor_scope(actor)
    page_result = await StationRepository(db_session).list_stations_page(
        scope=scope,
        page=query.page,
        page_size=query.page_size,
        status=query.status,
        search=query.search,
    )

    total_pages = (page_result.total + query.page_size - 1) // query.page_size

    return StationListResponse(
        items=[
            StationResponse.model_validate(station) for station in page_result.items
        ],
        page=query.page,
        page_size=query.page_size,
        total=page_result.total,
        total_pages=total_pages,
    )


@router.post(
    "",
    response_model=StationResponse,
    status_code=status.HTTP_201_CREATED,
)
@allow_roles("station_owner")
async def create_station(
    request: StationCreateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> StationResponse:
    station = await StationRepository(db_session).create_station(
        owner_id=actor.user_id,
        name=request.name,
        address=request.address,
        latitude=request.latitude,
        longitude=request.longitude,
    )
    return StationResponse.model_validate(station)


@router.get("/{station_id}", response_model=StationResponse)
@allow_roles("station_owner", "operator", "admin")
async def get_station(
    station_id: UUID,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> StationResponse:
    scope = build_actor_scope(actor)
    repository = StationRepository(db_session)

    try:
        station = await repository.get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="permission_denied",
        ) from error

    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resource_not_found",
        )

    return StationResponse.model_validate(station)
