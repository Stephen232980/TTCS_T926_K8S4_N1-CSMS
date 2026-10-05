"""Frame handling stays bound to its original socket, including late replies."""

import json
import logging
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError

from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.dispatcher import dispatch_call
from src.modules.ocpp.frames import FrameError, decode_frame, error_frame
from src.modules.ocpp.monitoring import mark_seen
from src.modules.ocpp.telemetry import ocpp_telemetry
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.ocpp")


@dataclass
class Exchange:
    started: float
    is_call: bool = False
    error: bool = False
    latency_ms: float | None = None


async def send_reply(
    connection: OcppConnection, raw: str, exchange: Exchange | None
) -> None:
    await connection.send(raw)
    if exchange is not None:
        exchange.error |= json.loads(raw)[0] == 4
        if exchange.is_call:
            exchange.latency_ms = (perf_counter() - exchange.started) * 1000


async def record_contact(connection: OcppConnection) -> None:
    async with SessionFactory() as session, session.begin():
        await mark_seen(session, connection.charge_point_id)


async def record_contact_or_error(
    connection: OcppConnection, exchange: Exchange | None = None
) -> bool:
    try:
        await record_contact(connection)
    except SQLAlchemyError:
        logger.error(
            "ocpp_contact_update_failed charger=%s", connection.charge_point_id
        )
        await send_reply(
            connection,
            error_frame("", "InternalError", "Unable to record contact"),
            exchange,
        )
        return False
    return True


async def handle_message(connection: OcppConnection, raw: str) -> None:
    exchange = Exchange(started=perf_counter())
    try:
        await _handle_message(connection, raw, exchange)
    finally:
        ocpp_telemetry.record(error=exchange.error, latency_ms=exchange.latency_ms)


async def _handle_message(
    connection: OcppConnection, raw: str, exchange: Exchange
) -> None:
    # CALL contact and business changes share one transaction and one charger lock.
    # Replies, malformed and oversized frames still record contact independently.
    if len(raw) > 65536:
        if not await record_contact_or_error(connection, exchange):
            return
        await send_reply(
            connection,
            error_frame("", "FormationViolation", "Frame exceeds maximum size"),
            exchange,
        )
        return
    try:
        frame = decode_frame(raw)
    except FrameError as error:
        if not await record_contact_or_error(connection, exchange):
            return
        await send_reply(
            connection,
            error_frame(error.message_id, error.code, error.description),
            exchange,
        )
        return
    exchange.is_call = frame.kind == 2
    exchange.error = frame.kind == 4 or (
        frame.kind == 2
        and frame.action == "StatusNotification"
        and isinstance(frame.payload.get("errorCode"), str)
        and frame.payload["errorCode"] != "NoError"
    )
    if frame.kind in (3, 4):
        if not await record_contact_or_error(connection, exchange):
            return
        future = connection.pending.get(frame.message_id)
        if future is not None and not future.done():
            future.set_result(frame)
        else:
            logger.warning(
                "ocpp_unmatched_response charger=%s message_id=%s",
                connection.charge_point_id,
                frame.message_id,
            )
        return
    try:
        response = await dispatch_call(connection, frame, record_seen=True)
    except SQLAlchemyError:
        logger.error(
            "ocpp_database_operation_failed charger=%s", connection.charge_point_id
        )
        response = error_frame(
            frame.message_id, "InternalError", "Unable to process request"
        )
    await send_reply(connection, response, exchange)
