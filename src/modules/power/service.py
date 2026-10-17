"""Owner-scoped settings, commissioning gates and post-commit power work."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import ActorScope, AuthorizationEvidence
from src.modules.power.models import ConnectorPower, StationPower
from src.modules.power.schemas import PowerSetting
from src.modules.stations.exceptions import StationOwnershipDeniedError
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.stations.repository import StationRepository
from src.platform.audit.service import ghi_nhat_ky


async def owned_station(
    db: AsyncSession, station_id: UUID, scope: ActorScope
) -> Station:
    try:
        station = await StationRepository(db).get_station_by_id(station_id, scope)
    except StationOwnershipDeniedError as error:
        raise HTTPException(403, "permission_denied") from error
    if station is None or station.archived_at is not None:
        raise HTTPException(404, "resource_not_found")
    return station


async def registered_connectors(
    db: AsyncSession, station_id: UUID
) -> list[tuple[Connector, ChargePoint]]:
    return [
        (row[0], row[1])
        for row in (
            await db.execute(
                select(Connector, ChargePoint)
                .join(ChargePoint)
                .where(
                    ChargePoint.station_id == station_id,
                    ChargePoint.archived_at.is_(None),
                    Connector.archived_at.is_(None),
                )
                .order_by(ChargePoint.code, Connector.connector_number)
            )
        ).all()
    ]


async def power_snapshot(db: AsyncSession, station_id: UUID) -> dict[str, object]:
    config = await db.get(StationPower, station_id)
    capacities = {
        c.connector_id: c
        for c in await db.scalars(
            select(ConnectorPower).where(ConnectorPower.station_id == station_id)
        )
    }
    items = []
    for connector, charger in await registered_connectors(db, station_id):
        cap = capacities.get(connector.id)
        items.append(
            {
                "connector_id": str(connector.id),
                "charge_point_code": charger.code,
                "connector_number": connector.connector_number,
                "rated_kw": str(Decimal(cap.rated_w) / 1000)
                if cap
                else str(connector.max_power_kw)
                if connector.max_power_kw is not None
                else None,
                "confirmed_w": cap.confirmed_w if cap else 0,
                "reserved_w": cap.reserved_w if cap else 0,
                "desired_w": cap.desired_w if cap else 0,
                "baseline_verified": bool(
                    cap
                    and cap.baseline_boot_at
                    and cap.baseline_boot_at == charger.last_boot_at
                ),
                "status": connector.raw_ocpp_status,
            }
        )
    total = sum(c.rated_w for c in capacities.values())
    return {
        "station_id": str(station_id),
        "version": config.version if config else 0,
        "generation": config.generation if config else 0,
        "limit_kw": str(Decimal(config.limit_w) / 1000) if config else None,
        "applied_limit_w": config.applied_limit_w
        if config
        and config.enabled
        and config.state != "bootstrap"
        and items
        and all(item["baseline_verified"] for item in items)
        else None,
        "enabled": config.enabled if config else False,
        "state": config.state if config else "disabled",
        "issue": config.issue if config else None,
        "zero_limit_verified": config.zero_limit_verified if config else False,
        "offline_retention_verified": config.offline_retention_verified
        if config
        else False,
        "verification_note": config.verification_note if config else "",
        "total_rated_w": total,
        "over_registered": bool(config and total > config.limit_w),
        "connectors": items,
    }


async def save_settings(
    db: AsyncSession,
    station_id: UUID,
    body: PowerSetting,
    scope: ActorScope,
    evidence: AuthorizationEvidence,
) -> None:
    # Lock the station for first-config races; never take a socket wait under this lock.
    await db.scalar(
        select(Station.id).where(Station.id == station_id).with_for_update()
    )
    config = await db.scalar(
        select(StationPower)
        .where(StationPower.station_id == station_id)
        .with_for_update()
    )
    if body.version != (config.version if config else 0):
        raise HTTPException(409, "power_version_conflict")
    if config and config.state in {"applying", "bootstrap", "disable_pending"}:
        raise HTTPException(409, "power_plan_in_progress")
    registered = await registered_connectors(db, station_id)
    ids = [c.connector_id for c in body.connectors]
    if len(ids) != len(set(ids)) or set(ids) != {c.id for c, _ in registered}:
        raise HTTPException(422, "power_connectors_must_match_station")
    if (
        config
        and config.enabled
        and (
            not body.zero_limit_verified
            or not body.offline_retention_verified
            or not body.verification_note.strip()
        )
    ):
        raise HTTPException(409, "cannot_remove_enabled_commissioning_evidence")
    limit = int(body.limit_kw * 1000)
    before = {"limit_w": config.limit_w, "version": config.version} if config else None
    if config is None:
        config = StationPower(
            station_id=station_id, limit_w=limit, applied_limit_w=limit
        )
        db.add(config)
        await db.flush()
    else:
        config.version += 1
    config.limit_w = limit
    config.zero_limit_verified = body.zero_limit_verified
    config.offline_retention_verified = body.offline_retention_verified
    config.verification_note = body.verification_note.strip()
    for value in body.connectors:
        cap = await db.get(ConnectorPower, value.connector_id)
        if cap is None:
            cap = ConnectorPower(
                connector_id=value.connector_id,
                station_id=station_id,
                rated_w=int(value.rated_kw * 1000),
            )
            db.add(cap)
        else:
            cap.rated_w = int(value.rated_kw * 1000)
    if not config.enabled:
        config.applied_limit_w = limit
    config.generation += 1
    config.dirty_at = datetime.now(UTC)
    await ghi_nhat_ky(
        db,
        actor_id=scope.actor_id,
        action="power.config_saved",
        object_type="station",
        object_id=str(station_id),
        data={"before": before, "limit_w": limit, "version": config.version},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )


async def change_control(
    db: AsyncSession,
    station_id: UUID,
    version: int,
    enable: bool,
    scope: ActorScope,
    evidence: AuthorizationEvidence,
) -> None:
    config = await db.scalar(
        select(StationPower)
        .where(StationPower.station_id == station_id)
        .with_for_update()
    )
    if config is None:
        raise HTTPException(409, "power_not_configured")
    if config.version != version:
        raise HTTPException(409, "power_version_conflict")
    if config.enabled == enable and config.state not in {"degraded", "disable_pending"}:
        return
    if config.state in {"applying", "bootstrap"}:
        raise HTTPException(409, "power_plan_in_progress")
    if enable and not (
        config.zero_limit_verified
        and config.offline_retention_verified
        and config.verification_note
    ):
        raise HTTPException(409, "power_commissioning_required")
    active = await db.scalar(
        select(ChargingSession.id)
        .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
        .where(ChargePoint.station_id == station_id, ChargingSession.ended_at.is_(None))
        .limit(1)
    )
    if active is not None:
        raise HTTPException(409, "power_control_requires_no_open_sessions")
    rows = await registered_connectors(db, station_id)
    caps = list(
        await db.scalars(
            select(ConnectorPower).where(ConnectorPower.station_id == station_id)
        )
    )
    if {c.id for c, _ in rows} != {c.connector_id for c in caps} or not rows:
        raise HTTPException(409, "power_configuration_incomplete")
    if enable:
        # A previous disable may have cleared profiles after its zero readback.
        # Every enable/retry must establish defaults again before admitting cars.
        for cap in caps:
            cap.baseline_boot_at = None
    config.version += 1
    config.generation += 1
    config.enabled = True  # Disable remains guarded until device profiles are cleared.
    config.target_enabled = enable
    config.state = "bootstrap" if enable else "disable_pending"
    config.issue = None
    config.dirty_at = datetime.now(UTC)
    await ghi_nhat_ky(
        db,
        actor_id=scope.actor_id,
        action="power.enable_requested" if enable else "power.disable_requested",
        object_type="station",
        object_id=str(station_id),
        data={"version": config.version},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )


async def power_start_allowed(db: AsyncSession, station_id: UUID) -> bool:
    config = await db.scalar(
        select(StationPower)
        .where(StationPower.station_id == station_id)
        .with_for_update()
    )
    if config is None or not config.enabled:
        return True
    if (
        config.state not in {"ready", "applying"}
        or config.issue
        or not config.target_enabled
    ):
        return False
    rows = await registered_connectors(db, station_id)
    caps = {
        c.connector_id: c
        for c in await db.scalars(
            select(ConnectorPower).where(ConnectorPower.station_id == station_id)
        )
    }
    return bool(rows) and all(
        c.id in caps
        and caps[c.id].baseline_boot_at is not None
        and caps[c.id].baseline_boot_at == charger.last_boot_at
        for c, charger in rows
    )


async def note_power_start(
    db: AsyncSession, station_id: UUID, connector_id: UUID
) -> None:
    """A previous transaction's readback cannot confirm power for a new car."""
    config = await db.scalar(
        select(StationPower)
        .where(StationPower.station_id == station_id)
        .with_for_update()
    )
    if config and config.enabled:
        cap = await db.get(ConnectorPower, connector_id)
        if cap is not None:
            # The verified default profile is zero. Keep the old reservation
            # until the worker verifies the profile bound to this transaction.
            cap.confirmed_w = 0


async def note_power_event(db: AsyncSession, station_id: UUID) -> None:
    config = await db.scalar(
        select(StationPower)
        .where(StationPower.station_id == station_id)
        .with_for_update()
    )
    if config and config.enabled:
        config.generation += 1
        if config.dirty_at is None:
            config.dirty_at = datetime.now(UTC)
