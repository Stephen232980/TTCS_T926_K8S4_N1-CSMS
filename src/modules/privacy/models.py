"""Durable intake and review; approval never implies erasure completion."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_privacy_request_status",
        ),
        CheckConstraint(
            "status = 'pending' OR (reviewer_id IS NOT NULL AND reviewed_at IS NOT NULL AND decision_reason IS NOT NULL AND policy_version IS NOT NULL AND length(trim(decision_reason)) >= 3 AND length(trim(policy_version)) > 0)",
            name="ck_privacy_request_decision",
        ),
        Index(
            "uq_privacy_request_active",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'approved')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str | None] = mapped_column(String(100))


class PrivacyPolicy(Base):
    __tablename__ = "privacy_policies"
    version: Mapped[str] = mapped_column(String(100), primary_key=True)
    document: Mapped[dict[str, object]] = mapped_column(JSONB)
    approval_basis: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PrivacyJob(Base):
    __tablename__ = "privacy_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','processing','needs_review','completed')",
            name="ck_privacy_job_status",
        ),
        CheckConstraint("checkpoint BETWEEN 0 AND 3", name="ck_privacy_job_checkpoint"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("privacy_requests.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued"
    )
    checkpoint: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
