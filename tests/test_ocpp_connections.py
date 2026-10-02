"""S-06 tests for OCPP WebSocket admission and connection replacement."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import WebSocket

from src.modules.ocpp import router as ocpp_router
from src.modules.ocpp.connection_registry import (
    OcppConnection,
    OcppConnectionRegistry,
)
from src.modules.ocpp.messages import CallError, OcppErrorCode, encode_frame
from src.modules.ocpp.repository import RegisteredChargePoint


def mock_websocket(
    subprotocols: list[str],
    *,
    received_message: dict[str, str] | None = None,
) -> AsyncMock:
    websocket = AsyncMock(spec=WebSocket)
    websocket.scope = {"subprotocols": subprotocols}
    websocket.client = MagicMock(host="127.0.0.1")
    websocket.receive.return_value = received_message or {
        "type": "websocket.disconnect"
    }
    return websocket


def registered_charge_point(status: str = "active") -> RegisteredChargePoint:
    return RegisteredChargePoint(
        charge_point_id=uuid4(),
        station_id=uuid4(),
        station_status=status,
    )


@pytest.mark.asyncio
async def test_rejects_missing_ocpp_subprotocol_before_registration_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = AsyncMock()
    monkeypatch.setattr(ocpp_router, "find_registered_charge_point", lookup)
    websocket = mock_websocket(["unsupported.protocol"])

    await ocpp_router.connect_charge_point(cast(WebSocket, websocket), "CP-01")

    websocket.close.assert_awaited_once_with()
    websocket.accept.assert_not_awaited()
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepts_registered_charge_point_with_offered_ocpp_subprotocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = registered_charge_point()
    lookup = AsyncMock(return_value=registration)
    registry = OcppConnectionRegistry()
    monkeypatch.setattr(ocpp_router, "find_registered_charge_point", lookup)
    monkeypatch.setattr(ocpp_router, "ocpp_connections", registry)
    websocket = mock_websocket(["unsupported.protocol", "ocpp1.6"])

    await ocpp_router.connect_charge_point(cast(WebSocket, websocket), "  CP-01  ")

    lookup.assert_awaited_once_with("cp-01")
    websocket.accept.assert_awaited_once_with(subprotocol="ocpp1.6")
    assert await registry.get("cp-01") is None


@pytest.mark.asyncio
async def test_suspended_station_connects_but_cannot_start_a_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = registered_charge_point("suspended")
    registry = OcppConnectionRegistry()
    replace_connection = AsyncMock(wraps=registry.replace)
    monkeypatch.setattr(
        ocpp_router,
        "find_registered_charge_point",
        AsyncMock(return_value=registration),
    )
    monkeypatch.setattr(ocpp_router, "ocpp_connections", registry)
    monkeypatch.setattr(registry, "replace", replace_connection)
    websocket = mock_websocket(["ocpp1.6"])

    await ocpp_router.connect_charge_point(cast(WebSocket, websocket), "CP-02")

    websocket.accept.assert_awaited_once_with(subprotocol="ocpp1.6")
    replace_connection.assert_awaited_once()
    connection = replace_connection.await_args.args[0]
    assert isinstance(connection, OcppConnection)
    assert not connection.can_start_session
    assert await registry.get("cp-02") is None


@pytest.mark.asyncio
async def test_rejects_unknown_charge_point_before_accept_and_logs_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = OcppConnectionRegistry()
    monkeypatch.setattr(
        ocpp_router, "find_registered_charge_point", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(ocpp_router, "ocpp_connections", registry)
    websocket = mock_websocket(["ocpp1.6"])

    await ocpp_router.connect_charge_point(cast(WebSocket, websocket), "CP-UNKNOWN")

    websocket.close.assert_awaited_once_with()
    websocket.accept.assert_not_awaited()
    assert "S-06 rejected unknown charge point" in caplog.text
    assert "127.0.0.1" in caplog.text
    assert "correlation_id=" in caplog.text


@pytest.mark.asyncio
async def test_replacing_connection_closes_old_socket_and_keeps_new_socket() -> None:
    registry = OcppConnectionRegistry()
    old_socket = AsyncMock(spec=WebSocket)
    new_socket = AsyncMock(spec=WebSocket)
    old_connection = OcppConnection(
        charge_point_id=uuid4(),
        station_id=uuid4(),
        charge_point_code="cp-03",
        station_status="active",
        websocket=cast(WebSocket, old_socket),
        connected_at=datetime.now(UTC),
    )
    new_connection = OcppConnection(
        charge_point_id=old_connection.charge_point_id,
        station_id=old_connection.station_id,
        charge_point_code="cp-03",
        station_status="active",
        websocket=cast(WebSocket, new_socket),
        connected_at=datetime.now(UTC),
    )

    await registry.replace(old_connection)
    await registry.replace(new_connection)
    await registry.remove("cp-03", cast(WebSocket, old_socket))

    old_socket.close.assert_awaited_once_with(
        code=1000,
        reason="Replaced by a newer charge point connection.",
    )
    assert await registry.get("cp-03") is new_connection


@pytest.mark.asyncio
async def test_active_station_can_start_a_session() -> None:
    connection = OcppConnection(
        charge_point_id=uuid4(),
        station_id=uuid4(),
        charge_point_code="cp-04",
        station_status="active",
        websocket=cast(WebSocket, AsyncMock(spec=WebSocket)),
        connected_at=datetime.now(UTC),
    )

    assert connection.can_start_session


@pytest.mark.asyncio
async def test_websocket_sends_s07_error_and_keeps_reading_later_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-07 keeps an accepted socket open after a malformed OCPP frame."""
    registry = OcppConnectionRegistry()
    dispatcher = MagicMock()
    malformed_response = CallError(
        message_id="",
        code=OcppErrorCode.FORMATION_VIOLATION,
        description="Frame must be valid JSON.",
        details={},
    )
    dispatcher.handle_text = AsyncMock(side_effect=[malformed_response, None])
    monkeypatch.setattr(
        ocpp_router,
        "find_registered_charge_point",
        AsyncMock(return_value=registered_charge_point()),
    )
    monkeypatch.setattr(ocpp_router, "ocpp_connections", registry)
    monkeypatch.setattr(ocpp_router, "ocpp_dispatcher", dispatcher)
    websocket = mock_websocket(["ocpp1.6"])
    websocket.receive.side_effect = [
        {"type": "websocket.receive", "text": "not-json"},
        {"type": "websocket.receive", "text": '[2,"request-1","Heartbeat",{}]'},
        {"type": "websocket.disconnect"},
    ]

    await ocpp_router.connect_charge_point(cast(WebSocket, websocket), "CP-05")

    assert dispatcher.handle_text.await_count == 2
    websocket.send_text.assert_awaited_once_with(encode_frame(malformed_response))
