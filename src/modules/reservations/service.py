"""Hold mutations use charger -> station -> connector -> reservation -> user.

The API commits durable intents. No network I/O belongs in these transactions.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from src.modules.charging.driver_models import DriverStartRequest
from src.modules.charging.driver_provisioning import ensure_driver_resources
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import Role, User, UserRole
from src.modules.ocpp.monitoring import database_time
from src.modules.power.service import power_start_allowed
from src.modules.reservations.models import (
    HOLDS,
    Reservation,
    ReservationCapability,
    ReservationCommand,
    ReservationEvent,
)
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.eligibility import du_so_du_de_sac
from src.platform.audit.service import ghi_nhat_ky


def live(point: ChargePoint, now: datetime) -> bool:
    return bool(
        point.archived_at is None
        and point.status == "online"
        and point.last_boot_at
        and point.last_seen_at
        and point.last_seen_at <= now
        and now - point.last_seen_at
        <= timedelta(seconds=2 * point.heartbeat_interval_seconds)
    )


def capability_status(cap: ReservationCapability | None, point: ChargePoint) -> str:
    if cap is None or cap.boot_at != point.last_boot_at or cap.checked_at is None:
        return "unverified"
    return "supported" if cap.supported else "unsupported"


async def lock_target(
    db: AsyncSession, connector_id: UUID
) -> tuple[ChargePoint, Connector, Station]:
    registered = await db.get(Connector, connector_id)
    if registered is None:
        raise HTTPException(404, "resource_not_found")
    point = await db.scalar(
        select(ChargePoint)
        .where(ChargePoint.id == registered.charge_point_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if point is None:
        raise HTTPException(404, "resource_not_found")
    station = await db.scalar(
        select(Station)
        .where(Station.id == point.station_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    connector = await db.scalar(
        select(Connector)
        .where(Connector.id == connector_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        station is None
        or connector is None
        or point.archived_at
        or connector.archived_at
        or station.archived_at
    ):
        raise HTTPException(404, "resource_not_found")
    return point, connector, station


def event(
    db: AsyncSession,
    reservation: Reservation,
    action: str,
    now: datetime,
    **details: object,
) -> None:
    db.add(
        ReservationEvent(
            reservation_id=reservation.id,
            action=action,
            occurred_at=now,
            details=details,
        )
    )


async def probe_capability(db: AsyncSession, connector_id: UUID) -> dict[str, str]:
    point, _, station = await lock_target(db, connector_id)
    now = await database_time(db)
    if station.status != "active" or not live(point, now):
        raise HTTPException(409, "station_or_charger_unavailable")
    cap = await db.get(ReservationCapability, point.id)
    if cap is None:
        cap = ReservationCapability(
            charge_point_id=point.id,
            boot_at=point.last_boot_at,
            next_attempt_at=now,
            outcome="queued",
        )
        db.add(cap)
    elif cap.boot_at != point.last_boot_at:
        cap.boot_at, cap.supported, cap.checked_at = point.last_boot_at, False, None
        cap.locked_until, cap.lease_token = None, None
        cap.next_attempt_at, cap.outcome = now, "queued"
    await db.flush()
    return {"status": capability_status(cap, point)}


async def create_reservation(
    db: AsyncSession,
    driver_id: UUID,
    request_id: UUID,
    connector_id: UUID,
    arrival_at: datetime | None,
    evidence: AuthorizationEvidence,
    accepted_fee_vnd: int | None = None,
    accepted_policy_version: int | None = None,
) -> Reservation:
    canonical_arrival = (
        arrival_at.astimezone(UTC).isoformat() if arrival_at is not None else "now"
    )
    digest = hashlib.sha256(
        f"{connector_id}|{canonical_arrival}|{accepted_fee_vnd}|{accepted_policy_version}".encode()
    ).hexdigest()
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": request_id.int % (2**63 - 1)},
    )
    previous = await db.get(Reservation, request_id)
    if previous is not None:
        legacy_hash = hashlib.sha256(
            f"{connector_id}|{canonical_arrival}".encode()
        ).hexdigest()
        legacy_retry = (
            previous.fee_decision == "legacy_exempt"
            and accepted_fee_vnd is None
            and accepted_policy_version is None
            and previous.request_hash == legacy_hash
        )
        if (
            previous.driver_id != driver_id
            or previous.request_hash != digest
            and not legacy_retry
        ):
            raise HTTPException(409, "reservation_request_conflict")
        return previous
    if await db.get(ReservationCommand, request_id) is not None:
        raise HTTPException(409, "reservation_request_conflict")
    point, connector, station = await lock_target(db, connector_id)
    now = await database_time(db)
    arrival = arrival_at.astimezone(UTC) if arrival_at is not None else now
    if arrival < now or arrival > now + timedelta(hours=2):
        raise HTTPException(422, "reservation_arrival_out_of_range")
    if station.status != "active" or not live(point, now):
        raise HTTPException(409, "station_or_charger_unavailable")
    cap = await db.get(ReservationCapability, point.id)
    state = capability_status(cap, point)
    if state != "supported":
        raise HTTPException(
            409,
            "reservation_unsupported"
            if state == "unsupported"
            else "reservation_capability_unverified",
        )
    hold = await db.scalar(
        select(Reservation.id).where(
            Reservation.connector_id == connector_id, Reservation.status.in_(HOLDS)
        )
    )
    if hold is not None:
        raise HTTPException(409, "connector_reserved")
    if connector.status != "Available":
        raise HTTPException(409, "connector_unavailable")
    if point.raw_ocpp_status == "Faulted" or point.error_code not in {None, "NoError"}:
        raise HTTPException(409, "connector_unavailable")
    occupied = await db.scalar(
        select(ChargingSession.id)
        .where(
            ChargingSession.connector_id == connector_id,
            or_(
                ChargingSession.ended_at.is_(None),
                (ChargingSession.billing_lifecycle_version == 1)
                & ChargingSession.connector_released_at.is_(None),
            ),
        )
        .limit(1)
    )
    pending = await db.scalar(
        select(DriverStartRequest.id)
        .where(
            DriverStartRequest.connector_id == connector_id,
            DriverStartRequest.status.in_(("Pending", "Accepted")),
        )
        .limit(1)
    )
    if occupied is not None or pending is not None:
        raise HTTPException(409, "connector_unavailable")
    driver = await db.scalar(select(User).where(User.id == driver_id).with_for_update())
    role = await db.scalar(
        select(UserRole.user_id)
        .join(Role)
        .where(UserRole.user_id == driver_id, Role.code == "driver")
    )
    if driver is None or driver.status != "active" or role is None:
        raise HTTPException(403, "permission_denied")
    from src.modules.reservations.policy import quote

    fee_policy = await quote(db, station.id)
    fee = fee_policy["fee_vnd"]
    if (
        (accepted_fee_vnd is not None and accepted_fee_vnd != fee)
        or (
            accepted_policy_version is not None
            and accepted_policy_version != fee_policy["version"]
        )
        or (fee > 0 and (accepted_fee_vnd is None or accepted_policy_version is None))
    ):
        raise HTTPException(409, "reservation_policy_changed")
    if (
        await db.scalar(
            select(Reservation.id).where(
                Reservation.driver_id == driver_id, Reservation.status.in_(HOLDS)
            )
        )
        is not None
    ):
        raise HTTPException(409, "driver_already_reserved")
    if not await power_start_allowed(db, station.id):
        raise HTTPException(409, "power_unavailable")
    from src.modules.wallet.models import Wallet

    await db.scalar(
        select(Wallet).where(Wallet.driver_id == driver_id).with_for_update()
    )
    eligibility = await du_so_du_de_sac(
        db, driver_id=driver_id, station_id=station.id, now=now
    )
    if not eligibility.allowed or eligibility.tariff_id is None:
        raise HTTPException(
            409,
            {
                "reason": eligibility.reason or "tariff_unavailable",
                "balance_vnd": eligibility.balance_vnd,
                "minimum_balance_vnd": eligibility.minimum_balance_vnd,
            },
        )
    tag = await ensure_driver_resources(db, driver)
    if (
        eligibility.minimum_balance_vnd is not None
        and eligibility.balance_vnd is not None
        and eligibility.balance_vnd < eligibility.minimum_balance_vnd + fee
    ):
        raise HTTPException(
            409,
            {
                "reason": "wallet_low",
                "minimum_balance_vnd": eligibility.minimum_balance_vnd + fee,
            },
        )
    identity = await db.get(ChargingCard, tag.card_id)
    if (
        identity is None
        or identity.status != "active"
        or (identity.expires_at is not None and identity.expires_at <= now)
    ):
        raise HTTPException(409, "reservation_identity_unavailable")
    reservation = Reservation(
        id=request_id,
        driver_id=driver_id,
        station_id=station.id,
        charge_point_id=point.id,
        connector_id=connector.id,
        card_id=tag.card_id,
        request_hash=digest,
        status="pending",
        fee_vnd=fee,
        fee_policy_version=fee_policy["version"],
        fee_decision="pending",
        created_at=now,
        arrival_at=arrival,
        expires_at=arrival + timedelta(minutes=15),
        updated_at=now,
    )
    db.add(reservation)
    await db.flush()
    db.add(
        ReservationCommand(
            id=request_id,
            reservation_id=request_id,
            action="ReserveNow",
            created_at=now,
            next_attempt_at=now,
        )
    )
    event(db, reservation, "requested", now)
    await ghi_nhat_ky(
        db,
        actor_id=driver_id,
        action="reservation.requested",
        object_type="reservation",
        object_id=str(request_id),
        data={
            "connector": str(connector.id),
            "expires_at": reservation.expires_at.isoformat(),
        },
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    await db.flush()
    return reservation


async def request_release(
    db: AsyncSession,
    reservation: Reservation,
    now: datetime,
    reason: str,
    request_id: UUID | None = None,
) -> None:
    if reservation.status not in HOLDS:
        return
    if reservation.cancel_requested_at is not None:
        return
    reserve = await db.scalar(
        select(ReservationCommand)
        .where(
            ReservationCommand.reservation_id == reservation.id,
            ReservationCommand.action == "ReserveNow",
        )
        .with_for_update()
    )
    reservation.cancel_requested_at = now
    reservation.cancel_reason = reason
    reservation.cancel_request_id = request_id
    reservation.no_show_exempt = reason == "station_unavailable" or (
        reason == "driver_cancel" and now < reservation.expires_at
    )
    if reservation.no_show_exempt and reservation.fee_decision == "pending":
        from src.modules.reservations.fees import decide

        await decide(db, reservation, "waived", reason, now)
    reservation.updated_at = now
    if reserve is not None and reserve.status == "queued" and reserve.attempts == 0:
        reserve.status = "suppressed"
        reservation.status = "expired" if reason == "expired" else "cancelled"
        reservation.outcome = "not_sent"
    else:
        reservation.status = (
            "expiry_release_pending" if reason == "expired" else "cancel_pending"
        )
        db.add(
            ReservationCommand(
                reservation_id=reservation.id,
                action="CancelReservation",
                created_at=now,
                next_attempt_at=now,
            )
        )
    event(db, reservation, "release_requested", now, reason=reason)


async def cancel_reservation(
    db: AsyncSession,
    driver_id: UUID,
    reservation_id: UUID,
    request_id: UUID,
    evidence: AuthorizationEvidence,
) -> Reservation:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": request_id.int % (2**63 - 1)},
    )
    registered = await db.get(Reservation, reservation_id)
    if registered is None:
        raise HTTPException(404, "resource_not_found")
    if registered.driver_id != driver_id:
        raise HTTPException(403, "permission_denied")
    await lock_target(db, registered.connector_id)
    reservation = await db.scalar(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert reservation is not None
    if (
        reservation.cancel_request_id == request_id
        and reservation.cancel_reason == "driver_cancel"
    ):
        return reservation
    command = await db.get(ReservationCommand, request_id)
    reused = await db.scalar(
        select(Reservation.id).where(Reservation.cancel_request_id == request_id)
    )
    if command is not None or reused is not None:
        raise HTTPException(409, "reservation_request_conflict")
    if reservation.status == "consumed":
        raise HTTPException(409, "reservation_consumed")
    if reservation.status in {"cancel_pending", "expiry_release_pending"}:
        return reservation
    now = await database_time(db)
    if now >= reservation.expires_at:
        raise HTTPException(409, "reservation_expired")
    if reservation.status not in {"active", "uncertain"}:
        raise HTTPException(409, "reservation_not_cancellable")
    await request_release(db, reservation, now, "driver_cancel", request_id)
    await ghi_nhat_ky(
        db,
        actor_id=driver_id,
        action="reservation.cancel_requested",
        object_type="reservation",
        object_id=str(reservation.id),
        data={"request_id": str(request_id)},
        permission=evidence.permission,
        actor_roles=evidence.roles,
    )
    await db.flush()
    return reservation


async def connector_hold(
    db: AsyncSession, connector_id: UUID, *, lock: bool = False
) -> Reservation | None:
    query = select(Reservation).where(
        Reservation.connector_id == connector_id, Reservation.status.in_(HOLDS)
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    result: Reservation | None = await db.scalar(query)
    return result


def admissible(reservation: Reservation, driver_id: UUID, now: datetime) -> bool:
    return bool(
        reservation.driver_id == driver_id
        and reservation.status in {"pending", "uncertain", "active"}
        and reservation.cancel_requested_at is None
        and now < reservation.expires_at
    )


async def authorize_allowed(
    db: AsyncSession, point_id: UUID, card: ChargingCard, now: datetime
) -> bool:
    rows = list(
        await db.scalars(
            select(Reservation).where(
                Reservation.charge_point_id == point_id, Reservation.status.in_(HOLDS)
            )
        )
    )
    if not rows:
        return True
    if any(
        row.card_id == card.id and admissible(row, card.driver_id, now) for row in rows
    ):
        return True
    held = [row.connector_id for row in rows]
    return (
        await db.scalar(
            select(Connector.id)
            .where(
                Connector.charge_point_id == point_id,
                Connector.archived_at.is_(None),
                Connector.id.not_in(held),
                Connector.status.in_(("Available", "Preparing")),
            )
            .limit(1)
        )
        is not None
    )


async def validate_start(
    db: AsyncSession,
    connector: Connector,
    card: ChargingCard | None,
    ocpp_id: int | None,
    source_time: datetime,
    now: datetime,
    message_id: str | None = None,
) -> tuple[bool, Reservation | None]:
    hold = await connector_hold(db, connector.id, lock=True)
    if ocpp_id is not None and (hold is None or hold.ocpp_id != ocpp_id):
        previous = await db.scalar(
            select(Reservation)
            .where(
                Reservation.ocpp_id == ocpp_id, Reservation.connector_id == connector.id
            )
            .with_for_update()
        )
        if (
            previous is not None
            and card is not None
            and previous.card_id == card.id
            and previous.driver_id == card.driver_id
            and previous.created_at - timedelta(seconds=30)
            <= source_time
            < previous.expires_at
            and previous.status != "consumed"
            and not previous.no_show_exempt
        ):
            if now > previous.expires_at + timedelta(seconds=30) or hold is not None:
                from src.modules.reservations.fees import mark_late_start

                await mark_late_start(db, previous, source_time, now, message_id)
                return False, previous
            if previous.status == "expired" and previous.cancel_reason == "expired":
                hold = previous
    if hold is None:
        return ocpp_id is None, None
    if (
        card is None
        or hold.card_id != card.id
        or hold.driver_id != card.driver_id
        or ocpp_id != hold.ocpp_id
    ):
        return False, hold
    timely = (
        hold.created_at - timedelta(seconds=30) <= source_time < hold.expires_at
        and source_time <= now + timedelta(seconds=30)
        and now <= hold.expires_at + timedelta(seconds=30)
    )
    if (
        source_time < hold.expires_at
        and source_time >= hold.created_at - timedelta(seconds=30)
        and now > hold.expires_at + timedelta(seconds=30)
        and not hold.no_show_exempt
    ):
        from src.modules.reservations.fees import mark_late_start

        await mark_late_start(db, hold, source_time, now, message_id)
        return False, hold
    state_ok = hold.status in {"pending", "uncertain", "active"} or (
        hold.status in {"expiry_release_pending", "expired"}
        and hold.cancel_reason == "expired"
    )
    return bool(timely and state_ok), hold


async def consume(
    db: AsyncSession, reservation: Reservation, charging: ChargingSession, now: datetime
) -> None:
    reservation.status, reservation.session_id, reservation.updated_at = (
        "consumed",
        charging.id,
        now,
    )
    reservation.outcome = "StartTransaction"
    if reservation.fee_decision == "pending":
        from src.modules.reservations.fees import decide

        await decide(db, reservation, "waived", "consumed", now)
    event(db, reservation, "consumed", now, session_id=charging.id)


def holds_connector() -> Exists:
    return exists().where(
        Reservation.connector_id == Connector.id, Reservation.status.in_(HOLDS)
    )
