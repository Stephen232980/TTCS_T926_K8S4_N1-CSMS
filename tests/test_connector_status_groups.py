from datetime import timedelta

import pytest
from sqlalchemy import func, select

from src.modules.identity.authorization import CurrentActor, build_actor_scope
from src.modules.ocpp.dispatcher import process_call
from src.modules.ocpp.frames import Frame, decode_frame
from src.modules.ocpp.monitor_router import MonitorQuery, monitoring_snapshot
from src.modules.ocpp.monitoring import database_time
from src.modules.stations.connector_status import connector_status_group
from src.modules.stations.models import ConnectorError
from src.modules.stations.schemas import ConnectorResponse
from tests.test_ocpp_monitoring import setup_charger

CASES = [
    ("Available", "available"),
    ("Preparing", "occupied"),
    ("Charging", "occupied"),
    ("SuspendedEV", "occupied"),
    ("SuspendedEVSE", "occupied"),
    ("Finishing", "occupied"),
    ("Reserved", "reserved"),
    ("Unavailable", "unavailable"),
    ("Faulted", "faulted"),
]


@pytest.mark.parametrize(
    "status,expected",
    CASES
    + [
        (None, "unknown"),
        ("unknown", "unknown"),
        ("Unknown", "unknown"),
        ("vendor_state", "unknown"),
        ("available", "unknown"),
    ],
)
def test_display_group_preserves_unknown_states(status, expected):
    assert connector_status_group(status) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", CASES)
async def test_status_groups_are_serialized_without_replacing_ocpp_state(
    db_session, status, expected
):
    station, _charger, connector, conn = await setup_charger(db_session)
    reply = decode_frame(
        await process_call(
            conn,
            Frame(
                2,
                "status-group",
                {"connectorId": 1, "status": status, "errorCode": "NoError"},
                action="StatusNotification",
            ),
            db_session,
        )
    )
    assert reply.kind == 3
    await db_session.refresh(connector)
    assert connector.status == connector.raw_ocpp_status == status
    station_payload = ConnectorResponse.model_validate(connector).model_dump(
        mode="json"
    )
    assert station_payload["status"] == status
    assert station_payload["status_group"] == expected
    snapshot = await monitoring_snapshot(
        db_session,
        build_actor_scope(
            CurrentActor(station.owner_id, frozenset({"station_owner"})), "owned"
        ),
        MonitorQuery(),
    )
    payload = snapshot.model_dump(mode="json")["items"][0]["connectors"][0]
    assert payload["status"] == payload["raw_ocpp_status"] == status
    assert payload["status_group"] == expected


@pytest.mark.asyncio
async def test_offline_observation_is_unknown_not_available(db_session):
    station, charger, connector, _ = await setup_charger(db_session)
    charger.last_seen_at = await database_time(db_session) - timedelta(seconds=121)
    await db_session.flush()
    snapshot = await monitoring_snapshot(
        db_session,
        build_actor_scope(
            CurrentActor(station.owner_id, frozenset({"station_owner"})), "owned"
        ),
        MonitorQuery(),
    )
    payload = snapshot.model_dump(mode="json")["items"][0]["connectors"][0]
    assert payload["status"] == payload["status_group"] == "unknown"
    await db_session.refresh(connector)
    assert connector.status == "Available"


@pytest.mark.asyncio
async def test_invalid_status_logs_safe_diagnostic_and_retains_valid_state(
    db_session, caplog
):
    _, charger, connector, conn = await setup_charger(db_session)
    secret = "bad-status\nemail=private@example.com;token=secret-value"
    payload = {
        "connectorId": 1,
        "status": secret,
        "errorCode": "OtherError",
        "info": secret,
    }
    frame = Frame(2, "invalid-status", payload, action="StatusNotification")
    reply = await process_call(conn, frame, db_session)
    assert decode_frame(reply).kind == 4
    assert "ocpp_invalid_status_notification" in caplog.text
    assert str(charger.id) in caplog.text
    assert (
        "private@example.com" not in caplog.text and "secret-value" not in caplog.text
    )
    await db_session.refresh(connector)
    assert connector.status == "Available"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ConnectorError)
            .where(ConnectorError.connector_id == connector.id)
        )
        == 0
    )
    caplog.clear()
    assert await process_call(conn, frame, db_session) == reply
    assert "ocpp_invalid_status_notification" not in caplog.text
