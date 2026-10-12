"""T-107 adapter for T-108's persisted manifest; never creates stations.

Coordinate simulator/t108_contract.py and simulator/t108_fixture.py with PR #135:
they are shared source files, not separate T-107 schemas.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import selectors
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.t108_contract import RunManifest, save_json
from simulator.t108_fixture import cleanup_manifest, lock_key, seed_manifest
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.stations.models import ChargePoint, Connector, Station


async def verify_prepared_run(session: AsyncSession, manifest: RunManifest) -> None:
    """Fail closed unless T-108 already created the exact run fixture/tariff."""
    station = await session.get(Station, manifest.station_id)
    marker = (
        f"T108 run {manifest.run_id}; config {manifest.configuration_hash}; "
        "virtual test only"
    )
    if (
        station is None
        or station.owner_id != manifest.owner_id
        or station.name != f"T108-{manifest.run_id.hex}"
        or station.address != marker
        or station.timezone != manifest.station_timezone
        or station.status != "active"
        or station.archived_at is not None
    ):
        raise ValueError("T-108 run station not prepared or manifest mismatch")
    tariffs = list(
        await session.scalars(select(Tariff).where(Tariff.station_id == station.id))
    )
    if len(tariffs) != 1 or manifest.tariff_id != tariffs[0].id:
        raise ValueError("T-108 run tariff not prepared or version mismatch")
    tariff = tariffs[0]
    from zoneinfo import ZoneInfo

    if (
        tariff.effective_from
        != manifest.started_at.astimezone(ZoneInfo(manifest.station_timezone)).date()
        or tariff.idle_rate_vnd_per_minute != 0
        or tariff.grace_minutes != 0
    ):
        raise ValueError("T-108 run tariff settings mismatch")
    bands = list(
        await session.scalars(
            select(TariffBand)
            .where(TariffBand.tariff_id == tariff.id)
            .order_by(TariffBand.start_min)
        )
    )
    first, second = manifest.first_boundary_minute, manifest.second_boundary_minute
    expected = [
        (0, first, manifest.rates[0], "T108-01"),
        (first, second, manifest.rates[1], "T108-02"),
        (second, 1440, manifest.rates[2], "T108-03"),
    ]
    actual = [
        (b.start_min, b.end_min, b.energy_rate_vnd_per_kwh, b.label) for b in bands
    ]
    if actual != expected:
        raise ValueError("T-108 run tariff bands mismatch")
    for participant in manifest.participants:
        charger = await session.get(ChargePoint, participant.charge_point_id)
        connector = await session.get(Connector, participant.connector_id)
        if (
            charger is None
            or charger.station_id != station.id
            or charger.code != participant.charge_point_code
            or charger.name != participant.charge_point_code
            or charger.archived_at is not None
            or connector is None
            or connector.charge_point_id != charger.id
            or connector.connector_number != participant.connector_number
            or connector.archived_at is not None
        ):
            raise ValueError("T-108 run charger/connector not prepared or mismatch")


async def apply_run(
    session: AsyncSession, manifest: RunManifest, admin_email: str
) -> int:
    """Serialize, validate T-108 ownership, and fund through shared T-88 adapter."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(manifest)}
    )
    await verify_prepared_run(session, manifest)
    return await seed_manifest(session, manifest, admin_email)


async def cleanup_run(session: AsyncSession, manifest: RunManifest) -> None:
    """Serialize with seed and archive only the specified run."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(manifest)}
    )
    await cleanup_manifest(session, manifest)


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T-107 T-108 manifest integration")
    parser.add_argument("--manifest", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--cleanup", action="store_true")
    parser.add_argument("--admin-email")
    parser.add_argument("--confirm-test-environment", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = arguments()
    manifest = RunManifest.model_validate_json(
        args.manifest.read_text(encoding="utf-8")
    )
    if args.apply and not args.admin_email:
        raise SystemExit("--admin-email is required for --apply")
    if args.cleanup and args.admin_email:
        raise SystemExit("--admin-email is not used for --cleanup")
    if (
        not args.confirm_test_environment
        or os.environ.get("T107_ALLOW_STAGING_SEED") != "YES"
    ):
        raise SystemExit(
            "Writes blocked: confirm isolated test DB and explicit consent"
        )
    from src.platform.database.session import SessionFactory

    async with SessionFactory() as session, session.begin():
        if args.apply:
            count = await apply_run(session, manifest, args.admin_email)
        else:
            await cleanup_run(session, manifest)
            count = None
    # Persist augmented wallet IDs/opening balances only after DB commit.
    if args.apply:
        save_json(args.manifest, manifest.model_dump(mode="json"))
        print(
            f"T107 run {manifest.run_id}: new T88 receipts {count}/{len(manifest.participants)}"
        )
    else:
        print(
            f"T107 run {manifest.run_id}: cleanup complete (financial history retained)"
        )


if __name__ == "__main__":
    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
