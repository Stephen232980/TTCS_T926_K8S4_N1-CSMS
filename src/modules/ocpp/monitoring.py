"""Server-clock liveness and short row updates; never create undeclared connectors."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.modules.stations.models import ChargePoint, Connector, ConnectorError

logger = logging.getLogger("csms.ocpp")
Status = Literal[
    "Available",
    "Preparing",
    "Charging",
    "SuspendedEVSE",
    "SuspendedEV",
    "Finishing",
    "Reserved",
    "Unavailable",
    "Faulted",
]
ErrorCode = Literal[
    "ConnectorLockFailure",
    "EVCommunicationError",
    "GroundFailure",
    "HighTemperature",
    "InternalError",
    "LocalListConflict",
    "NoError",
    "OtherError",
    "OverCurrentFailure",
    "PowerMeterFailure",
    "PowerSwitchFailure",
    "ReaderFailure",
    "ResetFailure",
    "UnderVoltage",
    "OverVoltage",
    "WeakSignal",
]


class HeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StatusPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    connectorId: Annotated[int, Field(ge=0)]
    status: Status
    errorCode: ErrorCode
    vendorErrorCode: Annotated[str, Field(max_length=50)] | None = None
    info: Annotated[str, Field(max_length=50)] | None = None
    vendorId: Annotated[str, Field(max_length=255)] | None = None
    timestamp: AwareDatetime | None = None


def expired(now: datetime) -> ColumnElement[bool]:
    return (ChargePoint.last_seen_at.is_(None)) | (
        ChargePoint.last_seen_at
        < now - ChargePoint.heartbeat_interval_seconds * literal(timedelta(seconds=2))
    )


async def mark_seen(
    session: AsyncSession, charger_id: UUID, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    # Expired connector observations remain unknown after reconnection until reported anew.
    await session.scalar(
        select(ChargePoint.id).where(ChargePoint.id == charger_id).with_for_update()
    )
    stale = select(ChargePoint.id).where(ChargePoint.id == charger_id, expired(now))
    await session.execute(
        update(Connector)
        .where(Connector.charge_point_id.in_(stale), Connector.archived_at.is_(None))
        .values(
            status="unknown",
            raw_ocpp_status=None,
            status_updated_at=now,
            updated_at=Connector.updated_at,
        )
    )
    # Only this column changes on charge_points; no read/modify/write of the ORM record.
    await session.execute(
        text(
            "UPDATE charge_points SET last_seen_at = :now WHERE id = :id AND archived_at IS NULL"
        ),
        {"now": now, "id": charger_id},
    )


async def expire_chargers(session: AsyncSession, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    stale = list(
        await session.scalars(
            select(ChargePoint.id)
            .where(expired(now), ChargePoint.archived_at.is_(None))
            .with_for_update(skip_locked=True)
        )
    )
    await session.execute(
        update(Connector)
        .where(
            Connector.charge_point_id.in_(stale),
            Connector.archived_at.is_(None),
            Connector.status != "unknown",
        )
        .values(status="unknown", raw_ocpp_status=None, status_updated_at=now)
    )
    await session.execute(
        update(ChargePoint)
        .where(
            ChargePoint.id.in_(stale),
            expired(now),
            ChargePoint.archived_at.is_(None),
            ChargePoint.status != "offline",
        )
        .values(status="offline", status_updated_at=now)
    )


async def report_status(
    session: AsyncSession, charger: ChargePoint, status: StatusPayload
) -> None:
    now = datetime.now(UTC)
    if status.connectorId == 0:
        await session.execute(
            update(ChargePoint)
            .where(ChargePoint.id == charger.id)
            .values(
                raw_ocpp_status=status.status,
                error_code=status.errorCode,
                vendor_error_code=status.vendorErrorCode,
                error_at=now if status.errorCode != "NoError" else None,
                status_updated_at=now,
            )
        )
        return
    connector_id = await session.scalar(
        update(Connector)
        .where(
            Connector.charge_point_id == charger.id,
            Connector.connector_number == status.connectorId,
            Connector.archived_at.is_(None),
        )
        .values(
            status=status.status, raw_ocpp_status=status.status, status_updated_at=now
        )
        .returning(Connector.id)
    )
    if connector_id is None:
        logger.warning(
            "ocpp_unknown_connector charger=%s connector=%s",
            charger.id,
            status.connectorId,
        )
        return
    if status.errorCode != "NoError":
        session.add(
            ConnectorError(
                connector_id=connector_id,
                error_code=status.errorCode,
                vendor_error_code=status.vendorErrorCode,
                occurred_at=now,
                details=status.info,
            )
        )
