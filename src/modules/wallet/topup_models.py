"""Payment attempts; wallet credits are recorded separately in the ledger."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class WalletTopup(Base):
    __tablename__ = "wallet_topups"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_wallet_topups_order"),
        UniqueConstraint("gateway_transaction_id", name="uq_wallet_topups_gateway"),
        CheckConstraint("amount_vnd > 0", name="ck_wallet_topups_amount"),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'cancelled', 'needs_review')",
            name="ck_wallet_topups_status",
        ),
        CheckConstraint("btrim(order_id) <> ''", name="ck_wallet_topups_order"),
        CheckConstraint(
            "gateway_transaction_id IS NULL OR btrim(gateway_transaction_id) <> ''",
            name="ck_wallet_topups_gateway",
        ),
        Index("ix_wallet_topups_driver_created", "driver_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    driver_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gateway_transaction_id: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
