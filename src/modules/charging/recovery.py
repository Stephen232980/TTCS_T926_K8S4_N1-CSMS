"""Recover by CSMS transaction identity; never infer a missing end meter."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.charging.models import (
    ChargingSession,
    ChargingSessionEvent,
    MeterSample,
)
from src.modules.charging.service import review
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.ocpp.monitoring import expired
from src.modules.stations.models import ChargePoint, Connector


async def note_reconnection(session: AsyncSession, charger_id: UUID) -> None:
    now = datetime.now(UTC)
    transactions = await session.scalars(
        select(ChargingSession)
        .where(
            ChargingSession.charge_point_id == charger_id,
            ChargingSession.ended_at.is_(None),
        )
        .with_for_update()
    )
    for transaction in transactions:
        transaction.recovery_at = now
        session.add(
            ChargingSessionEvent(
                session_id=transaction.id, action="reconnected", details={}
            )
        )


async def note_connector_status(
    session: AsyncSession, charger_id: UUID, number: int, status: str
) -> None:
    if number == 0 or status not in ("Available", "Charging"):
        return
    transaction = await session.scalar(
        select(ChargingSession)
        .join(Connector, Connector.id == ChargingSession.connector_id)
        .where(
            ChargingSession.charge_point_id == charger_id,
            Connector.connector_number == number,
            ChargingSession.ended_at.is_(None),
        )
        .with_for_update(of=ChargingSession)
    )
    if transaction is None:
        return
    if (
        status == "Available"
        and "available_with_open_session" not in transaction.review_reasons
    ):
        review(transaction, "available_with_open_session")
        session.add(
            ChargingSessionEvent(
                session_id=transaction.id,
                action="available_with_open_session",
                details={},
            )
        )
    elif (
        status == "Charging"
        and "available_with_open_session" in transaction.review_reasons
    ):
        transaction.review_reasons = [
            r for r in transaction.review_reasons if r != "available_with_open_session"
        ]
        session.add(
            ChargingSessionEvent(
                session_id=transaction.id, action="charging_resumed", details={}
            )
        )


async def flag_abnormal_sessions(
    session: AsyncSession, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    # Every writer locks charger before transaction; skip busy chargers until next scan.
    chargers = await session.scalars(
        select(ChargePoint).where(expired(now)).with_for_update(skip_locked=True)
    )
    for charger in chargers:
        transactions = await session.scalars(
            select(ChargingSession)
            .where(
                ChargingSession.charge_point_id == charger.id,
                ChargingSession.ended_at.is_(None),
                ChargingSession.abnormal_since.is_(None),
            )
            .with_for_update()
        )
        for transaction in transactions:
            last_contact = max(
                charger.last_seen_at or transaction.received_at, transaction.received_at
            )
            offline_at = last_contact + timedelta(
                seconds=2 * charger.heartbeat_interval_seconds
            )
            if now - offline_at < timedelta(
                seconds=settings.charging_abnormal_offline_seconds
            ):
                continue
            transaction.abnormal_since = now
            review(transaction, "offline_timeout")
            session.add(
                ChargingSessionEvent(
                    session_id=transaction.id,
                    action="offline_timeout",
                    details={"offline_at": offline_at.isoformat()},
                )
            )


async def manual_close(
    session: AsyncSession,
    transaction: ChargingSession,
    actor_id: UUID,
    reason: str,
    *,
    authorization: AuthorizationEvidence | None = None,
) -> None:
    if transaction.ended_at is not None or transaction.abnormal_since is None:
        raise HTTPException(409, "Chỉ được đóng tay phiên bất thường còn mở.")
    latest = await session.scalar(
        select(MeterSample)
        .where(
            MeterSample.session_id == transaction.id,
            MeterSample.measurand == "Energy.Active.Import.Register",
            MeterSample.phase == "",
            MeterSample.location == "Outlet",
        )
        .order_by(MeterSample.timestamp.desc(), MeterSample.id.desc())
        .limit(1)
    )
    if (
        latest is None
        or latest.value < transaction.meter_start_wh
        or transaction.meter_start_wh < 0
    ):
        raise HTTPException(
            409,
            "Chưa có số đo điện năng cuối hợp lệ để đóng tay. Hãy kiểm tra trụ và số đo.",
        )
    now = datetime.now(UTC)
    if latest.timestamp > now or transaction.started_at > now:
        raise HTTPException(
            409, "Thời gian số đo không hợp lệ. Hãy kiểm tra đồng hồ của trụ."
        )
    transaction.meter_stop_wh = latest.value
    transaction.energy_kwh = (latest.value - transaction.meter_start_wh) / 1000
    transaction.ended_at = now
    transaction.manual_closed_at = now
    transaction.closed_by = actor_id
    transaction.manual_close_reason = reason
    transaction.stop_reason = "ManualClosure"
    transaction.abnormal_since = None
    transaction.review_reasons = [
        r
        for r in transaction.review_reasons
        if r not in ("offline_timeout", "available_with_open_session")
    ]
    review(transaction, "manual_closure")
    session.add(
        ChargingSessionEvent(
            session_id=transaction.id,
            actor_id=actor_id,
            action="manual_closure",
            details={
                "permission": authorization.permission if authorization else None,
                "actor_roles": list(authorization.roles) if authorization else None,
                "reason": reason,
                "meter_stop_wh": str(latest.value),
                "meter_at": latest.timestamp.isoformat(),
                "energy_kwh": str(transaction.energy_kwh),
            },
        )
    )
