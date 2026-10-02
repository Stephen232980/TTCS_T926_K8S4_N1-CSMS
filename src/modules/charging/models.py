from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class ChargingCard(Base):
    __tablename__ = "charging_cards"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tag_hash: Mapped[str] = mapped_column(String(64), unique=True)
    tag_tail: Mapped[str] = mapped_column(String(4))
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    issuer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuthorizationAttempt(Base):
    __tablename__ = "charging_authorization_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE"), index=True
    )
    tag_tail: Mapped[str] = mapped_column(String(4))
    result: Mapped[str] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChargingSession(Base):
    __tablename__ = "charging_sessions"
    __table_args__ = (
        Index("ix_charging_sessions_charge_point_id", "charge_point_id"),
        Index(
            "uq_charging_sessions_open_connector",
            "connector_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(
        Integer, Identity(maxvalue=2147483647), primary_key=True
    )
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE")
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT")
    )
    driver_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    tag_tail: Mapped[str] = mapped_column(String(4))
    authorization_status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meter_start_wh: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    meter_stop_wh: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    energy_kwh: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    stop_reason: Mapped[str | None] = mapped_column(String(50))
    recovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    abnormal_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_close_reason: Mapped[str | None] = mapped_column(String(500))
    closed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_reasons: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MeterSample(Base):
    __tablename__ = "charging_meter_samples"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "measurand",
            "phase",
            "location",
            "timestamp",
            name="uq_charging_meter_sample",
        ),
        Index("ix_charging_meter_session_time", "session_id", "timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="CASCADE")
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    measurand: Mapped[str] = mapped_column(String(50))
    phase: Mapped[str] = mapped_column(String(10), default="", server_default="")
    location: Mapped[str] = mapped_column(
        String(10), default="Outlet", server_default="Outlet"
    )
    value: Mapped[Decimal] = mapped_column(Numeric(24, 6))
    unit: Mapped[str] = mapped_column(String(10))


class ChargingSessionEvent(Base):
    __tablename__ = "charging_session_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PendingChargingMessage(Base):
    __tablename__ = "charging_pending_messages"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    message_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
