"""Durable, at-most-once configuration writes; ambiguous writes only read back."""

import asyncio
import logging
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.ocpp.configuration_adapter import (
    ConfigurationReply,
    configuration_call,
)
from src.modules.ocpp.configuration_models import ConfigurationIntent
from src.modules.ocpp.connection_registry import OcppConnection, ocpp_connections
from src.modules.ocpp.monitoring import database_time
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import SessionFactory

LIMITS = {"HeartbeatInterval": (30, 600), "MeterValueSampleInterval": (5, 300)}
ACTIVE = ("queued", "sending", "accepted", "reboot_required", "resetting")
_processing_id: ContextVar[UUID | None] = ContextVar(
    "configuration_processing_id", default=None
)


async def charger(db: AsyncSession, identifier: UUID) -> ChargePoint:
    row = await db.scalar(
        select(ChargePoint)
        .join(Station)
        .where(
            ChargePoint.id == identifier,
            ChargePoint.archived_at.is_(None),
            Station.archived_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(404, "Không tìm thấy trụ.")
    return row


async def connection_for(row: ChargePoint) -> OcppConnection | None:
    conn = await ocpp_connections.get(row.code.strip().lower())
    now = datetime.now(UTC)
    return (
        conn
        if (
            conn
            and conn.boot_accepted
            and row.last_seen_at
            and row.last_seen_at
            >= now - timedelta(seconds=row.heartbeat_interval_seconds * 2)
        )
        else None
    )


async def read(
    conn: OcppConnection, keys: list[str]
) -> tuple[str, ConfigurationReply | None]:
    outcome, payload = await configuration_call(
        conn, "GetConfiguration", {"key": keys}, uuid4()
    )
    if outcome != "Accepted":
        return outcome, None
    parsed = ConfigurationReply.model_validate(payload)
    if any(
        item.key in LIMITS and item.value is not None and len(item.value) > 100
        for item in parsed.configurationKey
    ):
        return "ProtocolError", None
    return outcome, parsed


async def submit(
    db: AsyncSession,
    point_id: UUID,
    identifier: UUID,
    actor_id: UUID,
    key: str,
    value: int,
    evidence: AuthorizationEvidence,
) -> ConfigurationIntent:
    if (
        key not in LIMITS
        or type(value) is not int
        or not LIMITS[key][0] <= value <= LIMITS[key][1]
    ):
        raise HTTPException(422, "Cấu hình ngoài phạm vi cho phép.")
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": identifier.int % (2**63 - 1)},
    )
    previous = await db.get(ConfigurationIntent, identifier)
    if previous:
        if (
            previous.charge_point_id,
            previous.actor_id,
            previous.key,
            previous.value,
        ) != (point_id, actor_id, key, value):
            raise HTTPException(409, "Mã yêu cầu đã được dùng.")
        return previous
    if await db.scalar(
        select(ConfigurationIntent.id).where(ConfigurationIntent.reset_id == identifier)
    ):
        raise HTTPException(409, "Mã yêu cầu đã được dùng.")
    point = await charger(db, point_id)
    await db.execute(
        select(ChargePoint.id).where(ChargePoint.id == point_id).with_for_update()
    )
    if await db.scalar(
        select(ConfigurationIntent.id).where(
            ConfigurationIntent.charge_point_id == point_id,
            ConfigurationIntent.state.in_(ACTIVE),
        )
    ):
        raise HTTPException(409, "Trụ có cấu hình đang chờ xử lý.")
    if not await connection_for(point):
        raise HTTPException(409, "Trụ đang ngoại tuyến.")
    row = ConfigurationIntent(
        id=identifier,
        charge_point_id=point_id,
        actor_id=actor_id,
        key=key,
        value=value,
        state="queued",
    )
    db.add(row)
    await db.flush()
    await ghi_nhat_ky(
        db,
        actor_id=actor_id,
        action="ocpp.configuration_requested",
        object_type="charge_point",
        object_id=str(point_id),
        data={"request_id": str(identifier), "key": key, "new_value": value},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    return row


async def busy(db: AsyncSession, point_id: UUID) -> bool:
    charging = await db.scalar(
        select(ChargingSession.id)
        .where(
            ChargingSession.charge_point_id == point_id,
            ChargingSession.ended_at.is_(None),
        )
        .limit(1)
    )
    starting = await db.scalar(
        select(DriverStartRequest.id)
        .where(
            DriverStartRequest.charge_point_id == point_id,
            DriverStartRequest.status.in_(["Pending", "Accepted"]),
        )
        .limit(1)
    )
    reported = await db.scalar(
        select(Connector.id)
        .where(
            Connector.charge_point_id == point_id,
            Connector.archived_at.is_(None),
            Connector.raw_ocpp_status.in_(
                ["Preparing", "Charging", "SuspendedEV", "SuspendedEVSE", "Finishing"]
            ),
        )
        .limit(1)
    )
    return charging is not None or starting is not None or reported is not None


async def request_reset(
    db: AsyncSession,
    point_id: UUID,
    identifier: UUID,
    reset_id: UUID,
    actor_id: UUID,
    evidence: AuthorizationEvidence,
) -> ConfigurationIntent:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": reset_id.int % (2**63 - 1)}
    )
    point = await charger(db, point_id)
    await db.execute(
        select(ChargePoint.id).where(ChargePoint.id == point_id).with_for_update()
    )
    row = await db.scalar(
        select(ConfigurationIntent)
        .where(
            ConfigurationIntent.id == identifier,
            ConfigurationIntent.charge_point_id == point_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Không tìm thấy yêu cầu.")
    if row.reset_id:
        if row.reset_id != reset_id or row.reset_actor_id != actor_id:
            raise HTTPException(409, "Đã có yêu cầu khởi động lại.")
        return row
    if row.state != "reboot_required":
        raise HTTPException(409, "Trụ không chờ khởi động lại.")
    if not await connection_for(point):
        raise HTTPException(409, "Trụ đang ngoại tuyến.")
    if await busy(db, point_id):
        raise HTTPException(409, "Trụ đang có phiên sạc. Hãy chờ phiên kết thúc.")
    if await db.scalar(
        select(ConfigurationIntent.id).where(
            or_(
                ConfigurationIntent.reset_id == reset_id,
                ConfigurationIntent.id == reset_id,
            )
        )
    ):
        raise HTTPException(409, "Mã yêu cầu đã được dùng.")
    row.reset_id = reset_id
    # Invalidate any readback which started before this explicit confirmation.
    row.processing_id = None
    row.reset_actor_id = actor_id
    row.state = "resetting"
    row.outcome = "ResetQueued"
    row.updated_at = await database_time(db)
    row.next_attempt_at = row.updated_at
    await ghi_nhat_ky(
        db,
        actor_id=actor_id,
        action="ocpp.configuration_reset_requested",
        object_type="charge_point",
        object_id=str(point_id),
        data={"request_id": str(identifier), "reset_id": str(reset_id), "type": "Soft"},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    return row


async def finish(
    identifier: UUID, state: str, outcome: str, actual: str | None = None
) -> None:
    async with SessionFactory() as db, db.begin():
        point_id = await db.scalar(
            select(ConfigurationIntent.charge_point_id).where(
                ConfigurationIntent.id == identifier
            )
        )
        assert point_id
        await db.execute(
            select(ChargePoint.id).where(ChargePoint.id == point_id).with_for_update()
        )
        row = await db.get(ConfigurationIntent, identifier, with_for_update=True)
        assert row
        if (
            _processing_id.get() is not None
            and row.processing_id != _processing_id.get()
        ):
            return
        changed = (row.state, row.outcome, row.actual_value) != (state, outcome, actual)
        row.state = state
        row.outcome = outcome
        row.actual_value = actual
        row.updated_at = await database_time(db)
        row.next_attempt_at = row.updated_at + timedelta(
            seconds=40 if state == "accepted" else 10
        )
        if state == "verified":
            row.verified_at = row.updated_at
            if row.key == "HeartbeatInterval":
                point = await db.get(
                    ChargePoint, row.charge_point_id, with_for_update=True
                )
                assert point
                point.heartbeat_interval_seconds = row.value
        if changed:
            await ghi_nhat_ky(
                db,
                actor_id=row.actor_id,
                action="ocpp.configuration_result",
                object_type="charge_point",
                object_id=str(row.charge_point_id),
                data={
                    "request_id": str(identifier),
                    "key": row.key,
                    "old_value": row.old_value,
                    "new_value": row.value,
                    "actual_value": actual,
                    "state": state,
                    "result": outcome,
                },
            )


async def verify(
    identifier: UUID,
    conn: OcppConnection,
    key: str,
    value: int,
    pending_reboot: bool = False,
) -> None:
    outcome, payload = await read(conn, [key])
    if payload is None:
        await finish(
            identifier,
            "resetting"
            if pending_reboot and await reset_was_requested(identifier)
            else "needs_review"
            if outcome == "ProtocolError"
            else "reboot_required"
            if pending_reboot
            else "accepted",
            outcome,
        )
        return
    entry = next((item for item in payload.configurationKey if item.key == key), None)
    if entry is None or key in payload.unknownKey or entry.readonly:
        await finish(
            identifier,
            "resetting"
            if pending_reboot and await reset_was_requested(identifier)
            else "needs_review",
            "ReadbackUnsupported",
            entry.value if entry else None,
        )
    elif entry.value == str(value):
        await finish(identifier, "verified", "Verified", entry.value)
    else:
        await finish(
            identifier,
            "resetting"
            if pending_reboot and await reset_was_requested(identifier)
            else "reboot_required"
            if pending_reboot
            else "needs_review",
            "ReadbackMismatch",
            entry.value,
        )


async def reset_was_requested(identifier: UUID) -> bool:
    async with SessionFactory() as db:
        return (
            await db.scalar(
                select(ConfigurationIntent.reset_id).where(
                    ConfigurationIntent.id == identifier
                )
            )
            is not None
        )


async def process(identifier: UUID) -> None:
    token = _processing_id.set(uuid4())
    try:
        await _process(identifier)
    finally:
        _processing_id.reset(token)


async def _process(identifier: UUID) -> None:
    # A committed lease prevents concurrent workers from dispatching twice.
    async with SessionFactory() as db, db.begin():
        row = await db.scalar(
            select(ConfigurationIntent)
            .where(ConfigurationIntent.id == identifier)
            .with_for_update(skip_locked=True)
        )
        now = await database_time(db)
        if row is None or row.state not in ACTIVE or row.next_attempt_at > now:
            return
        try:
            point = await charger(db, row.charge_point_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            row.state = "failed" if row.state == "queued" else "needs_review"
            row.outcome = "Archived"
            row.updated_at = now
            await ghi_nhat_ky(
                db,
                actor_id=row.actor_id,
                action="ocpp.configuration_result",
                object_type="charge_point",
                object_id=str(row.charge_point_id),
                data={
                    "request_id": str(row.id),
                    "key": row.key,
                    "new_value": row.value,
                    "state": row.state,
                    "result": row.outcome,
                },
            )
            return
        conn = await connection_for(point)
        if conn is None:
            row.next_attempt_at = now + timedelta(seconds=10)
            if row.state == "queued":
                row.state = "failed"
                row.outcome = "Offline"
                row.updated_at = now
                await ghi_nhat_ky(
                    db,
                    actor_id=row.actor_id,
                    action="ocpp.configuration_result",
                    object_type="charge_point",
                    object_id=str(row.charge_point_id),
                    data={
                        "request_id": str(row.id),
                        "key": row.key,
                        "new_value": row.value,
                        "state": "failed",
                        "result": "Offline",
                    },
                )
            return
        state, key, value = row.state, row.key, row.value
        reset_queued = state == "resetting" and row.outcome in {
            "ResetQueued",
            "ChargingBlocked",
        }
        reset_id = row.reset_id
        row.processing_id = _processing_id.get()
        if state == "queued":
            row.state = "sending"
        if reset_queued:
            row.outcome = "ResetSending"
        row.next_attempt_at = now + timedelta(seconds=120)
    if state == "queued":
        outcome, payload = await read(conn, [key])
        entry = (
            next((item for item in payload.configurationKey if item.key == key), None)
            if payload
            else None
        )
        if entry is None or entry.readonly or entry.value is None:
            await finish(
                identifier, "failed", outcome if payload is None else "NotSupported"
            )
            return
        async with SessionFactory() as db, db.begin():
            stored = await db.get(ConfigurationIntent, identifier, with_for_update=True)
            assert stored
            if (
                stored.processing_id != _processing_id.get()
                or stored.state != "sending"
            ):
                return
            stored.old_value = entry.value
            await ghi_nhat_ky(
                db,
                actor_id=stored.actor_id,
                action="ocpp.configuration_dispatch",
                object_type="charge_point",
                object_id=str(stored.charge_point_id),
                data={
                    "request_id": str(identifier),
                    "key": key,
                    "old_value": entry.value,
                    "new_value": value,
                },
            )
        outcome, _ = await configuration_call(
            conn, "ChangeConfiguration", {"key": key, "value": str(value)}, identifier
        )
        if outcome in {"Rejected", "NotSupported", "ProtocolError"}:
            await finish(identifier, "failed", outcome)
            return
        if outcome == "RebootRequired":
            await finish(identifier, "reboot_required", outcome, entry.value)
            return
        if outcome != "Accepted":
            await finish(identifier, "accepted", outcome)
            await verify(identifier, conn, key, value)
            return
        await finish(identifier, "accepted", "Accepted", entry.value)
        await verify(identifier, conn, key, value)
    elif reset_queued:
        assert reset_id
        # Start admission checks the durable reset gate. Release DB locks before
        # waiting for the reply, because OCPP contact recording locks this row too.
        async with SessionFactory() as db, db.begin():
            await db.execute(
                select(ChargePoint.id)
                .where(ChargePoint.id == point.id)
                .with_for_update()
            )
            blocked = await busy(db, point.id)
        if blocked:
            await finish(identifier, "resetting", "ChargingBlocked")
            return
        outcome, _ = await configuration_call(conn, "Reset", {"type": "Soft"}, reset_id)
        if outcome == "Accepted":
            await finish(identifier, "reboot_required", "ResetAccepted")
        elif outcome in {"Timeout", "Disconnected", "ProtocolError", "RebootRequired"}:
            # The reset may still arrive. Keep start admission closed and only read back.
            await finish(identifier, "resetting", "Reset" + outcome)
        else:
            await finish(identifier, "needs_review", "Reset" + outcome)
    else:
        # Crash during a write: NEVER replay ChangeConfiguration/Reset.
        await verify(
            identifier,
            conn,
            key,
            value,
            pending_reboot=state in {"reboot_required", "resetting"},
        )


async def cycle() -> None:
    async with SessionFactory() as db:
        now = await database_time(db)
        ids = (
            await db.scalars(
                select(ConfigurationIntent.id)
                .where(
                    ConfigurationIntent.state.in_(ACTIVE),
                    ConfigurationIntent.next_attempt_at <= now,
                )
                .order_by(ConfigurationIntent.created_at)
                .limit(20)
            )
        ).all()
    await asyncio.gather(*(process(identifier) for identifier in ids))


async def configuration_loop() -> None:
    while True:
        try:
            await cycle()
        except Exception:
            logging.getLogger("csms.ocpp").exception("configuration_worker_failed")
        await asyncio.sleep(2)
