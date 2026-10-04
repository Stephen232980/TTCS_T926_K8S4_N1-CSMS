"""Durable replies make repeated charger calls safe across restarts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class OcppMessageReply(Base):
    __tablename__ = "ocpp_message_replies"
    __table_args__ = (Index("ix_ocpp_message_replies_created_at", "created_at"),)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RemoteCommandLog(Base):
    __tablename__ = "ocpp_remote_command_logs"
    __table_args__ = (
        Index("ix_ocpp_remote_command_logs_charge_point_id", "charge_point_id"),
        Index("ix_ocpp_remote_command_logs_user_id", "user_id"),
        Index("ix_ocpp_remote_command_logs_created_at", "created_at"),
    )
    
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    charge_point_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT"), nullable=True
    )
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="RESTRICT"), nullable=True
    )
    command: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
