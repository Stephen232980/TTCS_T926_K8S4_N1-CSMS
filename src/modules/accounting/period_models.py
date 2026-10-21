"""Monthly reconciliation close, immutable snapshots, and reopen revisions."""

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class PeriodClose(Base):
    __tablename__ = "period_closes"
    __table_args__ = (
        CheckConstraint(
            "EXTRACT(DAY FROM period_start) = 1",
            name="ck_period_closes_month_start",
        ),
        CheckConstraint(
            "period_end >= period_start", name="ck_period_closes_date_range"
        ),
        CheckConstraint("status IN ('open', 'closed')", name="ck_period_closes_status"),
        CheckConstraint("revision >= 1", name="ck_period_closes_revision"),
        UniqueConstraint("period_start", name="uq_period_closes_period_start"),
        Index("ix_period_closes_status", "status", "period_start"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PeriodSnapshot(Base):
    __tablename__ = "period_snapshots"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_period_snapshots_revision"),
        CheckConstraint(
            "length(snapshot_hash) = 64", name="ck_period_snapshots_hash_length"
        ),
        UniqueConstraint(
            "period_close_id",
            "revision",
            name="uq_period_snapshots_close_revision",
        ),
        UniqueConstraint(
            "reconciliation_run_id",
            name="uq_period_snapshots_reconciliation_run",
        ),
        Index("ix_period_snapshots_close_id", "period_close_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_close_id: Mapped[UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reconciliation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="RESTRICT"), nullable=False
    )
    closed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PeriodRevision(Base):
    __tablename__ = "period_revisions"
    __table_args__ = (
        CheckConstraint("revision >= 2", name="ck_period_revisions_revision"),
        CheckConstraint("btrim(reason) <> ''", name="ck_period_revisions_reason"),
        UniqueConstraint(
            "period_close_id",
            "revision",
            name="uq_period_revisions_close_revision",
        ),
        Index("ix_period_revisions_close_id", "period_close_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_close_id: Mapped[UUID] = mapped_column(
        ForeignKey("period_closes.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("period_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    reopened_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reopened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
