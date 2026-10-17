"""One durable inbox item and email intent per driver/business event."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class DriverNotification(Base):
    __tablename__ = "driver_notifications"
    __table_args__ = (
        UniqueConstraint(
            "driver_id", "event_type", "event_id", name="uq_driver_notification_event"
        ),
        CheckConstraint(
            "event_type IN ('stop','idle','invoice')",
            name="ck_driver_notification_event",
        ),
        CheckConstraint(
            "email_status IN ('pending','sending','sent')",
            name="ck_driver_notification_email",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(20))
    event_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(
        String(20), server_default="pending", default="pending"
    )
    attempts: Mapped[int] = mapped_column(server_default="0", default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
