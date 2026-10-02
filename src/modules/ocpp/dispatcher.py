"""Transactional handlers and persistent duplicate replies."""

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.modules.charging.service import charging_call
from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.frames import Frame, encode_frame, error_frame
from src.modules.ocpp.models import OcppMessageReply
from src.modules.ocpp.monitoring import (
    HeartbeatPayload,
    StatusPayload,
    mark_seen,
    report_status,
)
from src.modules.stations.models import ChargePoint, Station
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.ocpp")


class BootPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chargePointVendor: Annotated[str, Field(max_length=20)]
    chargePointModel: Annotated[str, Field(max_length=20)]
    chargePointSerialNumber: Annotated[str, Field(max_length=25)] | None = None
    chargeBoxSerialNumber: Annotated[str, Field(max_length=25)] | None = None
    firmwareVersion: Annotated[str, Field(max_length=50)] | None = None
    iccid: Annotated[str, Field(max_length=20)] | None = None
    imsi: Annotated[str, Field(max_length=20)] | None = None
    meterType: Annotated[str, Field(max_length=25)] | None = None
    meterSerialNumber: Annotated[str, Field(max_length=25)] | None = None


async def process_call(
    connection: OcppConnection,
    frame: Frame,
    session: AsyncSession,
    *,
    record_seen: bool = False,
) -> str:
    """Caller owns the transaction; the charger row serializes simultaneous repeats."""
    charge_point = await session.scalar(
        select(ChargePoint)
        .where(ChargePoint.id == connection.charge_point_id)
        .with_for_update()
    )
    if charge_point is None or charge_point.archived_at is not None:
        return error_frame(
            frame.message_id, "SecurityError", "Charger registration is unavailable"
        )
    if record_seen:
        await mark_seen(session, charge_point.id, locked_charger=charge_point)
    digest = hashlib.sha256(
        json.dumps(
            [frame.action, frame.payload],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    cached = await session.get(OcppMessageReply, (charge_point.id, frame.message_id))
    if cached is not None:
        if cached.request_hash != digest:
            logger.warning(
                "ocpp_duplicate_payload_mismatch charger=%s message_id=%s",
                charge_point.id,
                frame.message_id,
            )
        # Boot approval belongs to this connection, including a persisted replay.
        if frame.action == "BootNotification":
            reply = json.loads(cached.response)
            station = await session.scalar(
                select(Station)
                .where(Station.id == charge_point.station_id)
                .with_for_update()
            )
            connection.boot_accepted = (
                reply[0] == 3
                and reply[2].get("status") == "Accepted"
                and station is not None
                and station.archived_at is None
                and station.status != "blocked"
            )
        return cached.response

    if frame.action != "BootNotification" and not connection.boot_accepted:
        response = error_frame(
            frame.message_id, "SecurityError", "BootNotification must be accepted first"
        )
    elif frame.action == "BootNotification":
        try:
            boot = BootPayload.model_validate(frame.payload)
            # OCPP optional properties may be absent, but cannot be JSON null.
            if any(value is None for value in frame.payload.values()):
                raise ValueError("Null property")
        except ValidationError as error:
            kind = error.errors()[0]["type"]
            code = (
                "OccurrenceConstraintViolation"
                if kind == "missing"
                else "TypeConstraintViolation"
                if kind == "string_type"
                else "PropertyConstraintViolation"
            )
            response = error_frame(
                frame.message_id, code, "Invalid BootNotification payload"
            )
        except ValueError:
            response = error_frame(
                frame.message_id,
                "PropertyConstraintViolation",
                "Invalid BootNotification payload",
            )
        else:
            station = await session.scalar(
                select(Station)
                .where(Station.id == charge_point.station_id)
                .with_for_update()
            )
            accepted = (
                station is not None
                and station.archived_at is None
                and station.status != "blocked"
            )
            connection.boot_accepted = accepted
            now = datetime.now(UTC)
            if accepted:
                charge_point.vendor = boot.chargePointVendor
                charge_point.model = boot.chargePointModel
                if "firmwareVersion" in frame.payload:
                    charge_point.firmware_version = boot.firmwareVersion
                charge_point.last_boot_at = now
                charge_point.heartbeat_interval_seconds = (
                    settings.ocpp_heartbeat_interval_seconds
                )
                charge_point.status = "online"
                charge_point.status_updated_at = now
            else:
                charge_point.status = "offline"
            response = encode_frame(
                Frame(
                    3,
                    frame.message_id,
                    {
                        "status": "Accepted" if accepted else "Rejected",
                        "currentTime": now.isoformat(),
                        "interval": settings.ocpp_heartbeat_interval_seconds,
                    },
                )
            )
    elif frame.action in ("Heartbeat", "StatusNotification"):
        try:
            if any(value is None for value in frame.payload.values()):
                raise ValueError("Null property")
            if frame.action == "Heartbeat":
                HeartbeatPayload.model_validate(frame.payload)
                charge_point.status = "online"
                response = encode_frame(
                    Frame(
                        3,
                        frame.message_id,
                        {"currentTime": datetime.now(UTC).isoformat()},
                    )
                )
            else:
                status = StatusPayload.model_validate_json(json.dumps(frame.payload))
                await report_status(session, charge_point, status)
                response = encode_frame(Frame(3, frame.message_id, {}))
        except (ValidationError, ValueError):
            response = error_frame(
                frame.message_id,
                "PropertyConstraintViolation",
                "Invalid monitoring payload",
            )
    elif frame.action in (
        "Authorize",
        "StartTransaction",
        "StopTransaction",
        "MeterValues",
    ):
        try:
            response = encode_frame(
                Frame(
                    3,
                    frame.message_id,
                    await charging_call(session, charge_point, frame),
                )
            )
        except (ValidationError, ValueError):
            response = error_frame(
                frame.message_id,
                "PropertyConstraintViolation",
                "Invalid charging payload",
            )
    else:
        logger.info(
            "ocpp_action_not_implemented charger=%s action=%s",
            charge_point.id,
            frame.action,
        )
        response = error_frame(
            frame.message_id, "NotImplemented", "Action is not implemented"
        )
    session.add(
        OcppMessageReply(
            charge_point_id=charge_point.id,
            message_id=frame.message_id,
            request_hash=digest,
            response=response,
        )
    )
    await session.flush()
    return response


async def dispatch_call(
    connection: OcppConnection, frame: Frame, *, record_seen: bool = False
) -> str:
    previous_boot_state = connection.boot_accepted
    try:
        async with SessionFactory() as session, session.begin():
            response = await process_call(
                connection, frame, session, record_seen=record_seen
            )
    except Exception:
        connection.boot_accepted = previous_boot_state
        raise
    return response


async def prune_replies(session: AsyncSession) -> None:
    await session.execute(
        delete(OcppMessageReply).where(
            OcppMessageReply.created_at < datetime.now(UTC) - timedelta(days=7)
        )
    )
