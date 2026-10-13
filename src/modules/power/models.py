from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class StationPower(Base):
    __tablename__ = "station_power"
    __table_args__ = (
        CheckConstraint("limit_w > 0 AND applied_limit_w > 0", name="ck_power_limits"),
        CheckConstraint("version > 0 AND generation >= 0", name="ck_power_versions"),
        CheckConstraint(
            "state IN ('disabled','bootstrap','ready','applying','degraded','disable_pending')",
            name="ck_power_state",
        ),
    )
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), primary_key=True
    )
    limit_w: Mapped[int] = mapped_column(BigInteger)
    applied_limit_w: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(Integer, default=1)
    generation: Mapped[int] = mapped_column(BigInteger, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    target_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), default="disabled")
    # Explicit commissioning evidence, never inferred from Accepted alone.
    zero_limit_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    offline_retention_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_note: Mapped[str] = mapped_column(String(500), default="")
    issue: Mapped[str | None] = mapped_column(String(80))
    dirty_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_plan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConnectorPower(Base):
    __tablename__ = "connector_power"
    __table_args__ = (
        CheckConstraint(
            "rated_w > 0 AND confirmed_w >= 0 AND reserved_w >= confirmed_w",
            name="ck_connector_power",
        ),
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT"), primary_key=True
    )
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("station_power.station_id", ondelete="CASCADE"), index=True
    )
    rated_w: Mapped[int] = mapped_column(BigInteger)
    profile_id: Mapped[int] = mapped_column(
        Integer, Identity(maxvalue=1073741822), unique=True
    )
    confirmed_w: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_w: Mapped[int] = mapped_column(BigInteger, default=0)
    desired_w: Mapped[int] = mapped_column(BigInteger, default=0)
    baseline_boot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Command intent is durable before any socket write; uncertain results retain budget.
    pending_command_id: Mapped[UUID | None] = mapped_column()


class PowerCommand(Base):
    __tablename__ = "power_commands"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("station_power.station_id", ondelete="CASCADE"), index=True
    )
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT")
    )
    generation: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30), default="Pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
