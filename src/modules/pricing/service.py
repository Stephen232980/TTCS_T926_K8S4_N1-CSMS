"""Shared effective-date guards; locks last until the caller ends its transaction."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.pricing.models import Tariff
from src.modules.stations.models import Station


class TariffError(Exception):
    pass


class TariffNotFoundError(TariffError):
    pass


class TariffEffectiveDateError(TariffError, ValueError):
    pass


class TariffDuplicateDateError(TariffError):
    pass


class TariffImmutableError(TariffError):
    pass


def ngay_dia_phuong(timezone: str, at: datetime) -> date:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    return at.astimezone(ZoneInfo(timezone)).date()


def _calendar_date(value: date) -> None:
    if type(value) is not date:
        raise TypeError("Effective date must be a calendar date, not a timestamp")


async def _station(session: AsyncSession, station_id: UUID, *, lock: bool) -> Station:
    query = select(Station).where(Station.id == station_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    station = await session.scalar(query)
    if station is None:
        raise TariffNotFoundError("Station does not exist")
    return station


async def lay_bieu_gia_hieu_luc(
    session: AsyncSession, *, station_id: UUID, ngay: date | datetime
) -> Tariff | None:
    """A date is already local; an aware timestamp is converted to station time."""
    station = await _station(session, station_id, lock=False)
    local_date = (
        ngay_dia_phuong(station.timezone, ngay) if isinstance(ngay, datetime) else ngay
    )
    _calendar_date(local_date)
    tariff: Tariff | None = await session.scalar(
        select(Tariff)
        .where(Tariff.station_id == station_id, Tariff.effective_from <= local_date)
        .order_by(Tariff.effective_from.desc())
        .limit(1)
    )
    return tariff


async def kiem_ngay_hieu_luc(
    session: AsyncSession,
    *,
    station_id: UUID,
    effective_from: date,
    now: datetime | None = None,
    exclude_tariff_id: UUID | None = None,
) -> Station:
    """T-61/T-69 call before INSERT/UPDATE, in the same caller transaction.

    The station lock serializes first-version detection and pending-date checks.
    Updating uses exclude_tariff_id only after checking mutability below.
    """
    _calendar_date(effective_from)
    station = await _station(session, station_id, lock=True)
    today = ngay_dia_phuong(
        station.timezone, now if now is not None else datetime.now(UTC)
    )
    versions = select(Tariff).where(Tariff.station_id == station_id)
    if exclude_tariff_id is not None:
        # Do not permit using the creation validator to bypass an edit guard.
        await kiem_bieu_gia_co_the_sua(
            session, station_id=station_id, tariff_id=exclude_tariff_id, now=now
        )
        versions = versions.where(Tariff.id != exclude_tariff_id)
    existing = await session.scalar(versions.limit(1))
    if existing is None:
        if effective_from != today:
            raise TariffEffectiveDateError(
                "The first tariff must start today in station time"
            )
    elif effective_from < today + timedelta(days=1):
        raise TariffEffectiveDateError(
            "Later tariffs must start tomorrow or later in station time"
        )
    duplicate = await session.scalar(
        versions.where(Tariff.effective_from == effective_from).limit(1)
    )
    if duplicate is not None:
        raise TariffDuplicateDateError(
            "A tariff already exists for this effective date"
        )
    return station


async def kiem_bieu_gia_co_the_sua(
    session: AsyncSession,
    *,
    station_id: UUID,
    tariff_id: UUID,
    now: datetime | None = None,
) -> Tariff:
    """Lock station then tariff before editing rates, bands or effective date."""
    station = await _station(session, station_id, lock=True)
    tariff = await session.scalar(
        select(Tariff)
        .where(Tariff.id == tariff_id, Tariff.station_id == station_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tariff is None:
        raise TariffNotFoundError("Tariff does not belong to this station")
    today = ngay_dia_phuong(
        station.timezone, now if now is not None else datetime.now(UTC)
    )
    if tariff.effective_from <= today or tariff.used_at is not None:
        raise TariffImmutableError("An effective or invoice-used tariff is immutable")
    return tariff


async def danh_dau_bieu_gia_da_dung(
    session: AsyncSession,
    *,
    station_id: UUID,
    tariff_id: UUID,
    now: datetime | None = None,
) -> Tariff:
    """T-79 marks usage before copying locked tariff data into an invoice.

    Commit/rollback this marker with the invoice; never commit in this helper.
    """
    await _station(session, station_id, lock=True)
    tariff = await session.scalar(
        select(Tariff)
        .where(Tariff.id == tariff_id, Tariff.station_id == station_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if tariff is None:
        raise TariffNotFoundError("Tariff does not belong to this station")
    timestamp = now if now is not None else datetime.now(UTC)
    ngay_dia_phuong("UTC", timestamp)
    if tariff.used_at is None:
        tariff.used_at = timestamp.astimezone(UTC)
        await session.flush()
    return tariff
