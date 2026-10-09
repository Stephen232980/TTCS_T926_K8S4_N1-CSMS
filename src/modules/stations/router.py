import hashlib
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import (
    CurrentActorDependency,
    RequestScope,
    authorize_request,
)
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.exceptions import (
    ChargePointCodeAlreadyExistsError,
    StationIdempotencyConflictError,
    StationOwnershipDeniedError,
    StationTimezoneLockedError,
)
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import (
    ChargePointCreateRequest,
    ChargePointListQuery,
    ChargePointListResponse,
    ChargePointResponse,
    ConnectorResponse,
    StationCreateRequest,
    StationListQuery,
    StationListResponse,
    StationResponse,
    StationUpdateRequest,
)
from src.modules.stations.timezones import DEFAULT_STATION_TIMEZONE
from src.platform.database.session import get_db_session

router = APIRouter(
    route_class=PolicyRoute,
    prefix="/api/v1/stations",
    tags=["stations"],
    dependencies=[Depends(authorize_request)],
)

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
StationListQueryDependency = Annotated[StationListQuery, Query()]
ChargePointListQueryDependency = Annotated[ChargePointListQuery, Query()]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _station_create_request_hash(request: StationCreateRequest) -> str:
    payload = request.model_dump(mode="json")
    if request.price_vnd_per_kwh is None:
        payload.pop("price_vnd_per_kwh")
    # Preserve replay of create requests recorded before timezone was exposed.
    if request.timezone == DEFAULT_STATION_TIMEZONE:
        payload.pop("timezone")
    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


@router.get("", response_model=StationListResponse)
@user_policy("owner.stations.list_stations", "owned", "station_owner")
async def list_stations(
    query: StationListQueryDependency,
    actor: CurrentActorDependency,
    scope: RequestScope,
    db_session: DatabaseSession,
) -> StationListResponse:
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
@user_policy("owner.stations.create_station", "owned", "station_owner")
async def create_station(
    request: StationCreateRequest,
    idempotency_key: IdempotencyKey,
    actor: CurrentActorDependency,
    scope: RequestScope,
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
            price_vnd_per_kwh=request.price_vnd_per_kwh,
            timezone=request.timezone,
        )
    except StationIdempotencyConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency_conflict",
        ) from error
    return StationResponse.model_validate(station)


@router.get(
    "/{station_id}/charge-points",
    response_model=ChargePointListResponse,
)
@user_policy("owner.stations.list_charge_points", "owned", "station_owner")
async def list_charge_points(
    station_id: UUID,
    query: ChargePointListQueryDependency,
    actor: CurrentActorDependency,
    scope: RequestScope,
    db_session: DatabaseSession,
) -> ChargePointListResponse:

    try:
        page_result = await StationRepository(db_session).list_charge_points_page(
            station_id,
            scope,
            page=query.page,
            page_size=query.page_size,
        )
    except StationOwnershipDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="permission_denied",
        ) from error

    if page_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="resource_not_found",
        )

    total_pages = (page_result.total + query.page_size - 1) // query.page_size
    return ChargePointListResponse(
        items=[
            ChargePointResponse(
                id=charge_point.id,
                station_id=charge_point.station_id,
                code=charge_point.code,
                name=charge_point.name,
                vendor=charge_point.vendor,
                model=charge_point.model,
                firmware_version=charge_point.firmware_version,
                status=charge_point.status,
                code_locked_at=charge_point.code_locked_at,
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
            for charge_point in page_result.items
        ],
        page=query.page,
        page_size=query.page_size,
        total=page_result.total,
        total_pages=total_pages,
    )


@router.post(
    "/{station_id}/charge-points",
    response_model=ChargePointResponse,
    status_code=status.HTTP_201_CREATED,
)
@user_policy("owner.stations.create_charge_point", "owned", "station_owner")
async def create_charge_point(
    station_id: UUID,
    request: ChargePointCreateRequest,
    actor: CurrentActorDependency,
    scope: RequestScope,
    db_session: DatabaseSession,
) -> ChargePointResponse:

    try:
        charge_point = await StationRepository(db_session).create_charge_point(
            station_id,
            scope,
            code=request.code,
            connector_count=request.connector_count,
            name=request.name,
            connectors=request.connectors,
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
        vendor=charge_point.vendor,
        model=charge_point.model,
        firmware_version=charge_point.firmware_version,
        status=charge_point.status,
        code_locked_at=charge_point.code_locked_at,
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
@user_policy("owner.stations.get_station", "owned", "station_owner")
async def get_station(
    station_id: UUID,
    actor: CurrentActorDependency,
    scope: RequestScope,
    db_session: DatabaseSession,
) -> StationResponse:
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
@user_policy("owner.stations.update_station", "owned", "station_owner")
async def update_station(
    station_id: UUID,
    request: StationUpdateRequest,
    actor: CurrentActorDependency,
    scope: RequestScope,
    db_session: DatabaseSession,
) -> StationResponse:

    try:
        station = await StationRepository(db_session).update_station(
            station_id,
            scope,
            name=request.name,
            address=request.address,
            latitude=request.latitude,
            longitude=request.longitude,
            price_vnd_per_kwh=request.price_vnd_per_kwh,
            timezone=request.timezone,
        )
    except StationTimezoneLockedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="station_timezone_locked",
        ) from error
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
