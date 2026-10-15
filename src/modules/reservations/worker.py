"""One ReserveNow attempt; uncertain results retain holds until release evidence."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException, WebSocketDisconnect
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.charging.driver_models import DriverVirtualTag
from src.modules.charging.models import ChargingSession
from src.modules.ocpp.connection_registry import OcppConnection, ocpp_connections
from src.modules.ocpp.monitoring import database_time
from src.modules.reservations.models import (
    HOLDS,
    Reservation,
    ReservationCapability,
    ReservationCommand,
)
from src.modules.reservations.service import event, live, lock_target, request_release
from src.modules.stations.models import ChargePoint
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.reservations")


async def wire(
    connection: OcppConnection,
    action: str,
    payload: dict[str, object],
    message_id: UUID,
) -> tuple[str, dict[str, object]]:
    try:
        reply = await connection.call(
            action,
            payload,
            timeout=settings.reservation_command_timeout_seconds,
            message_id=str(message_id),
        )
        if reply.kind != 3:
            return "ProtocolError", {}
        if action == "GetConfiguration":
            return "Accepted", reply.payload
        allowed = (
            {"Accepted", "Rejected"}
            if action == "CancelReservation"
            else {"Accepted", "Occupied", "Rejected", "Unavailable", "Faulted"}
        )
        status = reply.payload.get("status")
        if (
            set(reply.payload) != {"status"}
            or not isinstance(status, str)
            or status not in allowed
        ):
            return "ProtocolError", {}
        return str(status), {}
    except TimeoutError:
        return "Timeout", {}
    except (ConnectionError, OSError, RuntimeError, WebSocketDisconnect):
        return "Disconnected", {}


async def probe_one(point_id: UUID) -> None:
    async with SessionFactory() as db, db.begin():
        point = await db.scalar(
            select(ChargePoint).where(ChargePoint.id == point_id).with_for_update()
        )
        if point is None:
            return
        cap = await db.get(ReservationCapability, point_id)
        now = await database_time(db)
        if cap is None or not live(point, now) or cap.next_attempt_at > now:
            return
        if cap.boot_at == point.last_boot_at and cap.checked_at is not None:
            return
        if cap.locked_until is not None and cap.locked_until > now:
            return
        connection = await ocpp_connections.get(point.code.strip().lower())
        if connection is None or not connection.boot_accepted:
            return
        token = uuid4()
        cap.lease_token, cap.locked_until = token, now + timedelta(seconds=60)
        cap.boot_at, cap.checked_at, cap.supported = point.last_boot_at, None, False
        boot = point.last_boot_at
    outcome, payload = await wire(
        connection, "GetConfiguration", {"key": ["SupportedFeatureProfiles"]}, token
    )
    values = payload.get("configurationKey")
    profiles = (
        [
            entry.get("value")
            for entry in values
            if isinstance(entry, dict)
            and entry.get("key") == "SupportedFeatureProfiles"
        ]
        if isinstance(values, list)
        else []
    )
    supported = any(
        isinstance(value, str)
        and "Reservation" in {item.strip() for item in value.split(",")}
        for value in profiles
    )
    async with SessionFactory() as db, db.begin():
        point = await db.scalar(
            select(ChargePoint).where(ChargePoint.id == point_id).with_for_update()
        )
        cap = await db.get(ReservationCapability, point_id)
        if (
            cap is None
            or point is None
            or cap.lease_token != token
            or point.last_boot_at != boot
        ):
            return
        now = await database_time(db)
        cap.lease_token, cap.locked_until = None, None
        if outcome == "Accepted" and isinstance(values, list):
            cap.checked_at, cap.supported = now, supported
            cap.outcome = "supported" if supported else "unsupported"
        else:
            cap.outcome, cap.next_attempt_at = outcome, now + timedelta(seconds=30)


@dataclass(frozen=True)
class Delivery:
    command_id: UUID
    reservation_id: UUID
    token: UUID
    action: str
    connection: OcppConnection
    payload: dict[str, object]


async def claim(command_id: UUID) -> Delivery | None:
    async with SessionFactory() as db, db.begin():
        candidate = await db.get(ReservationCommand, command_id)
        if candidate is None:
            return None
        registered = await db.get(Reservation, candidate.reservation_id)
        if registered is None:
            return None
        point, connector, station = await lock_target(db, registered.connector_id)
        reservation = await db.scalar(
            select(Reservation)
            .where(Reservation.id == registered.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        command = await db.scalar(
            select(ReservationCommand)
            .where(ReservationCommand.id == command_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert reservation is not None and command is not None
        now = await database_time(db)
        if command.status != "queued" or command.next_attempt_at > now:
            return None
        if reservation.status not in HOLDS:
            command.status = "suppressed"
            return None
        connection = await ocpp_connections.get(point.code.strip().lower())
        if connection is None or not connection.boot_accepted or not live(point, now):
            return None
        if command.action == "ReserveNow":
            if (
                station.status != "active"
                or now >= reservation.expires_at
                or reservation.cancel_requested_at is not None
            ):
                await request_release(
                    db,
                    reservation,
                    now,
                    "station_unavailable" if station.status != "active" else "expired",
                )
                return None
            cap = await db.get(ReservationCapability, point.id)
            if (
                cap is None
                or not cap.supported
                or cap.checked_at is None
                or cap.boot_at != point.last_boot_at
            ):
                command.status, command.outcome = "done", "capability_changed"
                reservation.status, reservation.outcome = (
                    "rejected",
                    "capability_changed",
                )
                reservation.updated_at = now
                event(db, reservation, "rejected", now, outcome="capability_changed")
                return None
            tag = await db.get(DriverVirtualTag, reservation.driver_id)
            if tag is None or tag.card_id != reservation.card_id:
                command.status, command.outcome = "done", "identity_changed"
                reservation.status, reservation.outcome = "rejected", "identity_changed"
                return None
            payload: dict[str, object] = {
                "connectorId": connector.connector_number,
                "reservationId": reservation.ocpp_id,
                "idTag": tag.id_tag,
                "expiryDate": reservation.expires_at.isoformat(),
            }
        else:
            reserve = await db.scalar(
                select(ReservationCommand).where(
                    ReservationCommand.reservation_id == reservation.id,
                    ReservationCommand.action == "ReserveNow",
                )
            )
            if reserve is not None and reserve.status == "sending":
                return None
            payload = {"reservationId": reservation.ocpp_id}
        token = uuid4()
        command.status, command.attempts = "sending", command.attempts + 1
        command.lease_token, command.locked_until = (
            token,
            now
            + timedelta(seconds=60 + 2 * settings.reservation_command_timeout_seconds),
        )
        return Delivery(
            command.id, reservation.id, token, command.action, connection, payload
        )


async def deliver(delivery: Delivery) -> None:
    # Reserve is never re-sent after uncertainty. Cancel retry is idempotent at
    # reservationId; each wire attempt has a fresh messageId after timeout.
    outcome, _ = await wire(
        delivery.connection,
        delivery.action,
        delivery.payload,
        delivery.command_id if delivery.action == "ReserveNow" else delivery.token,
    )
    async with SessionFactory() as db, db.begin():
        registered = await db.get(Reservation, delivery.reservation_id)
        if registered is None:
            return
        await lock_target(db, registered.connector_id)
        reservation = await db.scalar(
            select(Reservation)
            .where(Reservation.id == registered.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        command = await db.scalar(
            select(ReservationCommand)
            .where(ReservationCommand.id == delivery.command_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert command is not None and reservation is not None
        if command.lease_token != delivery.token:
            return
        now = await database_time(db)
        command.outcome, command.locked_until, command.lease_token = outcome, None, None
        if delivery.action == "ReserveNow":
            definitive = outcome in {
                "Accepted",
                "Occupied",
                "Rejected",
                "Unavailable",
                "Faulted",
            }
            command.status = "done" if definitive else "uncertain"
            if reservation.status not in HOLDS:
                return
            if outcome in {"Occupied", "Rejected", "Unavailable", "Faulted"}:
                reservation.status = "rejected"
            elif reservation.cancel_requested_at is None:
                reservation.status = "active" if outcome == "Accepted" else "uncertain"
            if outcome == "Accepted" and reservation.activated_at is None:
                reservation.activated_at = now
            reservation.outcome, reservation.updated_at = outcome, now
            event(db, reservation, "reserve_outcome", now, outcome=outcome)
        elif outcome == "Accepted":
            command.status = "done"
            if reservation.status in HOLDS:
                reservation.status = (
                    "expired" if reservation.cancel_reason == "expired" else "cancelled"
                )
                reservation.outcome, reservation.updated_at = outcome, now
                event(db, reservation, "release_confirmed", now)
        else:
            command.status = "queued"
            command.next_attempt_at = now + timedelta(
                seconds=min(300, 15 * 2 ** min(command.attempts - 1, 4))
            )
            if reservation.status in HOLDS:
                reservation.outcome, reservation.updated_at = outcome, now


async def reconcile(reservation_id: UUID) -> None:
    async with SessionFactory() as db, db.begin():
        registered = await db.get(Reservation, reservation_id)
        if registered is None:
            return
        point, connector, station = await lock_target(db, registered.connector_id)
        reservation = await db.scalar(
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert reservation is not None
        if reservation.status not in HOLDS:
            return
        now = await database_time(db)
        from src.modules.reservations.fees import observe_expiry

        await observe_expiry(db, reservation, point, station, now)
        commands = list(
            await db.scalars(
                select(ReservationCommand)
                .where(ReservationCommand.reservation_id == reservation_id)
                .with_for_update()
            )
        )
        if (
            point.last_boot_at is not None
            and point.last_boot_at > reservation.created_at
            and reservation.status == "active"
        ):
            reservation.status, reservation.outcome, reservation.updated_at = (
                "uncertain",
                "charger_reboot",
                now,
            )
            event(db, reservation, "uncertain", now, outcome="charger_reboot")
        for command in commands:
            if (
                command.status == "sending"
                and command.locked_until is not None
                and command.locked_until <= now
            ):
                command.lease_token, command.locked_until, command.outcome = (
                    None,
                    None,
                    "lease_expired",
                )
                command.status = (
                    "uncertain" if command.action == "ReserveNow" else "queued"
                )
                command.next_attempt_at = now
                if command.action == "ReserveNow" and reservation.status == "pending":
                    reservation.status, reservation.outcome = (
                        "uncertain",
                        "lease_expired",
                    )
                    reservation.updated_at = now
                    event(db, reservation, "uncertain", now)
        if station.status != "active":
            await request_release(db, reservation, now, "station_unavailable")
        elif now >= reservation.expires_at:
            await request_release(db, reservation, now, "expired")
        # Expiry plus a fresh, source-ordered Available on a live charger is
        # release evidence. A heartbeat or an API intent cannot manufacture it.
        if (
            now >= reservation.expires_at + timedelta(seconds=30)
            and live(point, now)
            and connector.status == "Available"
            and connector.raw_ocpp_status == "Available"
            and connector.last_status_notification_at is not None
            and reservation.expires_at
            <= connector.last_status_notification_at
            <= now + timedelta(seconds=30)
            and connector.status_updated_at >= reservation.expires_at
        ):
            occupied = await db.scalar(
                select(ChargingSession.id)
                .where(
                    ChargingSession.connector_id == connector.id,
                    or_(
                        ChargingSession.ended_at.is_(None),
                        (ChargingSession.billing_lifecycle_version == 1)
                        & ChargingSession.connector_released_at.is_(None),
                    ),
                )
                .limit(1)
            )
            if occupied is None:
                reservation.status = (
                    "cancelled" if reservation.no_show_exempt else "expired"
                )
                reservation.outcome, reservation.updated_at = "expiry_observed", now
                for command in commands:
                    if command.status == "queued":
                        command.status = "suppressed"
                event(db, reservation, "expiry_observed", now)


async def cycle() -> None:
    sockets = await ocpp_connections.snapshot()
    connected = [key for key, value in sockets.items() if value.boot_accepted]
    async with SessionFactory() as db:
        now = await database_time(db)
        points = list(
            await db.scalars(
                select(ReservationCapability.charge_point_id)
                .join(ChargePoint)
                .where(
                    ReservationCapability.charge_point_id.in_(connected),
                    ReservationCapability.next_attempt_at <= now,
                    or_(
                        ReservationCapability.checked_at.is_(None),
                        ReservationCapability.boot_at.is_distinct_from(
                            ChargePoint.last_boot_at
                        ),
                    ),
                )
                .limit(50)
            )
        )
        holds = list(
            await db.scalars(
                select(Reservation.id).where(Reservation.status.in_(HOLDS))
            )
        )
    for reservation_id in holds:
        try:
            await reconcile(reservation_id)
        except HTTPException:
            logger.warning("reservation_target_unavailable id=%s", reservation_id)
    await asyncio.gather(*(probe_one(point) for point in points))
    async with SessionFactory() as db:
        now = await database_time(db)
        ids = list(
            await db.scalars(
                select(ReservationCommand.id)
                .join(Reservation)
                .where(
                    Reservation.charge_point_id.in_(connected),
                    ReservationCommand.status == "queued",
                    ReservationCommand.next_attempt_at <= now,
                )
                .order_by(ReservationCommand.created_at)
                .limit(50)
            )
        )
    deliveries = [
        delivery
        for command_id in ids
        if (delivery := await claim(command_id)) is not None
    ]
    await asyncio.gather(*(deliver(delivery) for delivery in deliveries))


async def reservation_loop() -> None:
    while True:
        try:
            await cycle()
        except SQLAlchemyError:
            logger.error("reservation_cycle_failed")
        await asyncio.sleep(2)
