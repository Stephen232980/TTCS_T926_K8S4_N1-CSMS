"""Shared tariff creation for T-61/T-66; caller owns commit/rollback."""

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.pricing.bands import BandInput, kiem_khung_gio
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.schemas import TariffBandResponse, TariffResponse
from src.modules.pricing.service import TariffNotFoundError, kiem_ngay_hieu_luc
from src.modules.stations.repository import StationRepository


async def tao_bieu_gia(
    session: AsyncSession,
    *,
    scope: ActorScope,
    station_id: UUID,
    effective_from: date,
    idle_rate_vnd_per_minute: int,
    grace_minutes: int,
    bands: list[BandInput],
) -> TariffResponse:
    # Use the established ownership filter and lock before checking local dates.
    station = await StationRepository(session).get_station_by_id(
        station_id, scope, for_update=True
    )
    if station is None:
        raise TariffNotFoundError("Station does not exist")
    normalized = kiem_khung_gio(bands)
    await kiem_ngay_hieu_luc(
        session, station_id=station_id, effective_from=effective_from
    )
    tariff = Tariff(
        station_id=station_id,
        effective_from=effective_from,
        idle_rate_vnd_per_minute=idle_rate_vnd_per_minute,
        grace_minutes=grace_minutes,
    )
    session.add(tariff)
    await session.flush()
    rows = [
        TariffBand(
            tariff_id=tariff.id,
            start_min=band.start_min,
            end_min=band.end_min,
            energy_rate_vnd_per_kwh=band.energy_rate_vnd_per_kwh,
            label=band.label,
        )
        for band in normalized
    ]
    session.add_all(rows)
    await session.flush()
    return TariffResponse(
        id=tariff.id,
        station_id=tariff.station_id,
        effective_from=tariff.effective_from,
        idle_rate_vnd_per_minute=tariff.idle_rate_vnd_per_minute,
        grace_minutes=tariff.grace_minutes,
        created_at=tariff.created_at,
        bands=[TariffBandResponse.model_validate(row) for row in rows],
    )
