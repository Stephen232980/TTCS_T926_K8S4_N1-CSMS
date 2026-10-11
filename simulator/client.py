"""S-26: OCPP 1.6J virtual chargers for online and recovery Compose scenarios."""

from __future__ import annotations

import asyncio
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException
from websockets.typing import Subprotocol

from simulator.config import SimulatorSettings, load_settings
from simulator.reporting import begin_run, write_report

METER_START_WH = 1000
METER_STOP_WH = 3500
EXPECTED_ENERGY_KWH = "2.5"


async def run(settings: SimulatorSettings) -> None:
    """Run the configured S-26 scenario and persist its safe verification report."""
    run_id = begin_run(settings.report_path)
    if settings.scenario == "online":
        await _run_online(settings, run_id)
    else:
        await _run_recovery(settings, run_id)


async def _run_online(settings: SimulatorSettings, run_id: str) -> None:
    connections = await asyncio.gather(
        *(_connect_and_boot(settings, index) for index in range(1, settings.count + 1)),
        return_exceptions=True,
    )
    sockets: list[ClientConnection] = []
    results: list[dict[str, Any]] = []
    for index, connection in enumerate(connections, start=1):
        code = settings.code_for(index)
        if isinstance(connection, BaseException):
            results.append({"code": code, "error": str(connection)})
        else:
            socket, _ = connection
            sockets.append(socket)
            results.append({"code": code, "online": True})
    _write_report(settings, results, run_id)
    if len(sockets) != settings.count:
        await _close_all(sockets)
        raise RuntimeError("One or more virtual chargers could not connect")
    try:
        await _keep_connected(sockets, settings)
    finally:
        await _close_all(sockets)


async def _run_recovery(settings: SimulatorSettings, run_id: str) -> None:
    started_at = monotonic()
    results = await asyncio.gather(
        *(_recovery_charger(settings, index) for index in range(1, settings.count + 1)),
        return_exceptions=True,
    )
    sockets: list[ClientConnection] = []
    report_rows: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        code = settings.code_for(index)
        if isinstance(result, BaseException):
            report_rows.append({"code": code, "error": str(result)})
        else:
            row, socket = result
            report_rows.append(row)
            sockets.append(socket)
    _write_report(settings, report_rows, run_id, started_at)
    if len(sockets) != settings.count:
        await _close_all(sockets)
        raise RuntimeError("One or more virtual recovery scenarios failed")
    try:
        await _keep_connected(sockets, settings)
    finally:
        await _close_all(sockets)


async def _recovery_charger(
    settings: SimulatorSettings, index: int
) -> tuple[dict[str, Any], ClientConnection]:
    code = settings.code_for(index)
    tag = settings.tag_for(index)
    socket, _ = await _connect_and_boot(settings, index)
    try:
        authorization = await _call(socket, "Authorize", {"idTag": tag})
        if _field(authorization, "idTagInfo", "status") != "Accepted":
            raise RuntimeError("Simulator authorization was not accepted")
        timestamp = datetime.now(UTC) - timedelta(minutes=1)
        start_message_id = str(uuid4())
        start_payload = {
            "connectorId": 1,
            "idTag": tag,
            "meterStart": METER_START_WH,
            "timestamp": timestamp.isoformat(),
        }
        started = await _call(
            socket, "StartTransaction", start_payload, start_message_id
        )
        transaction_id = started.get("transactionId")
        if type(transaction_id) is not int:
            raise RuntimeError(
                "StartTransaction did not return an integer transactionId"
            )
        await _status(socket, "Charging")
        reconnects = random.Random(settings.seed + index).randint(
            1, settings.max_reconnects
        )
        for reconnect in range(1, reconnects + 1):
            await socket.close()
            socket, _ = await _connect_and_boot(settings, index)
            replay = await _call(
                socket, "StartTransaction", start_payload, start_message_id
            )
            if replay.get("transactionId") != transaction_id:
                raise RuntimeError("StartTransaction replay changed transactionId")
            await _status(socket, "Charging")
            await _meter(
                socket,
                transaction_id,
                timestamp + timedelta(seconds=reconnect * 10),
                METER_START_WH + reconnect * 500,
            )
        await _meter(socket, transaction_id, timestamp + timedelta(seconds=40), 3000)
        stop_message_id = str(uuid4())
        stop_payload = {
            "transactionId": transaction_id,
            "meterStop": METER_STOP_WH,
            "timestamp": (timestamp + timedelta(seconds=50)).isoformat(),
            "reason": "Local",
        }
        await _call(socket, "StopTransaction", stop_payload, stop_message_id)
        await _call(socket, "StopTransaction", stop_payload, stop_message_id)
        await _status(socket, "Available")
        return (
            {
                "code": code,
                "transaction_id": transaction_id,
                "expected_meter_stop_wh": METER_STOP_WH,
                "expected_energy_kwh": EXPECTED_ENERGY_KWH,
                "reconnects": reconnects,
            },
            socket,
        )
    except BaseException:
        await socket.close()
        raise


async def _connect_and_boot(
    settings: SimulatorSettings, index: int
) -> tuple[ClientConnection, int]:
    url = f"{settings.ocpp_url}/ocpp/{settings.code_for(index)}"
    last_error: Exception | None = None
    for _ in range(12):
        try:
            socket = await connect(
                url,
                subprotocols=[Subprotocol("ocpp1.6")],
                open_timeout=5,
            )
        except (OSError, TimeoutError, WebSocketException) as error:
            last_error = error
            await asyncio.sleep(1)
            continue
        reply = await _call(
            socket,
            "BootNotification",
            {
                "chargePointVendor": "CSMS S-26 Simulator",
                "chargePointModel": "Compose Fleet",
                "firmwareVersion": "s26",
            },
        )
        if reply.get("status") != "Accepted":
            await socket.close()
            raise RuntimeError("BootNotification was not accepted")
        interval = reply.get("interval")
        if type(interval) is not int or interval <= 0:
            await socket.close()
            raise RuntimeError("BootNotification did not return a valid interval")
        return socket, interval
    raise RuntimeError(
        f"Could not connect virtual charger {settings.code_for(index)}"
    ) from last_error


async def _call(
    socket: ClientConnection,
    action: str,
    payload: dict[str, Any],
    message_id: str | None = None,
) -> dict[str, Any]:
    call_id = message_id or str(uuid4())
    await socket.send(json.dumps([2, call_id, action, payload], separators=(",", ":")))
    raw = await asyncio.wait_for(socket.recv(), timeout=20)
    if not isinstance(raw, str):
        raise TypeError(f"{action} received a binary response")
    response = json.loads(raw)
    if not isinstance(response, list) or len(response) < 3 or response[1] != call_id:
        raise RuntimeError(f"{action} received an unmatched OCPP response")
    if response[0] == 4:
        raise RuntimeError(f"{action} received CALLERROR {response[2]}")
    if response[0] != 3 or not isinstance(response[2], dict):
        raise RuntimeError(f"{action} received an invalid OCPP response")
    return response[2]


async def _status(socket: ClientConnection, status: str) -> None:
    await _call(
        socket,
        "StatusNotification",
        {"connectorId": 1, "status": status, "errorCode": "NoError"},
    )


async def _meter(
    socket: ClientConnection, transaction_id: int, timestamp: datetime, value: int
) -> None:
    await _call(
        socket,
        "MeterValues",
        {
            "connectorId": 1,
            "transactionId": transaction_id,
            "meterValue": [
                {
                    "timestamp": timestamp.isoformat(),
                    "sampledValue": [{"value": str(value), "unit": "Wh"}],
                }
            ],
        },
    )


async def _keep_connected(
    sockets: list[ClientConnection], settings: SimulatorSettings
) -> None:
    deadline = (
        None if settings.hold_seconds == 0 else monotonic() + settings.hold_seconds
    )
    while deadline is None or monotonic() < deadline:
        await asyncio.gather(*(_call(socket, "Heartbeat", {}) for socket in sockets))
        await asyncio.sleep(settings.heartbeat_seconds)


async def _close_all(sockets: list[ClientConnection]) -> None:
    await asyncio.gather(
        *(socket.close() for socket in sockets), return_exceptions=True
    )


def _field(value: dict[str, Any], parent: str, child: str) -> Any:
    nested = value.get(parent)
    return nested.get(child) if isinstance(nested, dict) else None


def _write_report(
    settings: SimulatorSettings,
    rows: list[dict[str, Any]],
    run_id: str,
    started_at: float | None = None,
) -> None:
    elapsed = None if started_at is None else round(monotonic() - started_at, 3)
    write_report(
        settings.report_path,
        {
            "run_id": run_id,
            "scenario": settings.scenario,
            "count": settings.count,
            "elapsed_seconds": elapsed,
            "chargers": rows,
        },
    )


def main() -> None:
    """Run the S-26 command-line simulator and return a failing process status."""
    try:
        asyncio.run(run(load_settings()))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"S-26 simulator failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
