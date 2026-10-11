"""S-28 policy: a resumable EV pause is a candidate, not proof of completion."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.models import Invoice
from src.modules.charging.models import (
    ChargingSession,
    ChargingSessionEvent,
    OccupationInterval,
)


def flag(charging: ChargingSession, reason: str) -> None:
    if reason not in charging.review_reasons:
        charging.review_reasons = [*charging.review_reasons, reason]


async def current_interval(
    db: AsyncSession, charging: ChargingSession
) -> OccupationInterval | None:
    return (
        await db.scalars(
            select(OccupationInterval)
            .where(OccupationInterval.session_id == charging.id)
            .order_by(OccupationInterval.id.desc())
            .limit(1)
        )
    ).first()


async def release(
    db: AsyncSession,
    charging: ChargingSession,
    stamp: datetime,
    interval: OccupationInterval | None,
    *,
    source: str,
) -> None:
    if charging.connector_released_at is not None:
        return
    if stamp < charging.started_at or (
        interval is not None and stamp < interval.started_at
    ):
        flag(charging, "occupation_invalid_release_time")
        return
    charging.connector_released_at = stamp
    if interval is not None and interval.ended_at is None:
        interval.ended_at, interval.end_reason = stamp, "released"
    db.add(
        ChargingSessionEvent(
            session_id=charging.id,
            action="connector_released",
            details={
                "timestamp": stamp.isoformat(),
                "source": source,
            },
        )
    )


async def note_status(
    db: AsyncSession, connector_id: UUID, status: str, stamp: datetime | None
) -> None:
    # OCPP dispatch holds the charger/connector lock. Never attach a status to an
    # older driver's session after a newer transaction has used this connector.
    charging = await db.scalar(
        select(ChargingSession)
        .where(ChargingSession.connector_id == connector_id)
        .order_by(ChargingSession.id.desc())
        .limit(1)
        .with_for_update()
    )
    if charging is None or charging.billing_lifecycle_version == 0:
        return
    if (
        await db.scalar(select(Invoice.id).where(Invoice.session_id == charging.id))
        is not None
    ):
        return
    if stamp is None:
        flag(charging, "occupation_missing_status_timestamp")
        return
    if stamp < charging.started_at:
        return
    if charging.connector_released_at is not None:
        if status in {"Charging", "SuspendedEV", "Finishing"}:
            flag(charging, "occupation_status_after_release")
        return
    interval = await current_interval(db, charging)
    db.add(
        ChargingSessionEvent(
            session_id=charging.id,
            action="occupation_status",
            details={"status": status, "timestamp": stamp.isoformat()},
        )
    )
    if status in {"SuspendedEV", "Finishing"}:
        if interval is None or interval.ended_at is not None:
            interval = OccupationInterval(
                session_id=charging.id, started_at=stamp, confirmed=False
            )
            db.add(interval)
            charging.idle_since = stamp
        if status == "Finishing" or (
            charging.ended_at is not None and stamp >= charging.ended_at
        ):
            interval.confirmed = True
    elif status == "Charging":
        if charging.ended_at is not None:
            flag(charging, "occupation_charging_after_stop")
        elif interval is not None and interval.ended_at is None:
            interval.ended_at, interval.end_reason, interval.confirmed = (
                stamp,
                "resumed",
                False,
            )
            charging.idle_since = None
    elif status == "Available":
        if charging.release_detection == "available":
            await release(db, charging, stamp, interval, source="Available")
    elif interval is not None and interval.ended_at is None:
        # Do not silently turn supply suspension/faults into driver occupation fees.
        flag(charging, "occupation_interrupted_status")


async def note_stop(db: AsyncSession, charging: ChargingSession) -> None:
    if charging.billing_lifecycle_version == 0:
        return
    assert charging.ended_at is not None
    interval = await current_interval(db, charging)
    if interval is not None and interval.end_reason != "resumed":
        interval.confirmed = True
    if charging.stop_reason == "EVDisconnected":
        await release(
            db, charging, charging.ended_at, interval, source="EVDisconnected"
        )


async def note_offline_gap(db: AsyncSession, charger_id: UUID) -> None:
    candidates = await db.scalars(
        select(ChargingSession)
        .where(
            ChargingSession.charge_point_id == charger_id,
            ChargingSession.billing_lifecycle_version == 1,
            ChargingSession.connector_released_at.is_(None),
            or_(
                ChargingSession.idle_since.is_not(None),
                ChargingSession.ended_at.is_not(None),
            ),
            ~select(Invoice.id)
            .where(Invoice.session_id == ChargingSession.id)
            .exists(),
        )
        .with_for_update()
    )
    for charging in candidates:
        flag(charging, "occupation_offline_gap")
