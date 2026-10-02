"""Frame handling stays bound to its original socket, including late replies."""

import logging

from sqlalchemy.exc import SQLAlchemyError

from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.dispatcher import dispatch_call
from src.modules.ocpp.frames import FrameError, decode_frame, error_frame
from src.modules.ocpp.monitoring import mark_seen
from src.platform.database.session import SessionFactory

logger = logging.getLogger("csms.ocpp")


async def record_contact(connection: OcppConnection) -> None:
    async with SessionFactory() as session, session.begin():
        await mark_seen(session, connection.charge_point_id)


async def record_contact_or_error(connection: OcppConnection) -> bool:
    try:
        await record_contact(connection)
    except SQLAlchemyError:
        logger.error(
            "ocpp_contact_update_failed charger=%s", connection.charge_point_id
        )
        await connection.send(
            error_frame("", "InternalError", "Unable to record contact")
        )
        return False
    return True


async def handle_message(connection: OcppConnection, raw: str) -> None:
    # CALL contact and business changes share one transaction and one charger lock.
    # Replies, malformed and oversized frames still record contact independently.
    if len(raw) > 65536:
        if not await record_contact_or_error(connection):
            return
        await connection.send(
            error_frame("", "FormationViolation", "Frame exceeds maximum size")
        )
        return
    try:
        frame = decode_frame(raw)
    except FrameError as error:
        if not await record_contact_or_error(connection):
            return
        await connection.send(
            error_frame(error.message_id, error.code, error.description)
        )
        return
    if frame.kind in (3, 4):
        if not await record_contact_or_error(connection):
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
    await connection.send(response)
