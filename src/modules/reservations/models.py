from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base

HOLDS = ("pending", "uncertain", "active", "cancel_pending", "expiry_release_pending")
TERMINAL = ("consumed", "cancelled", "rejected", "expired")
HOLD_SQL = "status IN ('pending','uncertain','active','cancel_pending','expiry_release_pending')"


class ReservationCapability(Base):
    __tablename__ = "reservation_capabilities"
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE"), primary_key=True
    )
    boot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supported: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_token: Mapped[UUID | None] = mapped_column()
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(40), default="unverified")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','uncertain','active','cancel_pending','expiry_release_pending','consumed','cancelled','rejected','expired')",
            name="ck_reservation_status",
        ),
        CheckConstraint("ocpp_id > 0", name="ck_reservation_ocpp_id"),
        CheckConstraint(
            "expires_at > arrival_at AND arrival_at >= created_at",
            name="ck_reservation_times",
        ),
        Index(
            "uq_reservation_connector_hold",
            "connector_id",
            unique=True,
            postgresql_where=text(HOLD_SQL),
        ),
        Index(
            "uq_reservation_driver_hold",
            "driver_id",
            unique=True,
            postgresql_where=text(HOLD_SQL),
        ),
        Index("ix_reservation_driver_created", "driver_id", "created_at"),
        Index("ix_reservation_expiry", "status", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    ocpp_id: Mapped[int] = mapped_column(
        Integer, Identity(maxvalue=2147483647, cycle=False), unique=True
    )
    driver_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT")
    )
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT")
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT")
    )
    card_id: Mapped[UUID] = mapped_column(
        ForeignKey("charging_cards.id", ondelete="RESTRICT")
    )
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(40))
    cancel_request_id: Mapped[UUID | None] = mapped_column(unique=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(40))
    no_show_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="RESTRICT"), unique=True
    )


class ReservationCommand(Base):
    __tablename__ = "reservation_commands"
    __table_args__ = (
        CheckConstraint(
            "action IN ('ReserveNow','CancelReservation')",
            name="ck_reservation_command_action",
        ),
        CheckConstraint(
            "status IN ('queued','sending','done','uncertain','suppressed')",
            name="ck_reservation_command_status",
        ),
        Index("uq_reservation_command_action", "reservation_id", "action", unique=True),
        Index("ix_reservation_command_due", "status", "next_attempt_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    outcome: Mapped[str | None] = mapped_column(String(40))


class ReservationEvent(Base):
    __tablename__ = "reservation_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
