from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.modules.billing.invoicing import _active_subscription_frames
from src.modules.billing.segmentation import TariffFrame
from src.modules.identity.models import Role, User, UserRole
from src.modules.stations.models import Station
from src.modules.subscriptions.models import DriverSubscription
from src.modules.subscriptions.service import (
    SubscriptionFundsError,
    add_calendar_month,
    dang_ky,
    gia_han_den_han,
    tao_goi,
)
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.provisioning import ensure_driver_wallet
from src.modules.wallet.service import ghi_so_cai


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (datetime(2026, 1, 31, 10, tzinfo=UTC), datetime(2026, 2, 28, 10, tzinfo=UTC)),
        (datetime(2028, 1, 31, 10, tzinfo=UTC), datetime(2028, 2, 29, 10, tzinfo=UTC)),
        (datetime(2026, 12, 31, 10, tzinfo=UTC), datetime(2027, 1, 31, 10, tzinfo=UTC)),
    ],
)
def test_month_period_uses_calendar_month_and_clamps_last_day(start, expected):
    assert add_calendar_month(start) == expected


async def make_station_and_driver(db_session):
    owner = User(email=f"subscription-owner-{uuid4()}@example.com", password_hash="x")
    driver = User(email=f"subscription-driver-{uuid4()}@example.com", password_hash="x")
    role = await db_session.scalar(select(Role).where(Role.code == "driver"))
    if role is None:
        role = Role(code="driver")
        db_session.add(role)
    db_session.add_all([owner, driver])
    await db_session.flush()
    db_session.add(UserRole(user_id=driver.id, role_id=role.id))
    station = Station(
        owner_id=owner.id,
        name="Subscription test station",
        address="Test address",
        latitude=Decimal("10.7"),
        longitude=Decimal("106.7"),
    )
    db_session.add(station)
    await db_session.flush()
    return station, driver


@pytest.mark.asyncio
async def test_wallet_subscription_renewal_and_invoice_rate_snapshot(db_session):
    station, driver = await make_station_and_driver(db_session)
    wallet = await ensure_driver_wallet(db_session, driver.id)
    await ghi_so_cai(
        db_session,
        wallet_id=wallet.id,
        entry_type="manual_topup",
        amount_vnd=350_000,
        reference_type="test",
        reference_id=str(uuid4()),
    )
    plan = await tao_goi(
        db_session,
        station_id=station.id,
        name="Monthly",
        monthly_fee_vnd=200_000,
        bands=[(0, 1440, 1_200, "Subscriber energy")],
    )
    started_at = datetime(2026, 1, 31, 10, tzinfo=UTC)
    subscription = await dang_ky(
        db_session, driver_id=driver.id, plan_id=plan.id, now=started_at
    )
    assert subscription.current_period_end == datetime(2026, 2, 28, 10, tzinfo=UTC)
    assert wallet.balance_vnd == 150_000

    station_frame = TariffFrame("00:00", "24:00", 3_000, str(uuid4()), "Standard")
    plan_id, frames = await _active_subscription_frames(
        db_session,
        driver_id=driver.id,
        station_id=station.id,
        started_at=started_at,
        frames={started_at.date(): [station_frame]},
    )
    assert plan_id == plan.id
    assert frames[started_at.date()][0].price_vnd_per_kwh == 1_200
    assert frames[started_at.date()][0].tariff_version == station_frame.tariff_version

    due_at = subscription.current_period_end + timedelta(minutes=1)
    assert await gia_han_den_han(db_session, now=due_at) == 0
    await db_session.refresh(subscription)
    assert subscription.status == "past_due"
    assert subscription.current_period_end < subscription.next_billing_at

    await ghi_so_cai(
        db_session,
        wallet_id=wallet.id,
        entry_type="manual_topup",
        amount_vnd=50_000,
        reference_type="test",
        reference_id=str(uuid4()),
    )
    retry_at = subscription.next_billing_at + timedelta(seconds=1)
    assert await gia_han_den_han(db_session, now=retry_at) == 1
    await db_session.refresh(subscription)
    await db_session.refresh(wallet)
    assert subscription.status == "active"
    assert subscription.current_period_start == retry_at
    assert subscription.current_period_end == add_calendar_month(retry_at)
    assert wallet.balance_vnd == 0

    charges = list(
        await db_session.scalars(
            select(WalletLedger).where(
                WalletLedger.wallet_id == wallet.id,
                WalletLedger.entry_type == "subscription_debit",
            )
        )
    )
    assert len(charges) == 2
    assert all(row.amount_vnd == -200_000 for row in charges)
    assert all(row.reference_type == "subscription" for row in charges)


@pytest.mark.asyncio
async def test_initial_subscription_rejects_insufficient_wallet_without_charge(
    db_session,
):
    station, driver = await make_station_and_driver(db_session)
    plan = await tao_goi(
        db_session,
        station_id=station.id,
        name="Paid monthly",
        monthly_fee_vnd=200_000,
        bands=[(0, 1440, 1_200, "All day")],
    )
    with pytest.raises(SubscriptionFundsError):
        async with db_session.begin_nested():
            await dang_ky(
                db_session,
                driver_id=driver.id,
                plan_id=plan.id,
                now=datetime(2026, 1, 1, tzinfo=UTC),
            )
    assert (
        await db_session.scalar(
            select(DriverSubscription).where(DriverSubscription.driver_id == driver.id)
        )
        is None
    )
    wallet = await db_session.scalar(
        select(Wallet).where(Wallet.driver_id == driver.id)
    )
    assert wallet is None
