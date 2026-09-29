from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.modules.identity.models import User
from src.platform.database.base import Base


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (
        Index("ix_stations_owner_id", "owner_id"),
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_stations_latitude_range",
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_stations_longitude_range",
        ),
        CheckConstraint(
            "status IN ('inactive', 'active')",
            name="ck_stations_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default="inactive",
        server_default="inactive",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner: Mapped[User] = relationship(User)


class StationCreateIdempotency(Base):
    __tablename__ = "station_create_idempotency"

    actor_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    idempotency_key: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
