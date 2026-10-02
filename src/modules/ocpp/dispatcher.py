"""S-07 route parsed OCPP frames to handlers and pending outbound calls."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from uuid import uuid4

from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.messages import (
    Call,
    CallError,
    CallResult,
    JsonObject,
    OcppErrorCode,
    OcppFrameViolation,
    decode_frame,
    encode_frame,
)
from src.modules.ocpp.pending_calls import PendingCallRegistry

OcppActionHandler = Callable[[OcppConnection, JsonObject], Awaitable[JsonObject]]

_logger = logging.getLogger("csms.ocpp")


class OcppMessageDispatcher:
    """S-07 shared OCPP frame router; business handlers register by action name."""

    def __init__(self, pending_calls: PendingCallRegistry | None = None) -> None:
        self._handlers: dict[str, OcppActionHandler] = {}
        self._pending_calls = pending_calls or PendingCallRegistry()

    def register_handler(self, action: str, handler: OcppActionHandler) -> None:
        """Register one S-07+ action handler without exposing raw JSON to it."""
        if not action:
            raise ValueError("OCPP action must not be empty.")
        self._handlers[action] = handler

    async def handle_text(
        self,
        connection: OcppConnection,
        raw_text: str,
    ) -> CallResult | CallError | None:
        """Decode an inbound text frame and return a response only when required."""
        try:
            frame = decode_frame(raw_text)
        except OcppFrameViolation as error:
            _logger.warning(
                "S-07 rejected malformed OCPP frame charge_point_code=%s "
                "message_id=%s code=%s",
                connection.charge_point_code,
                error.message_id,
                error.code,
            )
            return error.as_call_error()

        if isinstance(frame, Call):
            return await self._dispatch_call(connection, frame)
        if isinstance(frame, CallResult):
            await self._resolve_call_result(connection, frame)
            return None
        await self._resolve_call_error(connection, frame)
        return None

    async def send_call(
        self,
        connection: OcppConnection,
        action: str,
        payload: JsonObject,
    ) -> asyncio.Future[CallResult]:
        """Send a S-07 CALL with a unique ID stored before socket I/O begins."""
        if not action:
            raise ValueError("OCPP action must not be empty.")

        while True:
            message_id = str(uuid4())
            try:
                response = await self._pending_calls.add(message_id)
                break
            except ValueError:
                # UUID collision is exceptionally unlikely, but must not reuse an ID.
                continue

        try:
            await connection.websocket.send_text(
                encode_frame(
                    Call(message_id=message_id, action=action, payload=payload)
                )
            )
        except Exception:
            await self._pending_calls.discard(message_id)
            raise
        return response

    async def _dispatch_call(
        self,
        connection: OcppConnection,
        call: Call,
    ) -> CallResult | CallError:
        handler = self._handlers.get(call.action)
        if handler is None:
            _logger.warning(
                "S-07 OCPP action not implemented charge_point_code=%s "
                "message_id=%s action=%s",
                connection.charge_point_code,
                call.message_id,
                call.action,
            )
            return CallError(
                message_id=call.message_id,
                code=OcppErrorCode.NOT_IMPLEMENTED,
                description="OCPP action is not implemented.",
                details={},
            )

        try:
            response_payload = await handler(connection, call.payload)
        except Exception:
            _logger.exception(
                "S-07 OCPP handler failed charge_point_code=%s message_id=%s action=%s",
                connection.charge_point_code,
                call.message_id,
                call.action,
            )
            return CallError(
                message_id=call.message_id,
                code=OcppErrorCode.INTERNAL_ERROR,
                description="OCPP action could not be processed.",
                details={},
            )
        return CallResult(message_id=call.message_id, payload=response_payload)

    async def _resolve_call_result(
        self,
        connection: OcppConnection,
        result: CallResult,
    ) -> None:
        if not await self._pending_calls.resolve(result):
            _logger.warning(
                "S-07 unmatched OCPP CALLRESULT charge_point_code=%s message_id=%s",
                connection.charge_point_code,
                result.message_id,
            )

    async def _resolve_call_error(
        self,
        connection: OcppConnection,
        error: CallError,
    ) -> None:
        if not await self._pending_calls.reject(error):
            _logger.warning(
                "S-07 unmatched OCPP CALLERROR charge_point_code=%s message_id=%s",
                connection.charge_point_code,
                error.message_id,
            )


ocpp_dispatcher = OcppMessageDispatcher()
