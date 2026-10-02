from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

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
            "status IN ('inactive', 'active', 'suspended', 'blocked')",
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
    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Asia/Ho_Chi_Minh",
        server_default="Asia/Ho_Chi_Minh",
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    charge_points: Mapped[list[ChargePoint]] = relationship(
        "ChargePoint",
        back_populates="station",
        passive_deletes=True,
    )


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


class ChargePoint(Base):
    __tablename__ = "charge_points"
    __table_args__ = (
        Index("ix_charge_points_code", "code", unique=True),
        Index("ix_charge_points_station_id", "station_id"),
        Index("ix_charge_points_last_seen_at", "last_seen_at"),
        CheckConstraint(
            "heartbeat_interval_seconds > 0", name="ck_charge_points_heartbeat_positive"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    vendor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="offline",
        server_default="offline",
        nullable=False,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    heartbeat_interval_seconds: Mapped[int] = mapped_column(
        Integer, default=60, server_default="60", nullable=False
    )
    raw_ocpp_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vendor_error_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_boot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    code_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    station: Mapped[Station] = relationship(
        "Station",
        back_populates="charge_points",
    )
    connectors: Mapped[list[Connector]] = relationship(
        "Connector",
        back_populates="charge_point",
        passive_deletes=True,
    )

    @validates("code")
    def normalize_code(self, _key: str, value: str) -> str:
        return value.strip()


Index(
    "uq_charge_points_code_ci",
    func.lower(ChargePoint.__table__.c.code),
    unique=True,
)


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint(
            "charge_point_id",
            "connector_number",
            name="uq_connectors_cp_id_connector_number",
        ),
        CheckConstraint(
            "connector_number >= 1",
            name="ck_connectors_connector_number_gte_1",
        ),
        CheckConstraint(
            "max_power_kw IS NULL OR max_power_kw > 0",
            name="ck_connectors_max_power_kw_positive",
        ),
        CheckConstraint(
            "voltage IS NULL OR voltage > 0",
            name="ck_connectors_voltage_positive",
        ),
        CheckConstraint(
            "amperage IS NULL OR amperage > 0",
            name="ck_connectors_amperage_positive",
        ),
        Index("ix_connectors_charge_point_id", "charge_point_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    charge_point_id: Mapped[UUID] = mapped_column(
        ForeignKey("charge_points.id", ondelete="RESTRICT"),
        nullable=False,
    )
    connector_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    raw_ocpp_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    connector_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    max_power_kw: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 3),
        nullable=True,
    )
    current_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    voltage: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    amperage: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    charge_point: Mapped[ChargePoint] = relationship(
        "ChargePoint",
        back_populates="connectors",
    )
    errors: Mapped[list[ConnectorError]] = relationship(
        "ConnectorError",
        back_populates="connector",
        passive_deletes=True,
    )


class ConnectorError(Base):
    __tablename__ = "connector_errors"
    __table_args__ = (
        Index(
            "ix_connector_errors_connector_id_occurred_at",
            "connector_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connector_id: Mapped[UUID] = mapped_column(
        ForeignKey("connectors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor_error_code: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    details: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    connector: Mapped[Connector] = relationship(
        "Connector",
        back_populates="errors",
    )
