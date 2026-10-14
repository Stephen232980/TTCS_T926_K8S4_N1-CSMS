from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.modules.identity.models import User
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.stations.models import Station


async def make_station(session):
    owner = User(email=f"tariff-{uuid4()}@example.com", password_hash="unused")
    session.add(owner)
    await session.flush()
    station = Station(
        owner_id=owner.id,
        name="Tariff fixture",
        address="Test",
        latitude=Decimal("10.7"),
        longitude=Decimal("106.7"),
    )
    session.add(station)
    await session.flush()
    return station


async def make_tariff(session):
    station = await make_station(session)
    tariff = Tariff(
        station_id=station.id,
        effective_from=date(2026, 10, 7),
        idle_rate_vnd_per_minute=1000,
        grace_minutes=5,
    )
    session.add(tariff)
    await session.flush()
    return tariff


@pytest.mark.asyncio
async def test_flat_tariff_roundtrip_and_large_integer_rates(db_session):
    tariff = await make_tariff(db_session)
    band = TariffBand(
        tariff_id=tariff.id,
        start_min=0,
        end_min=1440,
        energy_rate_vnd_per_kwh=3_000_000_001,
        label="Cả ngày",
    )
    db_session.add(band)
    await db_session.flush()
    band_id = band.id
    db_session.expire_all()
    saved = await db_session.scalar(select(TariffBand).where(TariffBand.id == band_id))
    assert saved is not None
    assert saved.energy_rate_vnd_per_kwh == 3_000_000_001
    assert (saved.start_min, saved.end_min) == (0, 1440)
    saved_tariff = await db_session.get(Tariff, saved.tariff_id)
    assert saved_tariff.effective_from == date(2026, 10, 7)
    assert saved_tariff.created_at.utcoffset() is not None


@pytest.mark.asyncio
async def test_versions_are_unique_per_station_local_date(db_session):
    tariff = await make_tariff(db_session)
    other_station = await make_station(db_session)
    for station_id, day in (
        (tariff.station_id, date(2026, 10, 8)),
        (other_station.id, tariff.effective_from),
    ):
        db_session.add(
            Tariff(
                station_id=station_id,
                effective_from=day,
                idle_rate_vnd_per_minute=0,
                grace_minutes=0,
            )
        )
    await db_session.flush()
    with pytest.raises(IntegrityError, match="uq_tariffs_station_effective_from"):
        async with db_session.begin_nested():
            db_session.add(
                Tariff(
                    station_id=tariff.station_id,
                    effective_from=tariff.effective_from,
                    idle_rate_vnd_per_minute=0,
                    grace_minutes=0,
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start,end",
    [(-1, 60), (0, 1441), (60, 60), (120, 60), (1440, 1441), (0, 0), (-2, -1)],
)
async def test_database_rejects_invalid_minutes_without_application_validation(
    db_session, start, end
):
    tariff = await make_tariff(db_session)
    with pytest.raises(IntegrityError, match="ck_tariff_bands_minute_range"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO tariff_bands "
                    "(id, tariff_id, start_min, end_min, energy_rate_vnd_per_kwh, label) "
                    "VALUES (:id, :tariff, :start, :end, 2500, 'Test')"
                ),
                {"id": uuid4(), "tariff": tariff.id, "start": start, "end": end},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column,constraint",
    [
        ("idle_rate_vnd_per_minute", "ck_tariffs_idle_rate_nonnegative"),
        ("grace_minutes", "ck_tariffs_grace_nonnegative"),
    ],
)
async def test_database_rejects_negative_tariff_values(db_session, column, constraint):
    station = await make_station(db_session)
    values = {
        "station_id": station.id,
        "effective_from": date(2026, 10, 7),
        "idle_rate_vnd_per_minute": 0,
        "grace_minutes": 0,
    }
    values[column] = -1
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            db_session.add(Tariff(**values))
            await db_session.flush()


@pytest.mark.asyncio
async def test_database_rejects_negative_energy_rate(db_session):
    tariff = await make_tariff(db_session)
    with pytest.raises(IntegrityError, match="ck_tariff_bands_energy_rate_nonnegative"):
        async with db_session.begin_nested():
            db_session.add(
                TariffBand(
                    tariff_id=tariff.id,
                    start_min=0,
                    end_min=1440,
                    energy_rate_vnd_per_kwh=-1,
                    label="Test",
                )
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_zero_rates_and_adjacent_bands_are_allowed(db_session):
    tariff = await make_tariff(db_session)
    for start, end in [(0, 360), (360, 1320), (1320, 1440)]:
        db_session.add(
            TariffBand(
                tariff_id=tariff.id,
                start_min=start,
                end_min=end,
                energy_rate_vnd_per_kwh=0,
                label="Miễn phí",
            )
        )
    await db_session.flush()
    bands = (
        await db_session.scalars(
            select(TariffBand)
            .where(TariffBand.tariff_id == tariff.id)
            .order_by(TariffBand.start_min)
        )
    ).all()
    assert len(bands) == 3


@pytest.mark.asyncio
async def test_foreign_keys_and_restricted_deletion_preserve_tariffs(db_session):
    tariff = await make_tariff(db_session)
    db_session.add(
        TariffBand(
            tariff_id=tariff.id,
            start_min=0,
            end_min=1440,
            energy_rate_vnd_per_kwh=2500,
            label="Test",
        )
    )
    await db_session.flush()
    for model, record_id in ((Station, tariff.station_id), (Tariff, tariff.id)):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(delete(model).where(model.id == record_id))
    for record in (
        Tariff(
            station_id=uuid4(),
            effective_from=date(2026, 10, 7),
            idle_rate_vnd_per_minute=0,
            grace_minutes=0,
        ),
        TariffBand(
            tariff_id=uuid4(),
            start_min=0,
            end_min=1440,
            energy_rate_vnd_per_kwh=2500,
            label="Test",
        ),
    ):
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(record)
                await db_session.flush()


@pytest.mark.asyncio
async def test_migrated_database_has_lookup_indexes(db_session):
    connection = await db_session.connection()
    tariffs = await connection.run_sync(
        lambda conn: inspect(conn).get_indexes("tariffs")
    )
    bands = await connection.run_sync(
        lambda conn: inspect(conn).get_indexes("tariff_bands")
    )
    assert any(
        index["unique"] and index["column_names"] == ["station_id", "effective_from"]
        for index in tariffs
    )
    assert any(index["column_names"] == ["tariff_id"] for index in bands)
