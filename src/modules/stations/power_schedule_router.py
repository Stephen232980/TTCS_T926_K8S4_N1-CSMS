"""Owner API endpoints for station power schedules (S-45 / G2)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import StationPowerSchedule
from src.modules.stations.power_bands import PowerBandsError
from src.modules.stations.power_schedule_schemas import (
    CurrentPowerLimitResponse,
    PowerScheduleBandDisplay,
    PowerScheduleResponse,
    PowerScheduleSaveRequest,
    _minute_to_time,
)
from src.modules.stations.power_schedule_service import (
    get_current_power_limit_w,
    get_effective_power_schedule,
    ngay_dia_phuong,
    phut_trong_ngay,
    save_station_power_schedule,
)
from src.modules.stations.repository import StationRepository
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations",
    tags=["owner-power-schedules"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)

Database = Annotated[AsyncSession, Depends(get_db_session)]


def _format_schedule_response(
    schedule: StationPowerSchedule,
) -> PowerScheduleResponse:
    bands_display = [
        PowerScheduleBandDisplay(
            id=b.id,
            start_min=b.start_min,
            end_min=b.end_min,
            start_time=_minute_to_time(b.start_min),
            end_time=_minute_to_time(b.end_min),
            power_limit_w=b.power_limit_w,
            power_limit_kw=f"{Decimal(b.power_limit_w) / Decimal(1000):.3f}",
        )
        for b in sorted(schedule.bands, key=lambda x: x.start_min)
    ]
    return PowerScheduleResponse(
        id=schedule.id,
        station_id=schedule.station_id,
        effective_from=schedule.effective_from,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        bands=bands_display,
    )


@router.get(
    "/{station_id}/power-schedule",
    response_model=PowerScheduleResponse | None,
)
@user_policy("owner.power_schedule.manage", "owned", "station_owner")
async def get_power_schedule(
    station_id: UUID,
    scope: RequestScope,
    db: Database,
    effective_date: str | None = Query(
        default=None, description="Optional target date YYYY-MM-DD"
    ),
) -> PowerScheduleResponse | None:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied") from error
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource_not_found")

    now = datetime.now(UTC)
    if effective_date:
        try:
            target_d = datetime.strptime(effective_date, "%Y-%m-%d").date()
        except ValueError as err:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Định dạng ngày không hợp lệ"
            ) from err
    else:
        target_d = ngay_dia_phuong(station.timezone, now)

    schedule = await get_effective_power_schedule(db, station_id, target_d)
    if schedule is None:
        return None

    return _format_schedule_response(schedule)


@router.put(
    "/{station_id}/power-schedule",
    response_model=PowerScheduleResponse,
)
@user_policy("owner.power_schedule.manage", "owned", "station_owner")
async def put_power_schedule(
    station_id: UUID,
    request: PowerScheduleSaveRequest,
    scope: RequestScope,
    db: Database,
) -> PowerScheduleResponse:
    try:
        station = await StationRepository(db).get_station_by_id(
            station_id, scope, for_update=True
        )
    except StationOwnershipDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied") from error
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource_not_found")

    now_date = ngay_dia_phuong(station.timezone, datetime.now(UTC))
    if request.effective_from < now_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Ngày hiệu lực phải từ hôm nay trở đi",
        )

    try:
        band_inputs = [b.to_band_input() for b in request.bands]
        schedule = await save_station_power_schedule(
            db,
            station_id=station_id,
            effective_from=request.effective_from,
            raw_bands=band_inputs,
        )
        await db.commit()
        return _format_schedule_response(schedule)
    except PowerBandsError as error:
        await db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"code": i.code, "message": i.message} for i in error.issues],
        ) from error
    except Exception:
        await db.rollback()
        raise


@router.get(
    "/{station_id}/power-schedule/current",
    response_model=CurrentPowerLimitResponse,
)
@user_policy("owner.power_schedule.manage", "owned", "station_owner")
async def get_current_power_limit(
    station_id: UUID,
    scope: RequestScope,
    db: Database,
) -> CurrentPowerLimitResponse:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "permission_denied") from error
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resource_not_found")

    now = datetime.now(UTC)
    local_d = ngay_dia_phuong(station.timezone, now)
    local_m = phut_trong_ngay(station.timezone, now)
    limit_w = await get_current_power_limit_w(db, station_id, now)

    return CurrentPowerLimitResponse(
        station_id=station_id,
        timezone=station.timezone,
        local_time=_minute_to_time(local_m),
        local_date=local_d,
        power_limit_w=limit_w,
        power_limit_kw=f"{Decimal(limit_w) / Decimal(1000):.3f}"
        if limit_w is not None
        else None,
    )
