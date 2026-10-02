"""Shared server-to-charger calls, durable audit and stop confirmation deadline."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, WebSocketDisconnect
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.models import ChargingSession, ChargingSessionEvent
from src.modules.identity.models import User
from src.modules.ocpp.connection_registry import ocpp_connections
from src.modules.ocpp.control_models import ControlRequest, ControlResult
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import SessionFactory

COMMAND_TIMEOUT = 30.0
STOP_CONFIRMATION_SECONDS = 120


async def record_result(
    session: AsyncSession, command_id: UUID, status: str, now: datetime
) -> None:
    await session.execute(
        insert(ControlResult)
        .values(command_id=command_id, status=status, received_at=now)
        .on_conflict_do_nothing()
    )


async def command_status(session: AsyncSession, command_id: UUID) -> str:
    return (
        await session.scalar(
            select(ControlResult.status).where(ControlResult.command_id == command_id)
        )
        or "Pending"
    )


async def execute_command(
    actor_id: UUID,
    command_id: UUID,
    action: str,
    target: UUID | int,
    reset_type: str = "Soft",
) -> dict[str, object]:
    now = datetime.now(UTC)
    payload: dict[str, object] = (
        {"type": reset_type} if action == "Reset" else {"transactionId": target}
    )
    connection = None
    async with SessionFactory() as session, session.begin():
        # Serialize identical request keys without holding locks during the socket wait.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": command_id.int % (2**63 - 1)},
        )
        previous = await session.get(ControlRequest, command_id)
        if previous is not None:
            matches_target = (
                previous.charge_point_id == target
                if action == "Reset"
                else previous.transaction_id == target
            )
            if (
                previous.actor_id != actor_id
                or previous.action != action
                or previous.payload != payload
                or not matches_target
            ):
                raise HTTPException(409, "Mã yêu cầu đã được dùng cho thao tác khác.")
            return {
                "id": command_id,
                "status": await command_status(session, command_id),
            }
        transaction_id = None
        if action == "RemoteStopTransaction":
            charging = await session.get(ChargingSession, target)
            if charging is None:
                raise HTTPException(404, "Không tìm thấy phiên sạc.")
            if charging.ended_at is not None:
                raise HTTPException(409, "Phiên đã kết thúc.")
            charger_id = charging.charge_point_id
            transaction_id = charging.id
        else:
            if not isinstance(target, UUID):
                raise HTTPException(422, "Mã trụ không hợp lệ.")
            charger_id = target
        charger = await session.get(ChargePoint, charger_id)
        station = await session.get(Station, charger.station_id) if charger else None
        if charger is None or station is None or station.archived_at is not None:
            raise HTTPException(404, "Không tìm thấy trụ sạc.")
        session.add(
            ControlRequest(
                id=command_id,
                actor_email=await session.scalar(
                    select(User.email).where(User.id == actor_id)
                )
                or str(actor_id),
                charge_point_code=charger.code,
                actor_id=actor_id,
                charge_point_id=charger_id,
                transaction_id=transaction_id,
                action=action,
                payload=payload,
                created_at=now,
            )
        )
        await session.flush()
        connection = await ocpp_connections.get(charger.code.strip().lower())
        live = (
            charger.last_seen_at is not None
            and charger.last_seen_at
            >= now - timedelta(seconds=charger.heartbeat_interval_seconds * 2)
        )
        if (
            charger.archived_at is not None
            or connection is None
            or not connection.boot_accepted
            or not live
        ):
            await record_result(session, command_id, "Offline", now)
            return {"id": command_id, "status": "Offline"}
    try:
        reply = await connection.call(
            action, payload, timeout=COMMAND_TIMEOUT, message_id=str(command_id)
        )
        result = reply.payload.get("status") if reply.kind == 3 else None
        outcome = result if result in ("Accepted", "Rejected") else "ProtocolError"
    except TimeoutError:
        outcome = "Timeout"
    except (ConnectionError, OSError, RuntimeError, WebSocketDisconnect):
        outcome = "Disconnected"
    async with SessionFactory() as session, session.begin():
        await record_result(session, command_id, str(outcome), datetime.now(UTC))
        return {"id": command_id, "status": await command_status(session, command_id)}


async def scan_control_deadlines(
    session: AsyncSession, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    # Persist a timeout even when the process restarted during a request. Never resend.
    pending = (
        await session.scalars(
            select(ControlRequest.id)
            .outerjoin(ControlResult)
            .where(
                ControlResult.command_id.is_(None),
                ControlRequest.created_at
                < now - timedelta(seconds=COMMAND_TIMEOUT + 1),
            )
        )
    ).all()
    for command_id in pending:
        await record_result(session, command_id, "Timeout", now)
    transaction_ids = (
        await session.scalars(
            select(ControlRequest.transaction_id)
            .join(ControlResult)
            .join(ChargingSession, ChargingSession.id == ControlRequest.transaction_id)
            .where(
                ControlRequest.action == "RemoteStopTransaction",
                ControlResult.status == "Accepted",
                ControlResult.received_at
                <= now - timedelta(seconds=STOP_CONFIRMATION_SECONDS),
                ChargingSession.ended_at.is_(None),
            )
        )
    ).all()
    changed = 0
    for transaction_id in set(transaction_ids):
        charging = await session.scalar(
            select(ChargingSession)
            .where(ChargingSession.id == transaction_id)
            .with_for_update()
        )
        if (
            charging is not None
            and charging.ended_at is None
            and "remote_stop_not_confirmed" not in charging.review_reasons
        ):
            charging.review_reasons = [
                *charging.review_reasons,
                "remote_stop_not_confirmed",
            ]
            session.add(
                ChargingSessionEvent(
                    session_id=charging.id,
                    action="remote_stop_not_confirmed",
                    details={},
                    occurred_at=now,
                )
            )
            changed += 1
    return changed


async def control_loop() -> None:
    import logging

    from sqlalchemy.exc import SQLAlchemyError

    while True:
        try:
            async with SessionFactory() as session, session.begin():
                await scan_control_deadlines(session)
        except SQLAlchemyError:
            logging.getLogger("csms.ocpp").error("ocpp_control_scan_failed")
        await asyncio.sleep(1)
