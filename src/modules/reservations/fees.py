"""S-50: conservative, atomic no-show decisions independent of socket ACKs."""

import asyncio
import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ocpp.monitoring import database_time
from src.modules.reservations.models import Reservation, ReservationCapability
from src.modules.reservations.service import (
    capability_status,
    event,
    live,
    lock_target,
    request_release,
)
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet
from src.modules.wallet.service import ghi_so_cai
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.reservation_fees")


async def observe_expiry(
    db: AsyncSession,
    row: Reservation,
    point: ChargePoint,
    station: Station,
    now: datetime,
) -> None:
    if row.fee_decision != "pending" or now < row.expires_at:
        return
    cap = await db.get(ReservationCapability, point.id)
    from src.modules.ocpp.connection_registry import ocpp_connections

    connection = await ocpp_connections.get(point.code.strip().lower())
    connector = await db.get(Connector, row.connector_id)
    eligible = bool(
        row.activated_at is not None
        and row.activated_at < row.expires_at
        and station.status == "active"
        and live(point, now)
        and capability_status(cap, point) == "supported"
        and point.last_boot_at is not None
        and point.last_boot_at <= row.created_at
        and point.error_code in {None, "NoError"}
        and point.raw_ocpp_status != "Faulted"
        and connector is not None
        and connector.status not in {"Faulted", "Unavailable"}
    )
    eligible = eligible and connection is not None and connection.boot_accepted
    if row.expiry_fee_eligible is None:
        row.expiry_fee_eligible = eligible
    elif not eligible:
        row.expiry_fee_eligible = False


async def decide(
    db: AsyncSession, row: Reservation, decision: str, reason: str, now: datetime
) -> None:
    if row.fee_decision == decision and row.fee_reason == reason:
        return
    row.fee_decision, row.fee_reason, row.fee_decided_at = decision, reason, now
    event(
        db,
        row,
        "fee_decided",
        now,
        decision=decision,
        reason=reason,
        fee_vnd=row.fee_vnd,
        ledger_id=row.fee_ledger_id,
    )
    await ghi_nhat_ky(
        db,
        actor_id=None,
        action="reservation.fee_decided",
        object_type="reservation",
        object_id=str(row.id),
        data={
            "decision": decision,
            "reason": reason,
            "fee_vnd": row.fee_vnd,
            "ledger_id": row.fee_ledger_id,
        },
    )


async def mark_late_start(
    db: AsyncSession,
    row: Reservation,
    source_time: datetime,
    now: datetime,
    message_id: str | None,
) -> None:
    if (
        row.fee_vnd > 0
        and row.fee_decision != "legacy_exempt"
        and not row.no_show_exempt
    ):
        await decide(db, row, "review", "late_start_after_fee_window", now)
    details: dict[str, object] = {
        "source_timestamp": source_time.isoformat(),
        "received_at": now.isoformat(),
        "message_id": message_id,
        "needs_review": True,
    }
    event(db, row, "late_start_observed", now, **details)
    await ghi_nhat_ky(
        db,
        actor_id=None,
        action="reservation.late_start_observed",
        object_type="reservation",
        object_id=str(row.id),
        data=details,
    )


async def fee_one(reservation_id: UUID) -> None:
    async with SessionFactory() as db, db.begin():
        registered = await db.get(Reservation, reservation_id)
        if registered is None:
            return
        point, _, station = await lock_target(db, registered.connector_id)
        row = await db.scalar(
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert row is not None
        now = await database_time(db)
        if row.fee_decision != "pending" or now < row.expires_at + timedelta(
            seconds=30
        ):
            return
        await observe_expiry(db, row, point, station, now)
        if row.status == "consumed" or row.session_id is not None:
            await decide(db, row, "waived", "consumed", now)
        elif (
            row.no_show_exempt
            or row.cancel_reason == "driver_cancel"
            and row.cancel_requested_at is not None
            and row.cancel_requested_at < row.expires_at
        ):
            await decide(db, row, "waived", "cancelled_before_expiry", now)
        elif row.status == "rejected" or row.outcome == "not_sent":
            await decide(db, row, "waived", "never_reserved", now)
        elif row.fee_vnd == 0:
            await request_release(db, row, now, "expired")
            await decide(db, row, "waived", "zero_fee", now)
        elif (
            row.expiry_fee_eligible is not True
            or point.last_seen_at is None
            or point.last_seen_at < row.expires_at
        ):
            await request_release(db, row, now, "expired")
            await decide(db, row, "review", "reservation_not_verified_at_expiry", now)
        else:
            await request_release(db, row, now, "expired")
            wallet = await db.scalar(
                select(Wallet)
                .where(Wallet.driver_id == row.driver_id)
                .with_for_update()
            )
            if wallet is None or wallet.status != "active":
                await decide(db, row, "review", "wallet_unavailable", now)
                return
            ledger = await ghi_so_cai(
                db,
                wallet_id=wallet.id,
                entry_type="reservation_fee",
                amount_vnd=-row.fee_vnd,
                reference_type="reservation",
                reference_id=str(row.id),
            )
            row.fee_ledger_id = ledger.id
            await decide(db, row, "charged", "no_show", now)


async def fee_cycle() -> None:
    async with SessionFactory() as db:
        now = await database_time(db)
        ids = list(
            await db.scalars(
                select(Reservation.id)
                .where(
                    Reservation.fee_decision == "pending",
                    Reservation.expires_at <= now - timedelta(seconds=30),
                )
                .order_by(Reservation.expires_at)
                .limit(100)
            )
        )
    for identifier in ids:
        try:
            await fee_one(identifier)
        except Exception:  # noqa: BLE001 -- a failed transaction stays pending for recovery.
            logger.error("reservation_fee_failed id=%s", identifier)


async def fee_loop() -> None:
    while True:
        try:
            await fee_cycle()
        except SQLAlchemyError:
            logger.error("reservation_fee_cycle_failed")
        await asyncio.sleep(15)
