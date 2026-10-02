"""S-07 tests for OCPP frame codec, dispatch and response matching."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import WebSocket

from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.dispatcher import OcppMessageDispatcher
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
from src.modules.ocpp.pending_calls import OcppCallFailed


def connected_charge_point(code: str = "cp-s07") -> OcppConnection:
    """S-07 builds a connected charge point without using a real socket."""
    return OcppConnection(
        charge_point_id=uuid4(),
        station_id=uuid4(),
        charge_point_code=code,
        station_status="active",
        websocket=cast(WebSocket, AsyncMock(spec=WebSocket)),
        connected_at=datetime.now(UTC),
    )


@pytest.mark.parametrize(
    "frame",
    [
        Call(message_id="call-1", action="Heartbeat", payload={}),
        CallResult(message_id="result-1", payload={"currentTime": "2026-10-02"}),
        CallError(
            message_id="error-1",
            code="SecurityError",
            description="Charge point rejected the request.",
            details={},
        ),
    ],
)
def test_frame_codec_round_trips_each_ocpp_message_type(
    frame: Call | CallResult | CallError,
) -> None:
    assert decode_frame(encode_frame(frame)) == frame


@pytest.mark.parametrize(
    "raw_frame",
    [
        "not-json",
        "{}",
        '[2,"request-1","Heartbeat"]',
        '[2,"request-1",1,{}]',
        '[2,"request-1","Heartbeat",[]]',
        '[3,"result-1",[]]',
        '[4,"error-1","InternalError",1,{}]',
    ],
)
def test_frame_codec_rejects_malformed_frames_with_formation_violation(
    raw_frame: str,
) -> None:
    with pytest.raises(OcppFrameViolation) as error:
        decode_frame(raw_frame)

    assert error.value.code == OcppErrorCode.FORMATION_VIOLATION


@pytest.mark.asyncio
async def test_dispatcher_routes_valid_call_to_registered_handler() -> None:
    dispatcher = OcppMessageDispatcher()
    connection = connected_charge_point()
    received_payloads: list[JsonObject] = []

    async def heartbeat_handler(
        handler_connection: OcppConnection,
        payload: JsonObject,
    ) -> JsonObject:
        assert handler_connection is connection
        received_payloads.append(payload)
        return {"currentTime": "2026-10-02T00:00:00Z"}

    dispatcher.register_handler("Heartbeat", heartbeat_handler)

    response = await dispatcher.handle_text(
        connection,
        '[2,"request-1","Heartbeat",{}]',
    )

    assert response == CallResult(
        message_id="request-1",
        payload={"currentTime": "2026-10-02T00:00:00Z"},
    )
    assert received_payloads == [{}]


@pytest.mark.asyncio
async def test_dispatcher_returns_formation_violation_and_remains_reusable() -> None:
    dispatcher = OcppMessageDispatcher()
    connection = connected_charge_point()

    malformed_response = await dispatcher.handle_text(connection, "not-json")
    unsupported_response = await dispatcher.handle_text(
        connection,
        '[2,"request-2","VendorAction",{}]',
    )

    assert malformed_response == CallError(
        message_id="",
        code=OcppErrorCode.FORMATION_VIOLATION,
        description="Frame must be valid JSON.",
        details={},
    )
    assert unsupported_response == CallError(
        message_id="request-2",
        code=OcppErrorCode.NOT_IMPLEMENTED,
        description="OCPP action is not implemented.",
        details={},
    )


@pytest.mark.asyncio
async def test_dispatcher_logs_not_implemented_action(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = OcppMessageDispatcher()

    await dispatcher.handle_text(
        connected_charge_point("cp-unknown-action"),
        '[2,"request-3","UnknownAction",{}]',
    )

    assert "S-07 OCPP action not implemented" in caplog.text
    assert "UnknownAction" in caplog.text


@pytest.mark.asyncio
async def test_outbound_calls_get_unique_ids_and_match_their_call_result() -> None:
    dispatcher = OcppMessageDispatcher()
    connection = connected_charge_point()
    socket = cast(AsyncMock, connection.websocket)

    first_pending = await dispatcher.send_call(connection, "Reset", {"type": "Soft"})
    second_pending = await dispatcher.send_call(connection, "Reset", {"type": "Hard"})

    first_call = decode_frame(socket.send_text.await_args_list[0].args[0])
    second_call = decode_frame(socket.send_text.await_args_list[1].args[0])
    assert isinstance(first_call, Call)
    assert isinstance(second_call, Call)
    assert first_call.message_id != second_call.message_id

    response = await dispatcher.handle_text(
        connection,
        encode_frame(
            CallResult(
                message_id=second_call.message_id, payload={"status": "Accepted"}
            )
        ),
    )

    assert response is None
    assert not first_pending.done()
    assert await second_pending == CallResult(
        message_id=second_call.message_id,
        payload={"status": "Accepted"},
    )


@pytest.mark.asyncio
async def test_outbound_call_error_fails_only_the_matching_pending_call() -> None:
    dispatcher = OcppMessageDispatcher()
    connection = connected_charge_point()
    socket = cast(AsyncMock, connection.websocket)
    pending = await dispatcher.send_call(connection, "Reset", {"type": "Soft"})
    call = decode_frame(socket.send_text.await_args.args[0])
    assert isinstance(call, Call)

    response = await dispatcher.handle_text(
        connection,
        encode_frame(
            CallError(
                message_id=call.message_id,
                code="SecurityError",
                description="Rejected by charge point.",
                details={},
            )
        ),
    )

    assert response is None
    with pytest.raises(OcppCallFailed, match="SecurityError"):
        await pending


@pytest.mark.asyncio
async def test_dispatcher_logs_unmatched_call_result() -> None:
    dispatcher = OcppMessageDispatcher()

    response = await dispatcher.handle_text(
        connected_charge_point(),
        '[3,"missing-call",{"status":"Accepted"}]',
    )

    assert response is None
