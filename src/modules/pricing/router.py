from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import RequestScope, authorize_request
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.pricing.bands import TariffBandsError, kiem_khung_gio
from src.modules.pricing.creation import tao_bieu_gia
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.schemas import TariffCreateRequest, TariffResponse
from src.modules.pricing.service import (
    TariffDuplicateDateError,
    TariffEffectiveDateError,
    TariffImmutableError,
    TariffNotFoundError,
    kiem_bieu_gia_co_the_sua,
    kiem_ngay_hieu_luc,
    ngay_dia_phuong,
)
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.repository import StationRepository
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations",
    tags=["owner-tariffs"],
    route_class=PolicyRoute,
    dependencies=[Depends(authorize_request)],
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class TariffDisplayBand(BaseModel):
    start_min: int
    end_min: int
    label: str
    energy_rate_vnd_per_kwh: str


class TariffDisplay(BaseModel):
    effective_from: str
    idle_rate_vnd_per_minute: str
    grace_minutes: int
    bands: list[TariffDisplayBand]


class TariffContext(BaseModel):
    today: str
    timezone: str
    has_versions: bool
    current: TariffDisplay | None
    upcoming: TariffDisplay | None


@router.get("/{station_id}/tariffs/context", response_model=TariffContext)
@user_policy("owner.tariff.manage", "owned", "station_owner")
async def tariff_context(
    station_id: UUID, scope: RequestScope, db: Database, response: Response
) -> TariffContext:
    """Minimal T-62 form context, not a version-history API."""
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    today = ngay_dia_phuong(station.timezone, datetime.now(UTC))
    query = select(Tariff).where(Tariff.station_id == station_id)
    current = await db.scalar(
        query.where(Tariff.effective_from <= today)
        .order_by(Tariff.effective_from.desc())
        .limit(1)
    )
    upcoming = await db.scalar(
        query.where(Tariff.effective_from > today)
        .order_by(Tariff.effective_from)
        .limit(1)
    )

    async def display(tariff: Tariff | None) -> TariffDisplay | None:
        if tariff is None:
            return None
        bands = await db.scalars(
            select(TariffBand)
            .where(TariffBand.tariff_id == tariff.id)
            .order_by(TariffBand.start_min)
        )
        return TariffDisplay(
            effective_from=tariff.effective_from.isoformat(),
            idle_rate_vnd_per_minute=str(tariff.idle_rate_vnd_per_minute),
            grace_minutes=tariff.grace_minutes,
            bands=[
                TariffDisplayBand(
                    start_min=band.start_min,
                    end_min=band.end_min,
                    label=band.label,
                    energy_rate_vnd_per_kwh=str(band.energy_rate_vnd_per_kwh),
                )
                for band in bands
            ],
        )

    response.headers["Cache-Control"] = "no-store"
    return TariffContext(
        today=today.isoformat(),
        timezone=station.timezone,
        has_versions=current is not None or upcoming is not None,
        current=await display(current),
        upcoming=await display(upcoming),
    )


@router.post(
    "/{station_id}/tariffs",
    response_model=TariffResponse,
    status_code=201,
    responses={
        401: {"description": "Chưa đăng nhập"},
        403: {"description": "Không có quyền hoặc trạm thuộc chủ khác"},
        404: {"description": "Không tìm thấy trạm"},
        409: {"description": "Trùng ngày hiệu lực biểu giá"},
    },
)
@user_policy("owner.tariff.manage", "owned", "station_owner")
async def create_tariff(
    station_id: UUID,
    request: TariffCreateRequest,
    scope: RequestScope,
    db: Database,
) -> TariffResponse:
    try:
        response = await tao_bieu_gia(
            db,
            scope=scope,
            station_id=station_id,
            effective_from=request.effective_from,
            idle_rate_vnd_per_minute=request.idle_rate_vnd_per_minute,
            grace_minutes=request.grace_minutes,
            bands=request.band_inputs(),
        )
        await db.commit()
        return response
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    except TariffNotFoundError as error:
        raise HTTPException(404, "resource_not_found") from error
    except TariffDuplicateDateError as error:
        raise HTTPException(409, "tariff_duplicate_date") from error
    except TariffEffectiveDateError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "effective_from"],
                    "msg": str(error),
                    "type": "value_error",
                }
            ],
        ) from error
    except TariffBandsError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "bands"],
                    "type": issue.code,
                    "msg": issue.message,
                    "input_indices": list(issue.input_indices),
                    "start_min": issue.start_min,
                    "end_min": issue.end_min,
                }
                for issue in error.issues
            ],
        ) from error


class TariffVersion(TariffDisplay):
    id: UUID
    created_at: datetime
    status: Literal["upcoming", "current", "historical"]
    editable: bool


class TariffHistory(BaseModel):
    today: str
    timezone: str
    items: list[TariffVersion]
    page: int
    page_size: int
    total: int


async def _version(
    db: AsyncSession,
    tariff: Tariff,
    today: str,
    current_id: UUID | None,
    loaded_bands: list[TariffBand] | None = None,
) -> TariffVersion:
    bands = loaded_bands
    if bands is None:
        bands = list(
            await db.scalars(
                select(TariffBand)
                .where(TariffBand.tariff_id == tariff.id)
                .order_by(TariffBand.start_min)
            )
        )
    future = tariff.effective_from.isoformat() > today
    return TariffVersion(
        id=tariff.id,
        created_at=tariff.created_at,
        effective_from=tariff.effective_from.isoformat(),
        idle_rate_vnd_per_minute=str(tariff.idle_rate_vnd_per_minute),
        grace_minutes=tariff.grace_minutes,
        status="upcoming"
        if future
        else "current"
        if tariff.id == current_id
        else "historical",
        editable=future and tariff.used_at is None,
        bands=[
            TariffDisplayBand(
                start_min=b.start_min,
                end_min=b.end_min,
                label=b.label,
                energy_rate_vnd_per_kwh=str(b.energy_rate_vnd_per_kwh),
            )
            for b in bands
        ],
    )


@router.get("/{station_id}/tariffs", response_model=TariffHistory)
@user_policy("owner.tariff.manage", "owned", "station_owner")
async def tariff_history(
    station_id: UUID,
    scope: RequestScope,
    db: Database,
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> TariffHistory:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None:
        raise HTTPException(404, "resource_not_found")
    today = ngay_dia_phuong(station.timezone, datetime.now(UTC))
    current_id = await db.scalar(
        select(Tariff.id)
        .where(Tariff.station_id == station_id, Tariff.effective_from <= today)
        .order_by(Tariff.effective_from.desc())
        .limit(1)
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(Tariff)
            .where(Tariff.station_id == station_id)
        )
        or 0
    )
    versions = await db.scalars(
        select(Tariff)
        .where(Tariff.station_id == station_id)
        .order_by(Tariff.effective_from.desc(), Tariff.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(versions)
    grouped: dict[UUID, list[TariffBand]] = {row.id: [] for row in rows}
    if rows:
        bands = await db.scalars(
            select(TariffBand)
            .where(TariffBand.tariff_id.in_(grouped))
            .order_by(TariffBand.start_min)
        )
        for band in bands:
            grouped[band.tariff_id].append(band)
    response.headers["Cache-Control"] = "no-store"
    return TariffHistory(
        today=today.isoformat(),
        timezone=station.timezone,
        items=[
            await _version(db, row, today.isoformat(), current_id, grouped[row.id])
            for row in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.patch(
    "/{station_id}/tariffs/{tariff_id}",
    response_model=TariffVersion,
    responses={409: {"description": "Phiên bản bất biến hoặc ngày hiệu lực trùng"}},
)
@user_policy("owner.tariff.manage", "owned", "station_owner")
async def edit_tariff(
    station_id: UUID,
    tariff_id: UUID,
    request: TariffCreateRequest,
    scope: RequestScope,
    db: Database,
) -> TariffVersion:
    """Replace editable version fields/bands atomically; never remove a version."""
    try:
        station = await StationRepository(db).get_station_by_id(
            station_id, scope, for_update=True
        )
        if station is None:
            raise TariffNotFoundError("Station does not exist")
        tariff = await kiem_bieu_gia_co_the_sua(
            db, station_id=station_id, tariff_id=tariff_id
        )
        normalized = kiem_khung_gio(request.band_inputs())
        await kiem_ngay_hieu_luc(
            db,
            station_id=station_id,
            effective_from=request.effective_from,
            exclude_tariff_id=tariff_id,
        )
        await db.execute(delete(TariffBand).where(TariffBand.tariff_id == tariff.id))
        tariff.effective_from = request.effective_from
        tariff.idle_rate_vnd_per_minute = request.idle_rate_vnd_per_minute
        tariff.grace_minutes = request.grace_minutes
        db.add_all(
            [
                TariffBand(
                    tariff_id=tariff.id,
                    start_min=b.start_min,
                    end_min=b.end_min,
                    label=b.label,
                    energy_rate_vnd_per_kwh=b.energy_rate_vnd_per_kwh,
                )
                for b in normalized
            ]
        )
        await db.flush()
        result = await _version(
            db,
            tariff,
            ngay_dia_phuong(station.timezone, datetime.now(UTC)).isoformat(),
            None,
        )
        await db.commit()
        return result
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    except TariffNotFoundError as error:
        raise HTTPException(404, "resource_not_found") from error
    except TariffImmutableError as error:
        raise HTTPException(409, "tariff_immutable") from error
    except TariffDuplicateDateError as error:
        raise HTTPException(409, "tariff_duplicate_date") from error
    except TariffEffectiveDateError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "effective_from"],
                    "msg": str(error),
                    "type": "value_error",
                }
            ],
        ) from error
    except TariffBandsError as error:
        raise HTTPException(
            422,
            [
                {
                    "loc": ["body", "bands"],
                    "type": issue.code,
                    "msg": issue.message,
                    "input_indices": list(issue.input_indices),
                    "start_min": issue.start_min,
                    "end_min": issue.end_min,
                }
                for issue in error.issues
            ],
        ) from error
