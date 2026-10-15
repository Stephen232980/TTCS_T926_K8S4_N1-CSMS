from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import AuditEvidence, RequestScope
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.power.schemas import PowerSetting, VersionRequest
from src.modules.power.service import (
    change_control,
    owned_station,
    power_snapshot,
    save_settings,
)
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations", route_class=PolicyRoute, tags=["owner-power"]
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/{station_id}/power-config")
@user_policy("owner.power.read", "owned", "station_owner")
async def read_power(
    station_id: UUID, db: Database, scope: RequestScope
) -> dict[str, object]:
    await owned_station(db, station_id, scope)
    return await power_snapshot(db, station_id)


@router.put("/{station_id}/power-config")
@user_policy("owner.power.configure", "owned", "station_owner")
async def write_power(
    station_id: UUID,
    body: PowerSetting,
    db: Database,
    scope: RequestScope,
    evidence: AuditEvidence,
) -> dict[str, object]:
    await owned_station(db, station_id, scope)
    await save_settings(db, station_id, body, scope, evidence)
    await db.flush()
    return await power_snapshot(db, station_id)


@router.get("/{station_id}/allocations")
@user_policy("owner.power.read", "owned", "station_owner")
async def allocations(
    station_id: UUID, db: Database, scope: RequestScope
) -> dict[str, object]:
    await owned_station(db, station_id, scope)
    return await power_snapshot(db, station_id)


@router.post("/{station_id}/power-control/enable", status_code=202)
@user_policy("owner.power.configure", "owned", "station_owner")
async def enable_power(
    station_id: UUID,
    body: VersionRequest,
    db: Database,
    scope: RequestScope,
    evidence: AuditEvidence,
) -> dict[str, object]:
    await owned_station(db, station_id, scope)
    await change_control(db, station_id, body.version, True, scope, evidence)
    return await power_snapshot(db, station_id)


@router.post("/{station_id}/power-control/disable", status_code=202)
@user_policy("owner.power.configure", "owned", "station_owner")
async def disable_power(
    station_id: UUID,
    body: VersionRequest,
    db: Database,
    scope: RequestScope,
    evidence: AuditEvidence,
) -> dict[str, object]:
    await owned_station(db, station_id, scope)
    await change_control(db, station_id, body.version, False, scope, evidence)
    return await power_snapshot(db, station_id)
