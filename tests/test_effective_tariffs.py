import asyncio
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.modules.pricing.models import Tariff
from src.modules.pricing.service import (
    TariffDuplicateDateError,
    TariffEffectiveDateError,
    TariffImmutableError,
    TariffNotFoundError,
    danh_dau_bieu_gia_da_dung,
    kiem_bieu_gia_co_the_sua,
    kiem_ngay_hieu_luc,
    lay_bieu_gia_hieu_luc,
    ngay_dia_phuong,
)
from tests.test_tariff_schema import make_station

NOW = datetime(2026, 10, 7, 17, 30, tzinfo=UTC)  # Oct 8 in Vietnam, Oct 7 in UTC.
TODAY = date(2026, 10, 8)


async def add_tariff(session, station, day):
    tariff = Tariff(
        station_id=station.id,
        effective_from=day,
        idle_rate_vnd_per_minute=1000,
        grace_minutes=5,
    )
    session.add(tariff)
    await session.flush()
    return tariff


@pytest.mark.parametrize("offset", [-1, 0, 1, 2, 3])
async def test_lookup_date_boundaries(db_session, offset):
    station = await make_station(db_session)
    first = await add_tariff(db_session, station, TODAY)
    second = await add_tariff(db_session, station, TODAY + timedelta(days=2))
    result = await lay_bieu_gia_hieu_luc(
        db_session, station_id=station.id, ngay=TODAY + timedelta(days=offset)
    )
    assert result is (None if offset < 0 else first if offset < 2 else second)


async def test_lookup_aware_timestamp_uses_station_day_and_is_scoped(db_session):
    station = await make_station(db_session)
    other = await make_station(db_session)
    selected = await add_tariff(db_session, station, TODAY)
    await add_tariff(db_session, other, TODAY)
    assert (
        await lay_bieu_gia_hieu_luc(db_session, station_id=station.id, ngay=NOW)
        is selected
    )
    assert (
        await lay_bieu_gia_hieu_luc(
            db_session, station_id=station.id, ngay=NOW - timedelta(hours=2)
        )
        is None
    )


@pytest.mark.parametrize(
    "zone, expected",
    [
        ("Asia/Ho_Chi_Minh", TODAY),
        ("America/Los_Angeles", date(2026, 10, 7)),
        ("Pacific/Kiritimati", TODAY),
    ],
)
async def test_first_version_uses_local_today(db_session, zone, expected):
    station = await make_station(db_session)
    station.timezone = zone
    await db_session.flush()
    await kiem_ngay_hieu_luc(
        db_session, station_id=station.id, effective_from=expected, now=NOW
    )
    for invalid in [expected - timedelta(days=1), expected + timedelta(days=1)]:
        with pytest.raises(TariffEffectiveDateError):
            await kiem_ngay_hieu_luc(
                db_session, station_id=station.id, effective_from=invalid, now=NOW
            )


async def test_later_versions_start_tomorrow_and_pending_duplicate_rejected(db_session):
    station = await make_station(db_session)
    await add_tariff(db_session, station, TODAY)
    for day in [TODAY - timedelta(days=1), TODAY]:
        with pytest.raises(TariffEffectiveDateError):
            await kiem_ngay_hieu_luc(
                db_session, station_id=station.id, effective_from=day, now=NOW
            )
    tomorrow = TODAY + timedelta(days=1)
    await kiem_ngay_hieu_luc(
        db_session, station_id=station.id, effective_from=tomorrow, now=NOW
    )
    await add_tariff(db_session, station, tomorrow)
    with pytest.raises(TariffDuplicateDateError):
        await kiem_ngay_hieu_luc(
            db_session, station_id=station.id, effective_from=tomorrow, now=NOW
        )


@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_edit_guard_effective_and_pending(db_session, offset):
    station = await make_station(db_session)
    tariff = await add_tariff(db_session, station, TODAY + timedelta(days=offset))
    if offset <= 0:
        with pytest.raises(TariffImmutableError):
            await kiem_bieu_gia_co_the_sua(
                db_session, station_id=station.id, tariff_id=tariff.id, now=NOW
            )
    else:
        assert (
            await kiem_bieu_gia_co_the_sua(
                db_session, station_id=station.id, tariff_id=tariff.id, now=NOW
            )
            is tariff
        )


async def test_used_marker_is_idempotent_and_freezes_future_version(db_session):
    station = await make_station(db_session)
    tariff = await add_tariff(db_session, station, TODAY + timedelta(days=2))
    for now in [NOW, NOW + timedelta(seconds=10)]:
        await danh_dau_bieu_gia_da_dung(
            db_session, station_id=station.id, tariff_id=tariff.id, now=now
        )
        assert tariff.used_at == NOW
    with pytest.raises(TariffImmutableError):
        await kiem_bieu_gia_co_the_sua(
            db_session, station_id=station.id, tariff_id=tariff.id, now=NOW
        )


async def test_edit_effective_date_uses_same_validator_without_bypass(db_session):
    station = await make_station(db_session)
    first = await add_tariff(db_session, station, TODAY)
    future = await add_tariff(db_session, station, TODAY + timedelta(days=1))
    with pytest.raises(TariffImmutableError):
        await kiem_ngay_hieu_luc(
            db_session,
            station_id=station.id,
            effective_from=TODAY + timedelta(days=3),
            exclude_tariff_id=first.id,
            now=NOW,
        )
    await kiem_ngay_hieu_luc(
        db_session,
        station_id=station.id,
        effective_from=future.effective_from,
        exclude_tariff_id=future.id,
        now=NOW,
    )
    other = await add_tariff(db_session, station, TODAY + timedelta(days=2))
    with pytest.raises(TariffDuplicateDateError):
        await kiem_ngay_hieu_luc(
            db_session,
            station_id=station.id,
            effective_from=other.effective_from,
            exclude_tariff_id=future.id,
            now=NOW,
        )


async def test_unknown_station_and_wrong_station_tariff(db_session):
    station = await make_station(db_session)
    other = await make_station(db_session)
    tariff = await add_tariff(db_session, station, TODAY)
    with pytest.raises(TariffNotFoundError):
        await lay_bieu_gia_hieu_luc(db_session, station_id=uuid4(), ngay=TODAY)
    for helper in [kiem_bieu_gia_co_the_sua, danh_dau_bieu_gia_da_dung]:
        with pytest.raises(TariffNotFoundError):
            await helper(db_session, station_id=other.id, tariff_id=tariff.id, now=NOW)


def test_dst_conversion_and_naive_timestamp_rejection():
    assert ngay_dia_phuong(
        "America/New_York", datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    ) == date(2026, 11, 1)
    assert ngay_dia_phuong(
        "America/New_York", datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    ) == date(2026, 11, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        ngay_dia_phuong("UTC", NOW.replace(tzinfo=None))


async def test_naive_and_datetime_effective_date_rejected(db_session):
    station = await make_station(db_session)
    with pytest.raises(TypeError):
        await kiem_ngay_hieu_luc(
            db_session, station_id=station.id, effective_from=NOW, now=NOW
        )
    with pytest.raises(ValueError):
        await lay_bieu_gia_hieu_luc(
            db_session, station_id=station.id, ngay=NOW.replace(tzinfo=None)
        )


@pytest_asyncio.fixture
async def committed_tariff_db():
    url = make_url(os.environ["DATABASE_URL"])
    name = "t68_" + uuid4().hex
    admin_url = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    test_url = url.set(database=name).render_as_string(hide_password=False)
    engine = create_async_engine(test_url)
    try:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=os.environ | {"DATABASE_URL": test_url},
            check=True,
            capture_output=True,
        )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


async def test_usage_migration_round_trip_preserves_tariff(committed_tariff_db):
    factory = committed_tariff_db
    async with factory() as session:
        station = await make_station(session)
        tariff = await add_tariff(session, station, TODAY)
        await danh_dau_bieu_gia_da_dung(
            session, station_id=station.id, tariff_id=tariff.id, now=NOW
        )
        await session.commit()
    test_url = factory.kw["bind"].url.render_as_string(hide_password=False)
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "downgrade", "b090010a2026"],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    async with factory() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT effective_from, idle_rate_vnd_per_minute, grace_minutes FROM tariffs WHERE id = :id"
                ),
                {"id": tariff.id},
            )
        ).one()
        assert tuple(stored) == (TODAY, 1000, 5)
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    async with factory() as session:
        restored = await session.get(Tariff, tariff.id)
        assert restored.effective_from == TODAY and restored.used_at is None


async def test_pending_edit_waits_for_usage_and_rejects_after_commit(
    committed_tariff_db,
):
    factory = committed_tariff_db
    async with factory() as setup:
        station = await make_station(setup)
        tariff = await add_tariff(setup, station, TODAY + timedelta(days=1))
        await setup.commit()
    async with factory() as writer, factory() as editor, factory() as observer:
        await editor.get(Tariff, tariff.id)
        await danh_dau_bieu_gia_da_dung(
            writer, station_id=station.id, tariff_id=tariff.id, now=NOW
        )
        pid = await editor.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(
            kiem_bieu_gia_co_the_sua(
                editor, station_id=station.id, tariff_id=tariff.id, now=NOW
            )
        )
        try:
            async with asyncio.timeout(10):
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                ):
                    await asyncio.sleep(0.01)
            await writer.commit()
            with pytest.raises(TariffImmutableError):
                await asyncio.wait_for(task, 10)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_first_version_creation_race_sees_committed_winner(committed_tariff_db):
    factory = committed_tariff_db
    async with factory() as setup:
        station = await make_station(setup)
        await setup.commit()
    async with factory() as winner, factory() as loser, factory() as observer:
        await kiem_ngay_hieu_luc(
            winner, station_id=station.id, effective_from=TODAY, now=NOW
        )
        await add_tariff(winner, station, TODAY)
        pid = await loser.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(
            kiem_ngay_hieu_luc(
                loser, station_id=station.id, effective_from=TODAY, now=NOW
            )
        )
        try:
            async with asyncio.timeout(10):
                while not await observer.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                ):
                    await asyncio.sleep(0.01)
            await winner.commit()
            with pytest.raises(TariffEffectiveDateError):
                await asyncio.wait_for(task, 10)
            assert await loser.scalar(select(func.count()).select_from(Tariff)) == 1
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_usage_transaction_rollback_and_reload(committed_tariff_db):
    factory = committed_tariff_db
    async with factory() as setup:
        station = await make_station(setup)
        tariff = await add_tariff(setup, station, TODAY + timedelta(days=1))
        await setup.commit()
    async with factory() as writer, factory() as reader:
        await danh_dau_bieu_gia_da_dung(
            writer, station_id=station.id, tariff_id=tariff.id, now=NOW
        )
        assert (await reader.get(Tariff, tariff.id)).used_at is None
        await writer.rollback()
        assert (await writer.get(Tariff, tariff.id)).used_at is None
        await danh_dau_bieu_gia_da_dung(
            writer, station_id=station.id, tariff_id=tariff.id, now=NOW
        )
        await writer.commit()
        with pytest.raises(TariffImmutableError):
            await kiem_bieu_gia_co_the_sua(
                reader, station_id=station.id, tariff_id=tariff.id, now=NOW
            )
