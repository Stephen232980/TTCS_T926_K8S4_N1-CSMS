"""Outbox leases survive restarts; SMTP never runs inside a DB transaction."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import settings
from src.modules.alerts.models import AlertEmail, OperationalAlert
from src.modules.alerts.service import scan_alerts
from src.modules.ocpp.monitoring import database_time
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import SessionFactory
from src.platform.email import send_email, smtp_enabled

logger = logging.getLogger("csms.alerts")


@dataclass(frozen=True)
class Delivery:
    id: UUID
    lease_token: UUID
    recipient: str
    code: str
    station: str
    kind: str
    opened_at: str
    status: str


def send_smtp(delivery: Delivery) -> None:
    label = (
        "Ngoại tuyến quá ngưỡng"
        if delivery.kind == "offline"
        else "Lỗi đầu nối liên tục"
    )
    send_email(
        recipient=delivery.recipient,
        subject=f"[CSMS] Cảnh báo trụ {delivery.code}",
        message_id=f"<csms-alert-{delivery.id}@csms.invalid>",
        text_body=(
            f"Trạm: {delivery.station}\nTrụ: {delivery.code}\nCảnh báo: {label}\n"
            f"Mở lúc (UTC): {delivery.opened_at}\nTrạng thái: {delivery.status}\n"
            "Đăng nhập khu vực vận hành CSMS để kiểm tra và xác nhận xử lý.\n"
        ),
        config=settings,
    )


async def claim_emails() -> list[Delivery]:
    if not settings.alert_smtp_enabled or not smtp_enabled(settings):
        return []
    async with SessionFactory() as db, db.begin():
        now = await database_time(db)
        rows = (
            await db.execute(
                select(AlertEmail, OperationalAlert, ChargePoint.code, Station.name)
                .join(OperationalAlert, OperationalAlert.id == AlertEmail.alert_id)
                .join(ChargePoint, ChargePoint.id == OperationalAlert.charge_point_id)
                .join(Station, Station.id == ChargePoint.station_id)
                .where(
                    or_(
                        and_(
                            AlertEmail.status.in_(("pending", "retry")),
                            AlertEmail.next_attempt_at <= now,
                        ),
                        and_(
                            AlertEmail.status == "sending",
                            AlertEmail.locked_until <= now,
                        ),
                    )
                )
                .order_by(AlertEmail.next_attempt_at, AlertEmail.id)
                .limit(10)
                .with_for_update(skip_locked=True, of=AlertEmail)
            )
        ).all()
        deliveries = []
        for email, alert, code, station in rows:
            if email.attempts >= settings.alert_email_max_attempts:
                email.status, email.last_error = "failed", "attempts_exhausted"
                continue
            email.attempts += 1
            email.status = "sending"
            email.lease_token = uuid4()
            email.locked_until = now + timedelta(
                seconds=120
                + 2
                * (
                    settings.smtp_timeout_seconds
                    if settings.smtp_enabled is not None
                    else settings.alert_smtp_timeout_seconds
                )
            )
            deliveries.append(
                Delivery(
                    email.id,
                    email.lease_token,
                    email.recipient,
                    code,
                    station,
                    alert.kind,
                    alert.opened_at.isoformat(),
                    alert.status,
                )
            )
    return deliveries


async def deliver_email(delivery: Delivery) -> None:
    failed = False
    try:
        await asyncio.to_thread(send_smtp, delivery)
    except (OSError, smtplib.SMTPException, ValueError):
        failed = True
        logger.warning("alert_email_delivery_failed id=%s", delivery.id)
    async with SessionFactory() as db, db.begin():
        email = await db.scalar(
            select(AlertEmail).where(AlertEmail.id == delivery.id).with_for_update()
        )
        if email is None or email.lease_token != delivery.lease_token:
            return
        now = await database_time(db)
        email.locked_until = None
        email.lease_token = None
        if failed:
            email.status = (
                "failed"
                if email.attempts >= settings.alert_email_max_attempts
                else "retry"
            )
            email.last_error = "smtp_unavailable"
            email.next_attempt_at = now + timedelta(
                seconds=min(900, 30 * 2 ** min(email.attempts - 1, 5))
            )
        else:
            email.status, email.sent_at, email.last_error = "sent", now, None


async def alert_scan_loop() -> None:
    while True:
        try:
            async with SessionFactory() as db, db.begin():
                await scan_alerts(db)
        except SQLAlchemyError:
            logger.error("alert_scan_failed")
        await asyncio.sleep(settings.alert_scan_interval_seconds)


async def alert_email_loop() -> None:
    while True:
        try:
            deliveries = await claim_emails()
            await asyncio.gather(
                *(deliver_email(delivery) for delivery in deliveries),
                return_exceptions=False,
            )
        except SQLAlchemyError:
            logger.error("alert_email_scan_failed")
        await asyncio.sleep(5)
