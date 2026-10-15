"""Owner fee configuration; station locks serialize booking snapshots."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import user_policy
from src.modules.identity.dependencies import AuditEvidence, CurrentActorDependency
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.reservations.models import ReservationPolicy
from src.modules.stations.models import Station
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import get_db_session

router = APIRouter(
    prefix="/api/v1/owner/stations", route_class=PolicyRoute, tags=["reservations"]
)
Database = Annotated[AsyncSession, Depends(get_db_session)]


class PolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fee_vnd: Annotated[StrictInt, Field(ge=0, le=1000000)]
    expected_version: Annotated[StrictInt, Field(ge=0)]


async def quote(db: AsyncSession, station_id: UUID) -> dict[str, int]:
    policy = await db.get(ReservationPolicy, station_id)
    return {
        "fee_vnd": policy.fee_vnd if policy else 0,
        "version": policy.version if policy else 0,
    }


async def owned(
    db: AsyncSession, station_id: UUID, actor_id: UUID, *, lock: bool = False
) -> Station:
    query = select(Station).where(Station.id == station_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    station = await db.scalar(query)
    if station is None or station.archived_at is not None:
        raise HTTPException(404, "resource_not_found")
    if station.owner_id != actor_id:
        raise HTTPException(403, "permission_denied")
    return station


@router.get("/{station_id}/reservation-policy")
@user_policy("owner.reservations.policy.read", "owned", "station_owner")
async def read_policy(
    station_id: UUID, actor: CurrentActorDependency, db: Database
) -> dict[str, int]:
    await owned(db, station_id, actor.user_id)
    return await quote(db, station_id)


@router.put("/{station_id}/reservation-policy")
@user_policy("owner.reservations.policy.update", "owned", "station_owner")
async def update_policy(
    station_id: UUID,
    body: PolicyBody,
    actor: CurrentActorDependency,
    evidence: AuditEvidence,
    db: Database,
) -> dict[str, int]:
    await owned(db, station_id, actor.user_id, lock=True)
    policy = await db.get(ReservationPolicy, station_id)
    version = policy.version if policy else 0
    if version != body.expected_version:
        raise HTTPException(409, "reservation_policy_changed")
    before = policy.fee_vnd if policy else 0
    if before == body.fee_vnd:
        return await quote(db, station_id)
    if policy is None:
        policy = ReservationPolicy(
            station_id=station_id, fee_vnd=body.fee_vnd, version=1
        )
        db.add(policy)
    else:
        policy.fee_vnd, policy.version = body.fee_vnd, version + 1
    await ghi_nhat_ky(
        db,
        actor_id=actor.user_id,
        action="reservation.policy_updated",
        object_type="station",
        object_id=str(station_id),
        data={
            "before_fee_vnd": before,
            "fee_vnd": policy.fee_vnd,
            "version": policy.version,
        },
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    await db.flush()
    return await quote(db, station_id)
