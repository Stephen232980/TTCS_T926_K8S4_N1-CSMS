from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class ConfigurationIntent(Base):
    __tablename__ = "ocpp_configuration_intents"
    __table_args__ = (
        CheckConstraint(
            "(key='HeartbeatInterval' AND value BETWEEN 30 AND 600) OR (key='MeterValueSampleInterval' AND value BETWEEN 5 AND 300)",
            name="ck_configuration_whitelist",
        ),
        CheckConstraint(
            "state IN ('queued','sending','accepted','reboot_required','resetting','verified','needs_review','failed')",
            name="ck_configuration_state",
        ),
        Index("ix_configuration_pending", "state", "next_attempt_at"),
        Index(
            "uq_configuration_active_charger",
            "charge_point_id",
            unique=True,
            postgresql_where=text(
                "state IN ('queued','sending','accepted','reboot_required','resetting')"
            ),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    key: Mapped[str] = mapped_column(String(50))
    value: Mapped[int] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(String(100))
    actual_value: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(30), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(30))
    processing_id: Mapped[UUID | None] = mapped_column()
    reset_id: Mapped[UUID | None] = mapped_column(unique=True)
    reset_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
