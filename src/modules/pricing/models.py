"""Versioned station tariffs. Monetary rates are integer Vietnamese dong."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class Tariff(Base):
    __tablename__ = "tariffs"
    __table_args__ = (
        UniqueConstraint(
            "station_id", "effective_from", name="uq_tariffs_station_effective_from"
        ),
        CheckConstraint(
            "idle_rate_vnd_per_minute >= 0", name="ck_tariffs_idle_rate_nonnegative"
        ),
        CheckConstraint("grace_minutes >= 0", name="ck_tariffs_grace_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    # Local calendar date in the station's timezone, not a UTC timestamp.
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    # Set in the invoice transaction; never clear when invoices are retained.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_rate_vnd_per_minute: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TariffBand(Base):
    __tablename__ = "tariff_bands"
    __table_args__ = (
        CheckConstraint(
            "start_min >= 0 AND start_min < end_min AND end_min <= 1440",
            name="ck_tariff_bands_minute_range",
        ),
        CheckConstraint(
            "energy_rate_vnd_per_kwh >= 0",
            name="ck_tariff_bands_energy_rate_nonnegative",
        ),
        Index("ix_tariff_bands_tariff_id", "tariff_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tariff_id: Mapped[UUID] = mapped_column(
        ForeignKey("tariffs.id", ondelete="RESTRICT"), nullable=False
    )
    start_min: Mapped[int] = mapped_column(Integer, nullable=False)
    end_min: Mapped[int] = mapped_column(Integer, nullable=False)
    energy_rate_vnd_per_kwh: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
