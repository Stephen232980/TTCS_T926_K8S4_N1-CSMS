"""Lease persisted intents; send SMTP after commit and retry with stable identity."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.driver_notifications.models import DriverNotification
from src.modules.driver_notifications.service import scan_idle
from src.modules.identity.models import User
from src.platform.database.session import SessionFactory
from src.platform.email import send_email, smtp_enabled

logger = logging.getLogger("csms.driver_notifications")


async def deliver_one() -> bool:
    if not smtp_enabled():
        return False
    now = datetime.now(UTC)
    async with SessionFactory() as db, db.begin():
        row = await db.scalar(
            select(DriverNotification)
            .join(User, User.id == DriverNotification.driver_id)
            .where(
                User.status == "active",
                or_(
                    and_(
                        DriverNotification.email_status == "pending",
                        DriverNotification.next_attempt_at <= now,
                    ),
                    and_(
                        DriverNotification.email_status == "sending",
                        DriverNotification.lease_until <= now,
                    ),
                ),
                DriverNotification.created_at
                >= now - timedelta(days=settings.driver_notification_retention_days),
            )
            .order_by(DriverNotification.next_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=DriverNotification)
        )
        if row is None:
            return False
        user = await db.get(User, row.driver_id)
        if user is None or user.status != "active":
            await db.delete(row)
            return True
        token = uuid4()
        row.email_status = "sending"
        row.lease_token = token
        row.lease_until = now + timedelta(minutes=2)
        row.attempts += 1
        item_id, recipient, title, body, attempts = (
            row.id,
            user.email,
            row.title,
            row.message,
            row.attempts,
        )
    try:
        await asyncio.to_thread(
            send_email,
            recipient=recipient,
            subject="[CSMS] " + title,
            text_body=body,
            message_id=f"<csms-driver-{item_id}@csms.invalid>",
        )
        status = "sent"
    except (OSError, ValueError):
        status = "pending"
    # SMTP errors inherit OSError. No raw address, exception text or PII in logs.
    async with SessionFactory() as db, db.begin():
        await db.execute(
            update(DriverNotification)
            .where(
                DriverNotification.id == item_id,
                DriverNotification.lease_token == token,
            )
            .values(
                email_status=status,
                lease_until=None,
                lease_token=None,
                next_attempt_at=datetime.now(UTC)
                + timedelta(seconds=min(60, 2 ** min(attempts, 6))),
            )
        )
    return True


async def scan_tick() -> None:
    async with SessionFactory() as db, db.begin():
        now = datetime.now(UTC)
        await db.execute(
            delete(DriverNotification).where(
                DriverNotification.created_at
                < now - timedelta(days=settings.driver_notification_retention_days)
            )
        )
        await scan_idle(db, now)


async def notification_loop() -> None:
    if not settings.driver_notifications_enabled:
        return

    async def scan_loop() -> None:
        while True:
            try:
                await scan_tick()
            except (SQLAlchemyError, ValueError):
                logger.warning("driver_notification_scan_retry")
            await asyncio.sleep(1)

    async def email_loop() -> None:
        while True:
            try:
                for _ in range(10):
                    if not await deliver_one():
                        break
            except (SQLAlchemyError, ValueError):
                logger.warning("driver_notification_email_retry")
            await asyncio.sleep(1)

    # A slow SMTP server must not delay the next idle-fee event.
    tasks = [asyncio.create_task(scan_loop()), asyncio.create_task(email_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
