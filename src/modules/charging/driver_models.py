"""Private virtual tags and durable remote-start reservations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class DriverVirtualTag(Base):
    __tablename__ = "id_tags"
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    card_id: Mapped[UUID] = mapped_column(
        ForeignKey("charging_cards.id", ondelete="RESTRICT"), unique=True
    )
    id_tag: Mapped[str] = mapped_column(String(20), unique=True)


class DriverStartRequest(Base):
    __tablename__ = "driver_start_requests"
    __table_args__ = (
        Index(
            "uq_driver_start_pending_connector",
            "connector_id",
            unique=True,
            postgresql_where=text("status IN ('Pending', 'Accepted')"),
        ),
        Index(
            "uq_driver_start_pending_driver",
            "driver_id",
            unique=True,
            postgresql_where=text("status IN ('Pending', 'Accepted')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT")
    )
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30))
    reply_status: Mapped[str] = mapped_column(String(30))
    reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("charging_sessions.id", ondelete="SET NULL")
    )
