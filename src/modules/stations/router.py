import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles, build_actor_scope
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    authorize_request,
)
from src.modules.stations.exceptions import (
    ChargePointCodeAlreadyExistsError,
    StationIdempotencyConflictError,
    StationOwnershipDeniedError,
)
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import (
    ChargePointCreateRequest,
    ChargePointResponse,
    ConnectorResponse,
    StationCreateRequest,
    StationListQuery,
    StationListResponse,
    StationResponse,
    StationUpdateRequest,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/stations",
    tags=["stations"],
    dependencies=[Depends(authorize_request)],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
StationListQueryDependency = Annotated[StationListQuery, Query()]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _station_create_request_hash(request: StationCreateRequest) -> str:
    canonical_payload = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


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
    idempotency_key: IdempotencyKey,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> StationResponse:
    try:
        station = await StationRepository(db_session).create_station_idempotent(
            actor_id=actor.user_id,
            idempotency_key=idempotency_key,
            request_hash=_station_create_request_hash(request),
            name=request.name,
            address=request.address,
            latitude=request.latitude,
            longitude=request.longitude,
        )
    except StationIdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency_conflict",
        ) from error
    return StationResponse.model_validate(station)


@router.post(
    "/{station_id}/charge-points",
    response_model=ChargePointResponse,
    status_code=status.HTTP_201_CREATED,
)
@allow_roles("station_owner")
async def create_charge_point(
    station_id: UUID,
    request: ChargePointCreateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> ChargePointResponse:
    scope = build_actor_scope(actor)

    try:
        charge_point = await StationRepository(db_session).create_charge_point(
            station_id,
            scope,
            code=request.code,
            connector_count=request.connector_count,
        )
    except StationOwnershipDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="permission_denied",
        ) from error
    except ChargePointCodeAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="charge_point_code_already_exists",
        ) from error

    if charge_point is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resource_not_found",
        )

    return ChargePointResponse(
        id=charge_point.id,
        station_id=charge_point.station_id,
        code=charge_point.code,
        name=charge_point.name,
        status=charge_point.status,
        connectors=[
            ConnectorResponse.model_validate(connector)
            for connector in sorted(
                charge_point.connectors,
                key=lambda item: item.connector_number,
            )
        ],
        created_at=charge_point.created_at,
        updated_at=charge_point.updated_at,
    )


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


@router.patch("/{station_id}", response_model=StationResponse)
@allow_roles("station_owner")
async def update_station(
    station_id: UUID,
    request: StationUpdateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> StationResponse:
    scope = build_actor_scope(actor)

    try:
        station = await StationRepository(db_session).update_station(
            station_id,
            scope,
            name=request.name,
            address=request.address,
            latitude=request.latitude,
            longitude=request.longitude,
        )
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
