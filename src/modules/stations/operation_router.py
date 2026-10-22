"""Owner station admission switch; never interrupts existing transactions."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import AuditEvidence, RequestScope
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.ocpp.monitoring import database_time
from src.modules.power.service import power_start_allowed
from src.modules.pricing.models import TariffBand
from src.modules.pricing.service import lay_bieu_gia_hieu_luc
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import ChargePoint, Connector
from src.modules.stations.repository import StationRepository
from src.modules.stations.schemas import StationResponse
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations", route_class=PolicyRoute, tags=["stations"]
)


class OperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["active", "suspended"]
    expected_version: int = Field(ge=1, strict=True)
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def require_suspend_reason(self) -> "OperationRequest":
        if self.status == "suspended" and not self.reason:
            raise ValueError("station_suspend_reason_required")
        return self


@router.patch("/{station_id}/operation", response_model=StationResponse)
@user_policy("owner.stations.change_operation", "owned", "station_owner")
async def change_operation(
    station_id: UUID,
    request: OperationRequest,
    scope: RequestScope,
    evidence: AuditEvidence,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> StationResponse:
    try:
        station = await StationRepository(db).get_station_by_id(
            station_id, scope, for_update=True
        )
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None or station.archived_at is not None:
        raise HTTPException(404, "resource_not_found")
    if station.status == "blocked":
        raise HTTPException(409, "station_admin_blocked")
    # Exact retry after response loss is a no-op. A superseded intent is stale.
    if station.status == request.status and station.status_version in {
        request.expected_version,
        request.expected_version + 1,
    }:
        return StationResponse.model_validate(station)
    if station.status_version != request.expected_version:
        raise HTTPException(409, "station_version_conflict")
    if request.status == "suspended" and station.status != "active":
        raise HTTPException(409, "station_transition_invalid")
    if request.status == "active":
        if not (
            station.name.strip()
            and station.address.strip()
            and -90 <= station.latitude <= 90
            and -180 <= station.longitude <= 180
        ):
            raise HTTPException(409, "station_configuration_incomplete")
        connector = await db.scalar(
            select(Connector.id)
            .join(ChargePoint)
            .where(
                ChargePoint.station_id == station.id,
                ChargePoint.archived_at.is_(None),
                Connector.archived_at.is_(None),
            )
            .limit(1)
        )
        if connector is None:
            raise HTTPException(409, "station_connector_required")
        tariff = await lay_bieu_gia_hieu_luc(
            db, station_id=station.id, ngay=await database_time(db)
        )
        bands = (
            list(
                await db.scalars(
                    select(TariffBand)
                    .where(TariffBand.tariff_id == tariff.id)
                    .order_by(TariffBand.start_min)
                )
            )
            if tariff is not None
            else []
        )
        cursor = 0
        for band in bands:
            if band.start_min != cursor or band.energy_rate_vnd_per_kwh < 0:
                raise HTTPException(409, "station_tariff_required")
            cursor = band.end_min
        if cursor != 1440:
            raise HTTPException(409, "station_tariff_required")
        if not await power_start_allowed(db, station.id):
            raise HTTPException(409, "power_unavailable")
    before = station.status
    station.status = request.status
    station.status_version += 1
    await ghi_nhat_ky(
        db,
        actor_id=scope.actor_id,
        action="station.operation_changed",
        object_type="station",
        object_id=str(station.id),
        data={
            "before": before,
            "after": station.status,
            "reason": request.reason,
            "version": station.status_version,
        },
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    await db.flush()
    await db.refresh(station)
    return StationResponse.model_validate(station)
