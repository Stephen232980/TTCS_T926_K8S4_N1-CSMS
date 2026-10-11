"""T-107: safely attach a three-band *first* tariff to a prefixed test station.

This deliberately does not create a station, touch an existing effective tariff,
credit a wallet, or delete financial evidence. The T-55 simulator seed must own
station/driver/card creation; see docs/T107_STAGING_SEED_NOTES.md.
"""

import argparse
import asyncio
import selectors
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.identity.authorization import ActorScope
from src.modules.pricing.bands import BandInput, kiem_khung_gio
from src.modules.pricing.creation import tao_bieu_gia
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.service import ngay_dia_phuong
from src.modules.stations.models import Station


@dataclass(frozen=True)
class Plan:
    first_boundary: int
    second_boundary: int
    rates: tuple[int, int, int]
    prefix: str = "T107-"

    def bands(self) -> list[BandInput]:
        if not (0 < self.first_boundary < self.second_boundary < 1440):
            raise ValueError("Need 0 < first boundary < second boundary < 1440")
        if len(self.rates) != 3 or any(type(x) is not int or x < 0 for x in self.rates):
            raise ValueError("Three nonnegative integer VND/kWh rates are required")
        if self.prefix != "T107-":
            raise ValueError("T-107 only works with dedicated T107- station names")
        return kiem_khung_gio(
            [
                BandInput(0, self.first_boundary, self.rates[0], "T107-01"),
                BandInput(self.first_boundary, self.second_boundary, self.rates[1], "T107-02"),
                BandInput(self.second_boundary, 1440, self.rates[2], "T107-03"),
            ]
        )


async def ensure_first_tariff(
    session: AsyncSession, *, station_id: UUID, plan: Plan
) -> tuple[UUID, bool]:
    """Return (tariff ID, created). Caller controls transaction and commit.

    Fail closed when the target station isn't T107-owned or has a non-matching
    tariff; rerunning an identical seed returns the original ID without change.
    """
    bands = plan.bands()
    station = await session.scalar(
        select(Station).where(Station.id == station_id).with_for_update()
    )
    if station is None or not station.name.startswith(plan.prefix):
        raise ValueError("Station must exist and have a dedicated T107- name")
    if station.archived_at is not None:
        raise ValueError("Cannot seed an archived station")

    today = ngay_dia_phuong(station.timezone, datetime.now(UTC))
    tariffs = (
        await session.scalars(
            select(Tariff).where(Tariff.station_id == station.id).order_by(Tariff.effective_from)
        )
    ).all()
    if tariffs:
        if len(tariffs) != 1:
            raise ValueError("Station already has multiple tariff versions; refusing to alter them")
        existing = tariffs[0]
        rows = (
            await session.scalars(
                select(TariffBand)
                .where(TariffBand.tariff_id == existing.id)
                .order_by(TariffBand.start_min)
            )
        ).all()
        if (
            existing.idle_rate_vnd_per_minute != 0
            or existing.grace_minutes != 0
            or [
                (b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label)
                for b in rows
            ]
            != [
                (b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label)
                for b in bands
            ]
        ):
            raise ValueError("Existing tariff is not today's exact T107 seed; no changes made")
        return existing.id, False

    created = await tao_bieu_gia(
        session,
        scope=ActorScope(actor_id=station.owner_id, owner_id=station.owner_id),
        station_id=station.id,
        effective_from=today,
        idle_rate_vnd_per_minute=0,
        grace_minutes=0,
        bands=bands,
    )
    return created.id, True


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T-107: seed only the initial 3-band tariff")
    parser.add_argument("--station-id", type=UUID, help="Explicit ID of a T107- station")
    parser.add_argument("--boundaries", nargs=2, type=int, required=True, metavar=("FIRST", "SECOND"))
    parser.add_argument("--rates", nargs=3, type=int, required=True, metavar=("R1", "R2", "R3"))
    parser.add_argument("--apply", action="store_true", help="Persist after validation; default is plan only")
    return parser.parse_args()


async def main() -> None:
    args = arguments()
    plan = Plan(args.boundaries[0], args.boundaries[1], tuple(args.rates))
    bands = plan.bands()
    for band in bands:
        print(f"{band.start_min:04d}-{band.end_min:04d}: {band.energy_rate_vnd_per_kwh} VND/kWh")
    if not args.apply:
        print("DRY RUN: no database changes. Use --apply --station-id UUID for T107- station.")
        return
    if args.station_id is None:
        raise SystemExit("--station-id is mandatory with --apply")
    from src.platform.database.session import SessionFactory

    async with SessionFactory() as session, session.begin():
        tariff_id, created = await ensure_first_tariff(session, station_id=args.station_id, plan=plan)
    print(f"{'Created' if created else 'Unchanged'} tariff {tariff_id}")


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
