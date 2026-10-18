"""Atomic wallet billing and calendar-month entitlement lifecycle."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.subscriptions.models import (
    DriverSubscription,
    SubscriptionPlan,
    SubscriptionPlanBand,
)
from src.modules.wallet.exceptions import WalletLockedError
from src.modules.wallet.models import Wallet
from src.modules.wallet.provisioning import ensure_driver_wallet
from src.modules.wallet.service import ghi_so_cai

logger = logging.getLogger("csms.subscriptions")


class SubscriptionError(Exception):
    pass


class SubscriptionNotFoundError(SubscriptionError):
    pass


class SubscriptionConflictError(SubscriptionError):
    pass


class SubscriptionFundsError(SubscriptionError):
    pass


def add_calendar_month(value: datetime) -> datetime:
    """Advance one UTC calendar month, clamping dates such as January 31."""
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    if month == 12:
        last_day = 31
    elif month in {4, 6, 9, 11}:
        last_day = 30
    elif month == 2:
        last_day = 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    else:
        last_day = 31
    return value.replace(year=year, month=month, day=min(value.day, last_day))


async def tao_goi(
    db: AsyncSession,
    *,
    station_id: UUID,
    name: str,
    monthly_fee_vnd: int,
    bands: list[tuple[int, int, int, str]],
) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        station_id=station_id, name=name, monthly_fee_vnd=monthly_fee_vnd
    )
    db.add(plan)
    await db.flush()
    db.add_all(
        [
            SubscriptionPlanBand(
                plan_id=plan.id,
                start_min=start,
                end_min=end,
                energy_rate_vnd_per_kwh=rate,
                label=label,
            )
            for start, end, rate, label in bands
        ]
    )
    await db.flush()
    return plan


async def lay_goi(
    db: AsyncSession, plan_id: UUID, *, lock: bool = False
) -> SubscriptionPlan:
    query = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    plan = await db.scalar(query)
    if plan is None:
        raise SubscriptionNotFoundError("Subscription plan does not exist")
    return plan


async def _charge_period(
    db: AsyncSession,
    subscription: DriverSubscription,
    plan: SubscriptionPlan,
    period_start: datetime,
) -> None:
    wallet = await db.scalar(
        select(Wallet)
        .where(Wallet.driver_id == subscription.driver_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if wallet is None:
        wallet = await ensure_driver_wallet(db, subscription.driver_id)
        wallet = await db.scalar(
            select(Wallet)
            .where(Wallet.id == wallet.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if wallet is None:
        raise SubscriptionFundsError("Driver wallet does not exist")
    if wallet.status == "locked":
        raise WalletLockedError("Wallet is locked")
    if wallet.balance_vnd < plan.monthly_fee_vnd:
        raise SubscriptionFundsError("Insufficient wallet balance")
    await ghi_so_cai(
        db,
        wallet_id=wallet.id,
        entry_type="subscription_debit",
        amount_vnd=-plan.monthly_fee_vnd,
        reference_type="subscription",
        reference_id=f"{subscription.id}:{period_start.isoformat()}",
    )


async def dang_ky(
    db: AsyncSession,
    *,
    driver_id: UUID,
    plan_id: UUID,
    now: datetime | None = None,
) -> DriverSubscription:
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    timestamp = timestamp.astimezone(UTC)
    plan = await lay_goi(db, plan_id, lock=True)
    if not plan.active:
        raise SubscriptionNotFoundError("Subscription plan is inactive")
    await ensure_driver_wallet(db, driver_id)
    existing = await db.scalar(
        select(DriverSubscription)
        .where(
            DriverSubscription.driver_id == driver_id,
            DriverSubscription.station_id == plan.station_id,
            (
                (DriverSubscription.status.in_(("active", "past_due")))
                | (DriverSubscription.current_period_end > timestamp)
            ),
        )
        .with_for_update()
    )
    if existing is not None:
        raise SubscriptionConflictError(
            "An active subscription already exists for this station"
        )
    period_end = add_calendar_month(timestamp)
    subscription = DriverSubscription(
        driver_id=driver_id,
        station_id=plan.station_id,
        plan_id=plan.id,
        status="active",
        current_period_start=timestamp,
        current_period_end=period_end,
        next_billing_at=period_end,
    )
    db.add(subscription)
    await db.flush()
    await _charge_period(db, subscription, plan, timestamp)
    return subscription


async def huy_dang_ky(
    db: AsyncSession,
    *,
    driver_id: UUID,
    subscription_id: UUID,
) -> DriverSubscription:
    subscription = await db.scalar(
        select(DriverSubscription)
        .where(
            DriverSubscription.id == subscription_id,
            DriverSubscription.driver_id == driver_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if subscription is None:
        raise SubscriptionNotFoundError("Subscription does not exist")
    if subscription.status == "cancelled":
        raise SubscriptionConflictError("Subscription is already cancelled")
    subscription.status = "cancelled"
    subscription.next_billing_at = subscription.current_period_end
    await db.flush()
    return subscription


async def gia_han_den_han(
    db: AsyncSession, *, now: datetime | None = None, limit: int = 100
) -> int:
    """Bill a bounded due batch; lock skips allow multiple worker processes."""
    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("A timezone-aware timestamp is required")
    timestamp = timestamp.astimezone(UTC)
    if limit < 1:
        raise ValueError("limit must be positive")
    due_ids = list(
        await db.scalars(
            select(DriverSubscription.id)
            .where(
                DriverSubscription.status.in_(("active", "past_due")),
                DriverSubscription.next_billing_at <= timestamp,
            )
            .order_by(DriverSubscription.next_billing_at, DriverSubscription.id)
            .limit(limit)
        )
    )
    renewed = 0
    for subscription_id in due_ids:
        subscription = await db.scalar(
            select(DriverSubscription)
            .where(
                DriverSubscription.id == subscription_id,
                DriverSubscription.status.in_(("active", "past_due")),
                DriverSubscription.next_billing_at <= timestamp,
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if subscription is None:
            continue
        plan = await lay_goi(db, subscription.plan_id)
        period_start = max(timestamp, subscription.current_period_end)
        try:
            await _charge_period(db, subscription, plan, period_start)
        except (SubscriptionFundsError, WalletLockedError):
            subscription.status = "past_due"
            subscription.next_billing_at = timestamp + timedelta(days=1)
            await db.flush()
            logger.warning(
                "monthly_subscription_renewal_deferred subscription=%s",
                subscription.id,
            )
            continue
        subscription.status = "active"
        subscription.current_period_start = period_start
        subscription.current_period_end = add_calendar_month(period_start)
        subscription.next_billing_at = subscription.current_period_end
        await db.flush()
        renewed += 1
    return renewed
