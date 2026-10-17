"""Business event snapshots. No commit, SMTP, or inferred invoice readiness."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Literal
from uuid import uuid4

from sqlalchemy import String, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession, OccupationInterval
from src.modules.driver_notifications.models import DriverNotification
from src.modules.identity.models import User
from src.modules.stations.models import ChargePoint, Station

Event = Literal["stop", "idle", "invoice"]


async def estimated_amount(
    db: AsyncSession, charging: ChargingSession, station: Station, at: datetime
) -> int | None:
    # Reuse the billing meter validation, segmentation, rounding and idle rules;
    # only read tariffs here, never create a premature invoice or lock a tariff.
    from src.modules.billing.invoicing import (
        _daily_tariffs,
        _idle_lines,
        _InvalidInvoice,
        _meter_values,
    )
    from src.modules.billing.segmentation import chia_doan

    if charging.ended_at is None or charging.review_reasons:
        return None
    try:
        end = charging.ended_at
        if end <= charging.started_at:
            return None
        readings = await _meter_values(db, charging, end)
        through = max(end, at)
        versions, frames = await _daily_tariffs(
            db, station, charging.started_at, through, mark_used=False
        )
        total: int
        with localcontext() as ctx:
            ctx.prec = 50
            total = sum(
                int(s["amount_vnd"])
                for s in chia_doan(
                    charging.started_at, end, readings, frames, station.timezone
                )
            )
        if charging.billing_lifecycle_version == 0:
            intervals = [(charging.idle_since, end)] if charging.idle_since else []
        else:
            rows = await db.scalars(
                select(OccupationInterval).where(
                    OccupationInterval.session_id == charging.id,
                    OccupationInterval.confirmed.is_(True),
                )
            )
            intervals = [(i.started_at, i.ended_at or at) for i in rows]
        for start, finish in intervals:
            if start >= at:
                continue
            total += sum(
                line.amount_vnd
                for line in _idle_lines(
                    charging,
                    station,
                    min(finish, at),
                    versions,
                    uuid4(),
                    idle_start=start,
                )
            )
        return total
    except (_InvalidInvoice, ValueError):
        return None


async def notify_event(
    db: AsyncSession,
    charging: ChargingSession,
    kind: Event,
    *,
    invoice: Invoice | None = None,
    at: datetime | None = None,
    event_id: str | None = None,
) -> None:
    if charging.driver_id is None:
        return
    # Lock the identity first so S-57 freeze and notification creation serialize.
    user = await db.scalar(
        select(User)
        .where(User.id == charging.driver_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or user.status != "active":
        return
    station = await db.scalar(
        select(Station)
        .join(ChargePoint, ChargePoint.station_id == Station.id)
        .where(ChargePoint.id == charging.charge_point_id)
    )
    if station is None:
        return
    if kind == "invoice":
        if invoice is None:
            raise ValueError("invoice_snapshot_required")
        at = invoice.created_at
    elif kind == "stop":
        if charging.ended_at is None:
            return
        at = charging.ended_at
    assert at is not None
    from src.config import settings

    if at < datetime.now(UTC) - timedelta(
        days=settings.driver_notification_retention_days
    ):
        return
    amount = (
        invoice.total_vnd
        if invoice
        else await estimated_amount(db, charging, station, at)
    )
    energy = charging.energy_kwh
    if (
        energy is None
        and charging.meter_stop_wh is not None
        and charging.meter_stop_wh >= charging.meter_start_wh >= 0
    ):
        energy = (charging.meter_stop_wh - charging.meter_start_wh) / Decimal(1000)
    energy_text = (
        f"{energy} kWh đã ghi nhận" if energy is not None else "kWh: đang đối chiếu"
    )
    money_text = (
        (
            f"Tổng tiền đã chốt: {amount:,} đ"
            if invoice
            else f"Tiền tạm tính (chưa chốt): {amount:,} đ"
        )
        if amount is not None
        else "Tiền tạm tính: đang đối chiếu, chưa chốt"
    )
    titles = {
        "stop": "Đã dừng sạc — Vui lòng kiểm tra súng sạc",
        "idle": "Đã bắt đầu tính phí chiếm trụ",
        "invoice": "Hóa đơn phiên sạc đã sẵn sàng",
    }
    detail = {
        "stop": "Đã ngừng cấp điện. Vui lòng rút súng nếu còn cắm; phí và tiền chưa chốt.",
        "idle": "Thời gian miễn phí đã kết thúc. Vui lòng rút súng để ngừng phí chiếm trụ.",
        "invoice": "Hóa đơn đã được lập từ số liệu đã chốt.",
    }[kind]
    message = (
        f"{station.name} · {at.isoformat()}\n{detail}\n{energy_text} · {money_text}"
    )
    await db.execute(
        insert(DriverNotification)
        .values(
            driver_id=charging.driver_id,
            session_id=charging.id,
            event_type=kind,
            event_id=event_id or str(charging.id),
            title=titles[kind],
            message=message,
            occurred_at=at,
        )
        .on_conflict_do_nothing(constraint="uq_driver_notification_event")
    )


async def scan_idle(db: AsyncSession, now: datetime) -> None:
    from src.config import settings
    from src.modules.billing.invoicing import (
        _daily_tariffs,
        _idle_lines,
        _InvalidInvoice,
    )

    # Keyset pages prevent early-unplug/no-fee intervals starving later sessions.
    cursor = 0
    while True:
        rows = list(
            await db.execute(
                select(ChargingSession, OccupationInterval, Station)
                .join(
                    OccupationInterval,
                    OccupationInterval.session_id == ChargingSession.id,
                )
                .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
                .join(Station, Station.id == ChargePoint.station_id)
                .join(User, User.id == ChargingSession.driver_id)
                .where(
                    OccupationInterval.id > cursor,
                    User.status == "active",
                    OccupationInterval.confirmed.is_(True),
                    OccupationInterval.started_at
                    >= now
                    - timedelta(days=settings.driver_notification_retention_days),
                    OccupationInterval.end_reason.is_distinct_from("resumed"),
                    ChargingSession.billing_lifecycle_version == 1,
                    ~select(DriverNotification.id)
                    .where(
                        DriverNotification.session_id == ChargingSession.id,
                        DriverNotification.event_type == "idle",
                        DriverNotification.event_id
                        == OccupationInterval.id.cast(String),
                    )
                    .exists(),
                )
                .order_by(OccupationInterval.id)
                .limit(100)
            )
        )
        if not rows:
            return
        for charging, interval, station in rows:
            cursor = interval.id
            if charging.review_reasons:
                continue
            end = min(interval.ended_at or now, now)
            if end <= interval.started_at:
                continue
            try:
                versions, _ = await _daily_tariffs(
                    db, station, interval.started_at, end, mark_used=False
                )
                lines = _idle_lines(
                    charging,
                    station,
                    end,
                    versions,
                    uuid4(),
                    idle_start=interval.started_at,
                )
            except (_InvalidInvoice, ValueError):
                continue
            first = next((line for line in lines if line.amount_vnd > 0), None)
            if first is not None:
                await notify_event(
                    db, charging, "idle", at=first.started_at, event_id=str(interval.id)
                )
