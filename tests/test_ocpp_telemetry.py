from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.modules.ocpp import transport
from src.modules.ocpp.connection_registry import OcppConnection
from src.modules.ocpp.telemetry import TelemetryBuffer

NOW = datetime(2038, 5, 1, 12, 0, tzinfo=UTC)


def test_telemetry_snapshot_ack_preserves_concurrent_updates_and_is_bounded() -> None:
    buffer = TelemetryBuffer(started_at=NOW)
    buffer.record(error=True, latency_ms=5, at=NOW)
    before = buffer.snapshot(NOW)
    buffer.record(error=True, latency_ms=10, at=NOW)
    buffer.acknowledge(before)
    assert buffer.snapshot(NOW)[0].error_count == 2
    buffer.acknowledge(buffer.snapshot(NOW))
    assert buffer.snapshot(NOW) == []
    later = buffer.snapshot(NOW + timedelta(days=10))
    assert len(later) <= 3000
    assert all(b.timestamp >= NOW + timedelta(days=10, hours=-25) for b in later)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,error,latency",
    [
        ('[2,"ok","Heartbeat",{}]', False, True),
        (
            '[2,"fault","StatusNotification",{"errorCode":"HighTemperature"}]',
            True,
            True,
        ),
        ('[4,"command","InternalError","failed",{}]', True, False),
        ("invalid-json", True, False),
    ],
)
async def test_transport_records_actual_exchanges_without_extra_db_writes(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    error: bool,
    latency: bool,
) -> None:
    buffer = TelemetryBuffer()
    connection = OcppConnection(
        uuid4(), uuid4(), "TEST", "active", AsyncMock(), NOW, boot_accepted=True
    )
    monkeypatch.setattr(transport, "ocpp_telemetry", buffer)
    contact = AsyncMock(return_value=True)
    dispatch = AsyncMock(return_value='[3,"ok",{}]')
    monkeypatch.setattr(transport, "record_contact_or_error", contact)
    monkeypatch.setattr(transport, "dispatch_call", dispatch)
    await transport.handle_message(connection, raw)
    buckets = buffer.snapshot(datetime.now(UTC))
    assert sum(b.error_count for b in buckets) == int(error)
    assert sum(b.response_count for b in buckets) == int(latency)
    assert all(b.latency_total_ms >= 0 for b in buckets)
    # Exactly the original contact/business calls; telemetry has no database call.
    assert dispatch.await_count == int(latency)
    assert contact.await_count == int(not latency)
