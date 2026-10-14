from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class AlertRuleState(Base):
    __tablename__ = "alert_rule_states"
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE"), primary_key=True
    )
    armed: Mapped[bool] = mapped_column(Boolean, default=True)
    online_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_observations: Mapped[int] = mapped_column(Integer, default=0)


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('offline','error_burst')", name="ck_operational_alert_kind"
        ),
        CheckConstraint(
            "status IN ('open','acknowledged','closed')",
            name="ck_operational_alert_status",
        ),
        Index(
            "uq_operational_alert_active_charger",
            "charge_point_id",
            unique=True,
            postgresql_where=text("status IN ('open','acknowledged')"),
        ),
        Index("ix_operational_alert_opened", "opened_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    close_reason: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class AlertEmail(Base):
    __tablename__ = "alert_emails"
    __table_args__ = (
        Index("uq_alert_email_recipient", "alert_id", "recipient", unique=True),
        Index("ix_alert_email_due", "status", "next_attempt_at"),
        CheckConstraint(
            "status IN ('pending','sending','retry','sent','failed')",
            name="ck_alert_email_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_alert_email_attempts"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(
        ForeignKey("operational_alerts.id", ondelete="RESTRICT")
    )
    recipient: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(40))
