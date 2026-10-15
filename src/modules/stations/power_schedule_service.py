"""Service for station power limit schedules (S-45 / G2)."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.stations.models import (
    Station,
    StationPowerSchedule,
    StationPowerScheduleBand,
)
from src.modules.stations.power_bands import (
    PowerBandInput,
    kiem_khung_gio_cong_suat,
)
from src.modules.stations.timezones import DEFAULT_STATION_TIMEZONE


def ngay_dia_phuong(station_timezone: str, dt: datetime) -> date:
    """Return local calendar date in the station's IANA timezone."""
    tz = ZoneInfo(station_timezone or DEFAULT_STATION_TIMEZONE)
    return dt.astimezone(tz).date()


def phut_trong_ngay(station_timezone: str, dt: datetime) -> int:
    """Return local minute of the day [0, 1440) in the station's timezone."""
    tz = ZoneInfo(station_timezone or DEFAULT_STATION_TIMEZONE)
    local_dt = dt.astimezone(tz)
    return local_dt.hour * 60 + local_dt.minute


async def get_effective_power_schedule(
    db: AsyncSession,
    station_id: UUID,
    target_date: date,
) -> StationPowerSchedule | None:
    """Find the effective power schedule for a station on a given local date.

    Picks the schedule where effective_from <= target_date with the latest effective_from.
    """
    stmt = (
        select(StationPowerSchedule)
        .options(selectinload(StationPowerSchedule.bands))
        .where(
            StationPowerSchedule.station_id == station_id,
            StationPowerSchedule.effective_from <= target_date,
        )
        .order_by(StationPowerSchedule.effective_from.desc())
        .limit(1)
    )
    result = await db.scalar(stmt)
    return result


async def get_current_power_limit_w(
    db: AsyncSession,
    station_id: UUID,
    at_time: datetime | None = None,
) -> int | None:
    """Determine the active power limit in Watts for a station at a given instant.

    Uses the station's IANA timezone (AC-5), finds the effective schedule,
    and looks up the band matching the local minute of day.
    Returns None if no power schedule is configured.
    """
    station = await db.get(Station, station_id)
    if station is None:
        return None

    instant = at_time or datetime.now(UTC)
    local_date = ngay_dia_phuong(station.timezone, instant)
    local_min = phut_trong_ngay(station.timezone, instant)

    schedule = await get_effective_power_schedule(db, station_id, local_date)
    if schedule is None:
        return None

    for band in schedule.bands:
        if band.start_min <= local_min < band.end_min:
            return band.power_limit_w

    return None


async def save_station_power_schedule(
    db: AsyncSession,
    station_id: UUID,
    effective_from: date,
    raw_bands: Sequence[PowerBandInput],
) -> StationPowerSchedule:
    """Validate and persist a station power schedule and its bands.

    Normalizes overnight bands, ensures exact 24h coverage, and replaces
    existing bands atomically if a schedule for the same date exists.
    """
    normalized_bands = kiem_khung_gio_cong_suat(raw_bands)

    # Check if a schedule already exists for this station and effective_from
    stmt = (
        select(StationPowerSchedule)
        .where(
            StationPowerSchedule.station_id == station_id,
            StationPowerSchedule.effective_from == effective_from,
        )
        .with_for_update()
    )
    schedule = await db.scalar(stmt)

    if schedule is None:
        schedule = StationPowerSchedule(
            station_id=station_id,
            effective_from=effective_from,
        )
        db.add(schedule)
        await db.flush()
    else:
        # Delete existing bands for replacement
        await db.execute(
            delete(StationPowerScheduleBand).where(
                StationPowerScheduleBand.schedule_id == schedule.id
            )
        )
        schedule.updated_at = datetime.now(UTC)

    # Insert normalized bands
    for band_input in normalized_bands:
        db.add(
            StationPowerScheduleBand(
                schedule_id=schedule.id,
                start_min=band_input.start_min,
                end_min=band_input.end_min,
                power_limit_w=band_input.power_limit_w,
            )
        )

    await db.flush()
    # Refresh with bands loaded
    reloaded = await db.scalar(
        select(StationPowerSchedule)
        .options(selectinload(StationPowerSchedule.bands))
        .where(StationPowerSchedule.id == schedule.id)
    )
    return reloaded or schedule
