from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.platform.database.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "btrim(action) <> '' AND btrim(object_type) <> '' AND btrim(object_id) <> ''",
            name="ck_audit_logs_identifiers",
        ),
        CheckConstraint("jsonb_typeof(data) = 'object'", name="ck_audit_logs_data"),
        CheckConstraint(
            "actor_roles IS NULL OR jsonb_typeof(actor_roles) = 'array'",
            name="ck_audit_logs_roles",
        ),
        Index("ix_audit_logs_object", "object_type", "object_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    action: Mapped[str] = mapped_column(String(100))
    object_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    permission: Mapped[str | None] = mapped_column(String(100))
    actor_roles: Mapped[list[str] | None] = mapped_column(JSONB(none_as_null=True))


Index("ix_audit_logs_occurred_at_desc", AuditLog.occurred_at.desc())
