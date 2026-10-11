from uuid import uuid4

import pytest
from sqlalchemy import func, select

from simulator import seed
from simulator.config import load_settings
from src.modules.charging import service as charging_service
from src.modules.identity.models import Role, User, UserRole
from src.modules.stations.models import ChargePoint, Station
from src.modules.wallet.eligibility import du_so_du_de_sac
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_ocpp_control import control
from tests.test_ocpp_control import db_session as control_database

db_session = control_database


@pytest.mark.asyncio
async def test_simulator_seed_funds_drivers_to_wallet_eligibility(
    db_session, monkeypatch
):
    monkeypatch.setattr(seed, "SessionFactory", control.SessionFactory)
    monkeypatch.setenv("SIMULATOR_OPERATOR_PASSWORD", "test-only-password")
    settings = load_settings(
        {
            "SIMULATOR_COUNT": "1",
            "SIMULATOR_CODE_PREFIX": f"S26-{uuid4().hex[:8]}-",
            "SIMULATOR_TAG_PREFIX": f"S26TAG-{uuid4().hex[:6]}-",
        }
    )

    await seed.seed_simulator_data(settings)

    driver = await db_session.scalar(
        select(User).where(User.email == "simulator-driver-001@example.com")
    )
    charger = await db_session.scalar(
        select(ChargePoint).where(ChargePoint.code == settings.code_for(1))
    )
    assert driver is not None and charger is not None
    station = await db_session.get(Station, charger.station_id)
    assert station is not None
    wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    assert wallet is not None
    eligibility = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id
    )

    assert eligibility.allowed
    assert eligibility.minimum_balance_vnd is not None
    assert wallet.balance_vnd >= eligibility.minimum_balance_vnd
    ledger_entries = (
        await db_session.scalars(
            select(WalletLedger).where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.reference_type == "simulator_seed",
            )
        )
    ).all()
    balance_after_first_seed = wallet.balance_vnd
    ledger_count_after_first_seed = len(ledger_entries)
    result, card, wallet_reason = await charging_service.authorize(
        db_session, charger, settings.tag_for(1)
    )
    assert result == "Accepted"
    assert card is not None and card.driver_id == driver.id
    assert wallet_reason is None

    await seed.seed_simulator_data(settings)
    await db_session.refresh(wallet)
    assert wallet.balance_vnd == balance_after_first_seed
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.reference_type == "simulator_seed",
            )
        )
        == ledger_count_after_first_seed
    )

    driver = User(
        email=f"simulator-wallet-{uuid4()}@example.com", password_hash="unused"
    )
    db_session.add(driver)
    await db_session.flush()
    role = await db_session.scalar(select(Role).where(Role.code == "driver"))
    assert role is not None
    db_session.add(UserRole(user_id=driver.id, role_id=role.id))
    await db_session.flush()

    await seed._ensure_simulator_wallet(db_session, driver, station)

    wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    assert wallet is not None
    funded = await du_so_du_de_sac(
        db_session, driver_id=driver.id, station_id=station.id
    )
    assert funded.allowed
    assert funded.minimum_balance_vnd is not None
    assert wallet.balance_vnd == funded.minimum_balance_vnd
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.reference_type == "simulator_seed",
            )
        )
        == 1
    )
