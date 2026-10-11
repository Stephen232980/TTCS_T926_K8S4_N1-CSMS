from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class OcppTelemetryBucket(Base):
    __tablename__ = "ocpp_telemetry_buckets"
    __table_args__ = (
        CheckConstraint(
            "error_count >= 0 AND response_count >= 0 AND latency_total_ms >= 0",
            name="ck_ocpp_telemetry_nonnegative",
        ),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    worker_id: Mapped[UUID] = mapped_column(primary_key=True)
    error_count: Mapped[int] = mapped_column(Integer)
    response_count: Mapped[int] = mapped_column(Integer)
    latency_total_ms: Mapped[float] = mapped_column(Float)
    complete: Mapped[bool] = mapped_column(Boolean)


class SystemHealthSample(Base):
    __tablename__ = "system_health_samples"
    __table_args__ = (
        CheckConstraint(
            "online_charge_points >= 0 AND registered_charge_points >= 0 "
            "AND running_sessions >= 0 AND error_messages_observed_5m >= 0 "
            "AND response_count_5m >= 0 "
            "AND (error_messages_5m IS NULL OR error_messages_5m >= 0) "
            "AND (response_latency_ms IS NULL OR response_latency_ms >= 0)",
            name="ck_system_health_nonnegative",
        ),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    online_charge_points: Mapped[int] = mapped_column(Integer)
    registered_charge_points: Mapped[int] = mapped_column(Integer)
    running_sessions: Mapped[int] = mapped_column(Integer)
    error_messages_5m: Mapped[int | None] = mapped_column(Integer)
    error_messages_observed_5m: Mapped[int] = mapped_column(Integer)
    response_count_5m: Mapped[int] = mapped_column(Integer)
    response_latency_ms: Mapped[float | None] = mapped_column(Float)
    window_complete: Mapped[bool] = mapped_column(Boolean)
