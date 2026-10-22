"""T-80: persist one immutable invoice in the caller's transaction."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.billing.idle_fee import tinh_phi_chiem_tru
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan
from src.modules.charging.models import ChargingSession, MeterSample, OccupationInterval
from src.modules.pricing.bands import BandInput, TariffBandsError, kiem_khung_gio
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.service import (
    danh_dau_bieu_gia_da_dung,
    lay_bieu_gia_hieu_luc,
)
from src.modules.stations.models import ChargePoint, Connector, Station

LEGACY_ROUNDING_RULE = (
    "Tiền điện: làm tròn nửa lên đến đồng nguyên ở từng đoạn rồi cộng tổng. "
    "Phí chiếm trụ: khoảng cuối đã ghi nhận đến StopTransaction; trừ ân hạn một lần "
    "theo biểu giá lúc bắt đầu chiếm trụ, làm tròn lên theo phút một lần; "
    "mỗi phút bắt đầu dùng biểu giá hiệu lực theo ngày địa phương của trạm."
)
ROUNDING_RULE = (
    "Tiền điện: làm tròn nửa lên đến đồng nguyên ở từng đoạn rồi cộng tổng. "
    "Phí chiếm trụ: khoảng đã xác nhận kết thúc sạc đến lúc rút súng; "
    "trừ ân hạn một lần theo biểu giá lúc bắt đầu khoảng liên tục, "
    "làm tròn lên theo phút một lần; mỗi phút bắt đầu dùng biểu giá "
    "hiệu lực theo ngày địa phương của trạm. Khoảng tạm dừng rồi sạc lại không thu phí."
)
MAX_VND = 2**63 - 1
MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class InvoiceResult:
    status: Literal["ready", "pending", "needs_review"]
    invoice: Invoice | None = None
    reason: str | None = None


class InvoiceSessionNotFoundError(LookupError):
    pass


class _InvalidInvoice(ValueError):
    """Safe reason code; no raw station payload or identity data."""


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _valid_reading(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value >= 0


async def _meter_values(
    db: AsyncSession, charging: ChargingSession, end: datetime
) -> list[MeterValue]:
    start_wh, stop_wh = charging.meter_start_wh, charging.meter_stop_wh
    if not _valid_reading(start_wh) or not _valid_reading(stop_wh):
        raise _InvalidInvoice("invoice_invalid_meter")
    assert stop_wh is not None
    readings = {charging.started_at: start_wh, end: stop_wh}
    samples = await db.scalars(
        select(MeterSample)
        .where(
            MeterSample.session_id == charging.id,
            MeterSample.timestamp >= charging.started_at,
            MeterSample.timestamp <= end,
            MeterSample.measurand == "Energy.Active.Import.Register",
            MeterSample.phase == "",
            MeterSample.location == "Outlet",
        )
        .order_by(MeterSample.timestamp, MeterSample.id)
    )
    for sample in samples:
        if sample.unit != "Wh" or not _valid_reading(sample.value):
            raise _InvalidInvoice("invoice_invalid_meter")
        if sample.timestamp in readings and readings[sample.timestamp] != sample.value:
            raise _InvalidInvoice("invoice_conflicting_meter")
        readings[sample.timestamp] = sample.value
    ordered = sorted(readings.items())
    if any(right[1] < left[1] for left, right in pairwise(ordered)):
        raise _InvalidInvoice("invoice_meter_decreased")
    return [MeterValue(stamp, value) for stamp, value in ordered]


async def _daily_tariffs(
    db: AsyncSession,
    station: Station,
    start: datetime,
    end: datetime,
    *,
    mark_used: bool = True,
) -> tuple[dict[date, Tariff], dict[date, list[TariffFrame]]]:
    tz = ZoneInfo(station.timezone)
    day = start.astimezone(tz).date()
    last = (end - timedelta(microseconds=1)).astimezone(tz).date()
    versions: dict[date, Tariff] = {}
    frames: dict[date, list[TariffFrame]] = {}
    cached: dict[UUID, list[TariffFrame]] = {}
    while day <= last:
        selected = await lay_bieu_gia_hieu_luc(db, station_id=station.id, ngay=day)
        if selected is None:
            raise _InvalidInvoice("invoice_missing_tariff")
        if selected.id not in cached:
            if mark_used:
                selected = await danh_dau_bieu_gia_da_dung(
                    db, station_id=station.id, tariff_id=selected.id
                )
            bands = list(
                await db.scalars(
                    select(TariffBand)
                    .where(TariffBand.tariff_id == selected.id)
                    .order_by(TariffBand.start_min)
                )
            )
            try:
                normalized = kiem_khung_gio(
                    [
                        BandInput(
                            b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label
                        )
                        for b in bands
                    ]
                )
            except TariffBandsError as exc:
                raise _InvalidInvoice("invoice_invalid_tariff") from exc
            cached[selected.id] = [
                TariffFrame(
                    _clock(b.start_min),
                    _clock(b.end_min),
                    b.energy_rate_vnd_per_kwh,
                    str(selected.id),
                    b.label.strip() or f"{_clock(b.start_min)}–{_clock(b.end_min)}",
                )
                for b in normalized
            ]
        versions[day], frames[day] = selected, cached[selected.id]
        day += timedelta(days=1)
    return versions, frames


def _idle_lines(
    charging: ChargingSession,
    station: Station,
    end: datetime,
    versions: dict[date, Tariff],
    invoice_id: UUID,
    *,
    idle_start: datetime | None = None,
) -> list[InvoiceLine]:
    idle = idle_start if idle_start is not None else charging.idle_since
    if idle is None:
        return []
    if idle < charging.started_at or idle > end:
        raise _InvalidInvoice("invoice_invalid_idle_interval")
    if idle == end:
        return []
    tz = ZoneInfo(station.timezone)
    initial = versions[idle.astimezone(tz).date()]
    count, _ = tinh_phi_chiem_tru(idle, end, initial.grace_minutes, 1)
    if not count:
        return []
    anchor = idle.astimezone(UTC) + timedelta(minutes=initial.grace_minutes)
    lines: list[InvoiceLine] = []
    while count:
        day = anchor.astimezone(tz).date()
        tariff = versions[day]
        midnight = datetime.combine(day + timedelta(days=1), time(), tz).astimezone(UTC)
        until_midnight = (midnight - anchor) // timedelta(microseconds=1)
        # Count started-minute anchors before midnight; no extra ceil at the day cut.
        span = min(count, (until_midnight + 59_999_999) // 60_000_000)
        line_end = min(end, anchor + span * MINUTE)
        _, amount = tinh_phi_chiem_tru(
            anchor, line_end, 0, tariff.idle_rate_vnd_per_minute
        )
        lines.append(
            InvoiceLine(
                invoice_id=invoice_id,
                line_type="idle",
                local_date=day,
                started_at=anchor,
                ended_at=line_end,
                energy_wh=Decimal(0),
                rate_vnd=tariff.idle_rate_vnd_per_minute,
                band_label="Phí chiếm trụ",
                interpolated=False,
                tariff_id=tariff.id,
                amount_vnd=amount,
            )
        )
        anchor += span * MINUTE
        count -= span
    return lines


async def _create_invoice(
    db: AsyncSession, charging: ChargingSession, end: datetime
) -> Invoice:
    row = (
        await db.execute(
            select(ChargePoint.station_id, Connector.charge_point_id)
            .join(Connector, Connector.id == charging.connector_id)
            .where(ChargePoint.id == charging.charge_point_id)
        )
    ).one_or_none()
    if row is None or row[1] != charging.charge_point_id:
        raise _InvalidInvoice("invoice_session_mismatch")
    if charging.driver_id is None:
        raise _InvalidInvoice("invoice_missing_driver")
    if charging.authorization_status != "Accepted":
        raise _InvalidInvoice("invoice_unauthorized_session")
    station = await db.scalar(
        select(Station)
        .where(Station.id == row[0])
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert station is not None
    if end <= charging.started_at:
        raise _InvalidInvoice("invoice_invalid_interval")
    readings = await _meter_values(db, charging, end)
    billing_end = end
    intervals: list[OccupationInterval] = []
    if charging.billing_lifecycle_version == 1:
        assert charging.connector_released_at is not None
        intervals = list(
            await db.scalars(
                select(OccupationInterval)
                .where(
                    OccupationInterval.session_id == charging.id,
                    OccupationInterval.confirmed.is_(True),
                )
                .order_by(OccupationInterval.started_at)
            )
        )
        if len(intervals) > 1 or any(
            i.ended_at != charging.connector_released_at or i.end_reason != "released"
            for i in intervals
        ):
            raise _InvalidInvoice("invoice_invalid_occupation_history")
        if intervals:
            billing_end = max(end, charging.connector_released_at)
    versions, frames = await _daily_tariffs(
        db, station, charging.started_at, billing_end
    )
    # Numeric(24,6) readings may use all 24 digits; avoid caller Decimal contexts.
    with localcontext() as ctx:
        ctx.prec = 50
        segments = chia_doan(
            charging.started_at, end, readings, frames, station.timezone
        )
        if sum((s["energy_consumed_wh"] for s in segments), Decimal(0)) != (
            readings[-1].energy_wh - readings[0].energy_wh
        ):
            raise _InvalidInvoice("invoice_energy_mismatch")
    invoice = Invoice(
        id=uuid4(),
        session_id=charging.id,
        driver_id=charging.driver_id,
        station_id=station.id,
        total_vnd=0,
        rounding_rule=ROUNDING_RULE
        if charging.billing_lifecycle_version == 1
        else LEGACY_ROUNDING_RULE,
    )
    lines = [
        InvoiceLine(
            invoice_id=invoice.id,
            line_type="energy",
            local_date=s["local_date"],
            started_at=s["start_time"],
            ended_at=s["end_time"],
            energy_wh=s["energy_consumed_wh"],
            rate_vnd=s["price_vnd_per_kwh"],
            band_label=s["frame_label"],
            interpolated=s["start_interpolated"] or s["end_interpolated"],
            tariff_id=UUID(s["tariff_version"]),
            amount_vnd=s["amount_vnd"],
        )
        for s in segments
    ]
    if charging.billing_lifecycle_version == 0:
        lines += _idle_lines(charging, station, end, versions, invoice.id)
    else:
        for interval in intervals:
            assert interval.ended_at is not None
            lines += _idle_lines(
                charging,
                station,
                interval.ended_at,
                versions,
                invoice.id,
                idle_start=interval.started_at,
            )
    total = sum(line.amount_vnd for line in lines)
    if total > MAX_VND or any(line.amount_vnd > MAX_VND for line in lines):
        raise _InvalidInvoice("invoice_amount_overflow")
    invoice.total_vnd = total
    db.add(invoice)
    await db.flush()
    db.add_all(lines)
    await db.flush()
    return invoice


async def lap_hoa_don(db: AsyncSession, session_id: int) -> InvoiceResult:
    """Lock the session, reuse a saved snapshot, or create it without committing.

    Business rejections persist safe review reasons when the caller commits.
    A savepoint rolls back partial invoice/usage writes without losing the reason.
    Technical DB failures propagate: the caller must rollback/retry its transaction.
    No wallet debit or settlement flag is performed here (T-102).
    """
    charging = await db.scalar(
        select(ChargingSession)
        .where(ChargingSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if charging is None:
        raise InvoiceSessionNotFoundError("Charging session does not exist")
    if charging.review_reasons:
        return InvoiceResult("needs_review", reason="invoice_session_needs_review")
    if charging.ended_at is None:
        return InvoiceResult("pending", reason="invoice_session_in_progress")
    existing = await db.scalar(select(Invoice).where(Invoice.session_id == session_id))
    if existing is not None:
        from src.modules.driver_notifications.service import notify_event

        await notify_event(db, charging, "invoice", invoice=existing)
        return InvoiceResult("ready", existing)
    if (
        charging.billing_lifecycle_version == 1
        and charging.connector_released_at is None
    ):
        return InvoiceResult("pending", reason="invoice_awaiting_unplug")
    end = charging.ended_at
    try:
        async with db.begin_nested():
            invoice = await _create_invoice(db, charging, end)
    except _InvalidInvoice as exc:
        reason = str(exc)
        charging.review_reasons = [*charging.review_reasons, reason]
        await db.flush()
        return InvoiceResult("needs_review", reason=reason)
    from src.modules.driver_notifications.service import notify_event

    await notify_event(db, charging, "invoice", invoice=invoice)
    return InvoiceResult("ready", invoice)
