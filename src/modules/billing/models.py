"""Invoice snapshots; rates and money are integer Vietnamese dong."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_invoices_session"),
        CheckConstraint("total_vnd >= 0", name="ck_invoices_total"),
        CheckConstraint("btrim(rounding_rule) <> ''", name="ck_invoices_rounding_rule"),
        Index("ix_invoices_driver_created", "driver_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("charging_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"), nullable=False
    )
    total_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rounding_rule: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    __table_args__ = (
        CheckConstraint(
            "line_type IN ('energy', 'idle')", name="ck_invoice_lines_type"
        ),
        CheckConstraint("started_at < ended_at", name="ck_invoice_lines_interval"),
        CheckConstraint(
            "energy_wh >= 0 AND rate_vnd >= 0 AND amount_vnd >= 0",
            name="ck_invoice_lines_nonnegative",
        ),
        CheckConstraint(
            "line_type <> 'idle' OR energy_wh = 0", name="ck_invoice_lines_idle_energy"
        ),
        CheckConstraint("btrim(band_label) <> ''", name="ck_invoice_lines_label"),
        Index("ix_invoice_lines_invoice", "invoice_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    invoice_id: Mapped[UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    line_type: Mapped[str] = mapped_column(String(20), nullable=False)
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    energy_wh: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    rate_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    band_label: Mapped[str] = mapped_column(String(100), nullable=False)
    interpolated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tariff_id: Mapped[UUID] = mapped_column(
        ForeignKey("tariffs.id", ondelete="RESTRICT"), nullable=False
    )
    amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
