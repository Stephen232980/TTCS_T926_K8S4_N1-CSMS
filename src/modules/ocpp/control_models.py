"""Immutable command requests and outcomes: one audit record per intent."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class ControlRequest(Base):
    __tablename__ = "ocpp_control_requests"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_email: Mapped[str] = mapped_column(String(320))
    charge_point_code: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT"), index=True
    )
    transaction_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ControlResult(Base):
    __tablename__ = "ocpp_control_results"
    command_id: Mapped[UUID] = mapped_column(
        ForeignKey("ocpp_control_requests.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(30))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
