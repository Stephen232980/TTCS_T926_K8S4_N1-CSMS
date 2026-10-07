"""Wallet amounts are signed integer Vietnamese dong, including debt balances."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("driver_id", name="uq_wallets_driver"),
        CheckConstraint("status IN ('active', 'locked')", name="ck_wallets_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    balance_vnd: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class WalletLedger(Base):
    __tablename__ = "wallet_ledger"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('gateway_topup', 'manual_topup', 'charging_debit', 'adjustment')",
            name="ck_wallet_ledger_entry_type",
        ),
        CheckConstraint(
            "btrim(reference_type) <> '' AND btrim(reference_id) <> ''",
            name="ck_wallet_ledger_reference_nonempty",
        ),
        CheckConstraint(
            "entry_type <> 'adjustment' OR (actor_id IS NOT NULL AND reference_type = 'audit')",
            name="ck_wallet_ledger_adjustment_audit",
        ),
        UniqueConstraint(
            "entry_type", "reference_id", name="uq_wallet_ledger_reference"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Gateway and automatic charging entries have no human actor.
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


Index(
    "ix_wallet_ledger_wallet_id_id_desc", WalletLedger.wallet_id, WalletLedger.id.desc()
)


class WalletAudit(Base):
    """Administrative evidence; a cache repair is not a monetary ledger entry."""

    __tablename__ = "wallet_audits"
    __table_args__ = (
        CheckConstraint(
            "action IN ('cache_repaired', 'adjustment_authorized')",
            name="ck_wallet_audits_action",
        ),
        CheckConstraint("btrim(reason) <> ''", name="ck_wallet_audits_reason"),
        CheckConstraint(
            "(action = 'cache_repaired' AND amount_vnd IS NULL) OR "
            "(action = 'adjustment_authorized' AND amount_vnd IS NOT NULL "
            "AND amount_vnd <> 0 AND after_balance_vnd::numeric = "
            "before_balance_vnd::numeric + amount_vnd::numeric)",
            name="ck_wallet_audits_amount",
        ),
        Index("ix_wallet_audits_wallet_created", "wallet_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    before_balance_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    after_balance_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_vnd: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
