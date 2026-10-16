"""Reconciliation runs and issues models for S-53."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint("date_from <= date_to", name="ck_reconciliation_runs_date_range"),
        CheckConstraint("total_sessions >= 0", name="ck_reconciliation_runs_total_sessions"),
        Index("ix_reconciliation_runs_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    period_type: Mapped[str] = mapped_column(String(20), default="month", nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    station_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("stations.id", ondelete="SET NULL"), nullable=True
    )
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mismatch_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_data_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_meter_kwh: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal(0), nullable=False
    )
    total_billed_kwh: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal(0), nullable=False
    )
    kwh_discrepancy: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), default=Decimal(0), nullable=False
    )
    total_billed_vnd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_recomputed_vnd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_debited_vnd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    money_discrepancy_vnd: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    summary_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    algorithm_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ReconciliationIssue(Base):
    __tablename__ = "reconciliation_run_issues"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'warning', 'info')",
            name="ck_reconciliation_issues_severity",
        ),
        Index("ix_reconciliation_issues_run_id", "run_id"),
        Index("ix_reconciliation_issues_session_id", "session_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="CASCADE"), nullable=False
    )
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    billed_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recomputed_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    debited_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    money_difference_vnd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meter_kwh: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    billed_kwh: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    kwh_difference: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
