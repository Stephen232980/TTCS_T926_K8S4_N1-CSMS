"""Registered charger WebSocket endpoint. S-06 owns connection admission."""

import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, WebSocket

from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.identity.policy_routing import PolicyRoute
from src.modules.ocpp.connection_registry import OcppConnection, ocpp_connections
from src.modules.ocpp.frames import error_frame
from src.modules.ocpp.service import find_registered_charge_point
from src.modules.ocpp.transport import handle_message, record_contact

OCPP_SUBPROTOCOL = "ocpp1.6"


router = APIRouter(route_class=PolicyRoute, tags=["OCPP"])
_logger = logging.getLogger("csms.ocpp")


@router.websocket("/ocpp/{charge_point_code}")
@access_policy(
    AccessPolicy(
        "device",
        note="S-06 registered charger and OCPP subprotocol admission; S-08 Boot authorization",
    )
)
async def connect_charge_point(websocket: WebSocket, charge_point_code: str) -> None:
    """Accept registered charge points and keep their WebSocket open."""
    # S-06: only accept if the client offered the exact OCPP 1.6J subprotocol.
    offered_subprotocols = set(websocket.scope.get("subprotocols") or [])
    if OCPP_SUBPROTOCOL not in offered_subprotocols:
        await websocket.close()
        return

    normalized_code = charge_point_code.strip().lower()
    charge_point = await find_registered_charge_point(normalized_code)

    if charge_point is None:
        # S-06/T-13: record enough context to investigate an unknown charger.
        correlation_id = str(uuid4())
        remote_ip = websocket.client.host if websocket.client is not None else "unknown"
        occurred_at = datetime.now(UTC).isoformat()
        _logger.warning(
            "S-06 rejected unknown charge point code=%r remote_ip=%s "
            "occurred_at=%s correlation_id=%s",
            charge_point_code,
            remote_ip,
            occurred_at,
            correlation_id,
        )
        # Closing before accept rejects the HTTP upgrade; no OCPP frame is sent.
        await websocket.close()
        return

    connection = OcppConnection(
        charge_point_id=charge_point.charge_point_id,
        station_id=charge_point.station_id,
        charge_point_code=normalized_code,
        station_status=charge_point.station_status,
        websocket=websocket,
        connected_at=datetime.now(UTC),
    )

    # S-06: suspended/non-active stations connect for status reporting only.
    await websocket.accept(subprotocol=OCPP_SUBPROTOCOL)
    try:
        await ocpp_connections.replace(connection)
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if raw is None:
                await record_contact(connection)
                await connection.send(
                    error_frame("", "FormationViolation", "OCPP requires text frames")
                )
            else:
                await handle_message(connection, raw)
    except (OSError, RuntimeError):
        # Replacement/disconnection can race a response to the original socket.
        pass
    finally:
        connection.cancel_pending()
        await ocpp_connections.remove(normalized_code, websocket)
