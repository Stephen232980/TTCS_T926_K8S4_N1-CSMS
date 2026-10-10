from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.config import get_settings
from src.modules.identity.models import User
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.pricing.service import TariffNotFoundError
from src.modules.wallet.eligibility import du_so_du_de_sac
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_tariff_schema import make_station

NOW = datetime(2026, 10, 7, 17, 30, tzinfo=UTC)


async def setup_case(session, balance, rates=(2500,), *, day=date(2026, 10, 8)):
    station = await make_station(session)
    station.timezone = "Asia/Ho_Chi_Minh"
    driver = User(email=f"eligibility-{uuid4()}@example.com", password_hash="unused")
    session.add(driver)
    await session.flush()
    wallet = Wallet(driver_id=driver.id, balance_vnd=balance, status="active")
    session.add(wallet)
    tariff = None
    if rates is not None:
        tariff = await add_tariff(session, station.id, day, rates)
    await session.flush()
    return station, driver, wallet, tariff


async def add_tariff(session, station_id, day, rates):
    tariff = Tariff(
        station_id=station_id,
        effective_from=day,
        idle_rate_vnd_per_minute=0,
        grace_minutes=0,
    )
    session.add(tariff)
    await session.flush()
    for index, rate in enumerate(rates):
        session.add(
            TariffBand(
                tariff_id=tariff.id,
                start_min=index * 1440 // len(rates),
                end_min=(index + 1) * 1440 // len(rates),
                energy_rate_vnd_per_kwh=rate,
                label=f"Band {index}",
            )
        )
    await session.flush()
    return tariff


@pytest.mark.parametrize(
    "balance,allowed", [(12499, False), (12500, True), (12501, True), (-1, False)]
)
async def test_balance_boundaries(db_session, balance, allowed):
    station, driver, wallet, tariff = await setup_case(db_session, balance)
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert result.allowed is allowed
    assert result.reason == (None if allowed else "wallet_low")
    assert result.minimum_balance_vnd == 12500
    assert result.balance_vnd == balance
    assert result.tariff_id == tariff.id
    assert wallet.balance_vnd == balance
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
        )
        == 0
    )


async def test_highest_effective_rate_and_station_scope(db_session):
    station, driver, _, tariff = await setup_case(db_session, 25000, (2000, 5000, 3000))
    await add_tariff(db_session, station.id, date(2026, 10, 9), (9000,))
    await add_tariff(db_session, station.id, date(2026, 10, 7), (8000,))
    other = await make_station(db_session)
    await add_tariff(db_session, other.id, date(2026, 10, 8), (20000,))
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert result.allowed
    assert result.minimum_balance_vnd == 25000
    assert result.tariff_id == tariff.id


@pytest.mark.parametrize(
    "balance,allowed", [(9999, False), (10000, True), (10001, True), (-1, False)]
)
async def test_no_tariff_uses_reserve(db_session, balance, allowed):
    station, driver, _, _ = await setup_case(db_session, balance, None)
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert result.allowed is allowed
    assert result.minimum_balance_vnd == 10000
    assert result.tariff_id is None


async def test_local_day_boundary_and_future_only_tariff(db_session):
    station, driver, _, tariff = await setup_case(db_session, 12500)
    before = await du_so_du_de_sac(
        db_session,
        driver_id=driver.id,
        station_id=station.id,
        now=datetime(2026, 10, 7, 16, 59, tzinfo=UTC),
    )
    after = await du_so_du_de_sac(
        db_session,
        driver_id=driver.id,
        station_id=station.id,
        now=datetime(2026, 10, 7, 17, 0, tzinfo=UTC),
    )
    assert before.tariff_id is None
    assert before.minimum_balance_vnd == 10000
    assert after.tariff_id == tariff.id
    assert after.minimum_balance_vnd == 12500


async def test_shared_configuration(db_session, monkeypatch):
    config = get_settings()
    monkeypatch.setattr(config, "charging_minimum_kwh", 3)
    monkeypatch.setattr(config, "wallet_reserve_vnd", 7000)
    station, driver, _, _ = await setup_case(db_session, 6000, (2000,))
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert result.allowed and result.minimum_balance_vnd == 6000
    other = await make_station(db_session)
    fallback = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=other.id, now=NOW
    )
    assert not fallback.allowed and fallback.minimum_balance_vnd == 7000


@pytest.mark.parametrize("balance,allowed", [(0, True), (-1, False)])
async def test_free_tariff_still_rejects_debt(db_session, balance, allowed):
    station, driver, _, _ = await setup_case(db_session, balance, (0,))
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert result.allowed is allowed
    assert result.minimum_balance_vnd == 0


async def test_missing_wallet_does_not_create_one(db_session):
    station = await make_station(db_session)
    result = await du_so_du_de_sac(
        db_session, driver_id=uuid4(), station_id=station.id, now=NOW
    )
    assert not result.allowed and result.reason == "wallet_missing"
    assert result.balance_vnd is None
    assert not db_session.new


async def test_locked_wallet(db_session):
    station, driver, wallet, _ = await setup_case(db_session, 100000)
    wallet.status = "locked"
    await db_session.flush()
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert not result.allowed and result.reason == "wallet_locked"


async def test_empty_effective_tariff_fails_closed(db_session):
    station, driver, _, _ = await setup_case(db_session, 100000, ())
    result = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id, now=NOW
    )
    assert not result.allowed and result.reason == "tariff_unavailable"
    assert result.minimum_balance_vnd is None


async def test_unknown_station(db_session):
    with pytest.raises(TariffNotFoundError):
        await du_so_du_de_sac(
            db_session, driver_id=uuid4(), station_id=uuid4(), now=NOW
        )
