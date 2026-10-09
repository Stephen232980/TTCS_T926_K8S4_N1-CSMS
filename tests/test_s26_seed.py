from decimal import ROUND_CEILING, Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from simulator.config import load_settings
from simulator.seed import (
    SIMULATOR_PRICE_VND_PER_KWH,
    _minimum_wallet_balance,
    _station,
    _wallet,
)
from src.config import settings as app_settings
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.identity.models import User
from src.modules.stations.models import Station
from src.modules.wallet.manual_topup import ManualTopupRequest
from src.modules.wallet.models import Wallet


@pytest.mark.asyncio
async def test_seed_credits_wallet_to_charging_minimum(monkeypatch) -> None:
    session = AsyncMock(spec=AsyncSession)
    driver = User(id=uuid4(), email="simulator-driver@example.com", password_hash="")
    administrator = User(
        id=uuid4(), email="simulator-admin@example.com", password_hash=""
    )
    settings = load_settings({})
    wallet = Wallet(driver_id=driver.id, balance_vnd=0, status="active")

    async def credit_wallet(_session, **kwargs) -> None:
        wallet.balance_vnd += kwargs["request"].amount_vnd

    topup = AsyncMock(side_effect=credit_wallet)
    monkeypatch.setattr(
        "simulator.seed.ensure_driver_wallet", AsyncMock(return_value=wallet)
    )
    monkeypatch.setattr("simulator.seed.nap_tay", topup)

    seeded_wallet = await _wallet(session, driver, administrator, settings)

    assert seeded_wallet is wallet
    assert wallet.balance_vnd >= _minimum_wallet_balance()
    assert wallet.balance_vnd >= (
        app_settings.charging_minimum_kwh * SIMULATOR_PRICE_VND_PER_KWH
        + app_settings.wallet_reserve_vnd
    )
    topup.assert_awaited_once()
    call = topup.await_args.kwargs
    assert call["driver_id"] == driver.id
    assert call["actor_id"] == administrator.id
    assert call["request"].amount_vnd == wallet.balance_vnd
    assert isinstance(call["request"], ManualTopupRequest)
    assert isinstance(call["authorization"], AuthorizationEvidence)


@pytest.mark.asyncio
async def test_seed_updates_price_for_existing_station() -> None:
    session = AsyncMock(spec=AsyncSession)
    operator = User(
        id=uuid4(), email="simulator-operator@example.com", password_hash=""
    )
    station = Station(
        owner_id=uuid4(),
        name="Existing simulator station",
        address="Test",
        latitude=Decimal(10),
        longitude=Decimal(106),
        price_vnd_per_kwh=None,
        status="inactive",
    )
    session.scalar.return_value = station

    seeded_station = await _station(session, operator, load_settings({}))

    assert seeded_station is station
    assert seeded_station.owner_id == operator.id
    assert seeded_station.price_vnd_per_kwh == SIMULATOR_PRICE_VND_PER_KWH
    assert seeded_station.status == "active"
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_seed_creates_station_with_simulator_price() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None
    operator = User(
        id=uuid4(), email="simulator-operator@example.com", password_hash=""
    )

    station = await _station(session, operator, load_settings({}))

    assert station.price_vnd_per_kwh == SIMULATOR_PRICE_VND_PER_KWH
    session.add.assert_called_once_with(station)


@pytest.mark.asyncio
async def test_seed_tops_up_low_wallet_and_preserves_higher_balance(
    monkeypatch,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    driver = User(id=uuid4(), email="simulator-driver@example.com", password_hash="")
    administrator = User(
        id=uuid4(), email="simulator-admin@example.com", password_hash=""
    )
    settings = load_settings({})
    wallet = Wallet(driver_id=driver.id, balance_vnd=1, status="active")

    async def credit_wallet(_session, **kwargs) -> None:
        wallet.balance_vnd += kwargs["request"].amount_vnd

    topup = AsyncMock(side_effect=credit_wallet)
    monkeypatch.setattr(
        "simulator.seed.ensure_driver_wallet", AsyncMock(return_value=wallet)
    )
    monkeypatch.setattr("simulator.seed.nap_tay", topup)

    seeded_wallet = await _wallet(session, driver, administrator, settings)

    minimum_balance = int(
        _minimum_wallet_balance().to_integral_value(rounding=ROUND_CEILING)
    )
    assert seeded_wallet.balance_vnd == minimum_balance
    assert topup.await_args.kwargs["request"].amount_vnd == minimum_balance - 1
    assert topup.await_count == 1

    wallet.balance_vnd = 25000
    seeded_wallet = await _wallet(session, driver, administrator, settings)

    assert seeded_wallet.balance_vnd == 25000
    assert topup.await_count == 1
