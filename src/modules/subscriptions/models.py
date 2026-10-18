"""Monthly station subscription plans, rates, and driver entitlements."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint("monthly_fee_vnd > 0", name="ck_subscription_plan_fee"),
        CheckConstraint("btrim(name) <> ''", name="ck_subscription_plan_name"),
        Index("ix_subscription_plans_station_active", "station_id", "active"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_fee_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubscriptionPlanBand(Base):
    __tablename__ = "subscription_plan_bands"
    __table_args__ = (
        CheckConstraint(
            "start_min >= 0 AND start_min < end_min AND end_min <= 1440",
            name="ck_subscription_bands_minute_range",
        ),
        CheckConstraint(
            "energy_rate_vnd_per_kwh >= 0",
            name="ck_subscription_bands_rate_nonnegative",
        ),
        CheckConstraint("btrim(label) <> ''", name="ck_subscription_bands_label"),
        Index("ix_subscription_plan_bands_plan_id", "plan_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    start_min: Mapped[int] = mapped_column(Integer, nullable=False)
    end_min: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_rate_vnd_per_kwh: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)


class DriverSubscription(Base):
    __tablename__ = "driver_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'past_due', 'cancelled')",
            name="ck_driver_subscription_status",
        ),
        CheckConstraint(
            "current_period_start < current_period_end",
            name="ck_driver_subscription_period",
        ),
        Index(
            "uq_driver_subscription_station_active",
            "driver_id",
            "station_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'past_due')"),
        ),
        Index("ix_driver_subscriptions_due", "status", "next_billing_at"),
        Index(
            "ix_driver_subscriptions_driver_station",
            "driver_id",
            "station_id",
            "current_period_end",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    next_billing_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
