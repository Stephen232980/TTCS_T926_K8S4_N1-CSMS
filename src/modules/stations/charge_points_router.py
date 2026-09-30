from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import allow_roles, build_actor_scope
from src.modules.identity.dependencies import CurrentActorDependency, authorize_request
from src.modules.stations.exceptions import (
    ChargePointCodeAlreadyExistsError,
    ChargePointCodeLockedError,
    ChargePointOwnershipDeniedError,
)
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import (
    ChargePointCodeAvailabilityQuery,
    ChargePointCodeAvailabilityResponse,
    ChargePointResponse,
    ChargePointUpdateRequest,
    ConnectorResponse,
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


@router.patch("/{charge_point_id}", response_model=ChargePointResponse)
@allow_roles("station_owner")
async def update_charge_point_code(
    charge_point_id: UUID,
    request: ChargePointUpdateRequest,
    actor: CurrentActorDependency,
    db_session: DatabaseSession,
) -> ChargePointResponse:
    scope = build_actor_scope(actor)
    try:
        charge_point = await StationRepository(db_session).update_charge_point_code(
            charge_point_id,
            scope,
            code=request.code,
        )
    except ChargePointOwnershipDeniedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="permission_denied",
        ) from error
    except ChargePointCodeLockedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="charge_point_code_locked_after_charging",
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
