"""Local OCPP control demo. Reset acknowledges only; no physical reboot."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.client import connect


async def run(
    url: str,
    code: str,
    tag: str | None,
    outcome: str,
    omit_stop: bool,
    existing_transaction_id: int | None = None,
    omit_start: bool = False,
    start_delay: float = 1,
) -> None:
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:
        pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        transaction_id: int | None = existing_transaction_id
        meter_wh = 1000

        async def start_transaction(raw_tag: str, connector_number: int) -> None:
            nonlocal transaction_id
            await asyncio.sleep(start_delay)
            result = await call(
                "StartTransaction",
                {
                    "connectorId": connector_number,
                    "idTag": raw_tag,
                    "meterStart": meter_wh,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            value = result.get("transactionId")
            if isinstance(value, int):
                transaction_id = value
            print(f"Actual StartTransaction: {transaction_id}", flush=True)
            await call(
                "StatusNotification",
                {
                    "connectorId": connector_number,
                    "status": "Charging",
                    "errorCode": "NoError",
                },
            )

        async def call(action: str, payload: dict[str, object]) -> dict[str, object]:
            uid = str(uuid4())
            future: asyncio.Future[dict[str, object]] = (
                asyncio.get_running_loop().create_future()
            )
            pending[uid] = future
            try:
                await socket.send(json.dumps([2, uid, action, payload]))
                return await asyncio.wait_for(future, 30)
            finally:
                pending.pop(uid, None)

        async def stop_transaction() -> None:
            nonlocal transaction_id
            if transaction_id is not None:
                await call(
                    "StopTransaction",
                    {
                        "transactionId": transaction_id,
                        "meterStop": max(3500, meter_wh),
                        "reason": "Remote",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                transaction_id = None
                print("Sent actual StopTransaction, reason Remote.", flush=True)
                await call(
                    "StatusNotification",
                    {"connectorId": 1, "status": "Available", "errorCode": "NoError"},
                )

        stops: set[asyncio.Task[None]] = set()

        async def receive() -> None:
            async for raw in socket:
                frame = json.loads(raw)
                if frame[0] == 3:
                    future = pending.get(frame[1])
                    if future is not None and not future.done():
                        future.set_result(frame[2])
                elif frame[0] == 4:
                    future = pending.get(frame[1])
                    if future is not None and not future.done():
                        future.set_exception(RuntimeError("Charger call rejected"))
                elif frame[0] == 2:
                    action = frame[2]
                    print(f"Received {action}; demo outcome {outcome}.", flush=True)
                    if outcome == "Timeout":
                        continue
                    accepted = (
                        action
                        in ("Reset", "RemoteStopTransaction", "RemoteStartTransaction")
                        and outcome == "Accepted"
                    )
                    if action == "RemoteStopTransaction":
                        accepted = (
                            accepted and frame[3].get("transactionId") == transaction_id
                        )
                    if action == "RemoteStartTransaction":
                        accepted = (
                            accepted
                            and transaction_id is None
                            and frame[3].get("connectorId") == 1
                        )
                    await socket.send(
                        json.dumps(
                            [
                                3,
                                frame[1],
                                {"status": "Accepted" if accepted else "Rejected"},
                            ]
                        )
                    )
                    if accepted and action == "RemoteStopTransaction" and not omit_stop:
                        task = asyncio.create_task(stop_transaction())
                        stops.add(task)
                        task.add_done_callback(stops.discard)
                    if (
                        accepted
                        and action == "RemoteStartTransaction"
                        and not omit_start
                    ):
                        task = asyncio.create_task(
                            start_transaction(
                                frame[3]["idTag"], frame[3]["connectorId"]
                            )
                        )
                        stops.add(task)
                        task.add_done_callback(stops.discard)

        receiver = asyncio.create_task(receive())
        try:
            boot = await call(
                "BootNotification",
                {
                    "chargePointVendor": "CSMS Simulator",
                    "chargePointModel": "Remote control demo",
                },
            )
            if boot.get("status") != "Accepted":
                raise RuntimeError("Boot was not accepted")
            if tag:
                result = await call(
                    "StartTransaction",
                    {
                        "connectorId": 1,
                        "idTag": tag,
                        "meterStart": 1000,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                value = result.get("transactionId")
                if isinstance(value, int):
                    transaction_id = value
                print(f"Demo transaction: {transaction_id}", flush=True)
            await call(
                "StatusNotification",
                {
                    "connectorId": 1,
                    "status": "Charging" if transaction_id is not None else "Available",
                    "errorCode": "NoError",
                },
            )
            print(
                "Ready for operator commands. Reset only acknowledges in this simulator.",
                flush=True,
            )
            while True:
                await call("Heartbeat", {})
                if transaction_id is not None:
                    meter_wh += 50
                    await call(
                        "MeterValues",
                        {
                            "connectorId": 1,
                            "transactionId": transaction_id,
                            "meterValue": [
                                {
                                    "timestamp": datetime.now(UTC).isoformat(),
                                    "sampledValue": [
                                        {"value": str(meter_wh), "unit": "Wh"}
                                    ],
                                }
                            ],
                        },
                    )
                await asyncio.sleep(2)
        finally:
            receiver.cancel()
            for task in stops:
                task.cancel()
            await asyncio.gather(receiver, *stops, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument("--code", required=True)
    parser.add_argument(
        "--transaction-id",
        type=int,
        help="Use an existing open demo transaction instead of starting another",
    )
    parser.add_argument(
        "--id-tag", help="Existing active demo card, maximum 20 characters"
    )
    parser.add_argument(
        "--outcome", choices=["Accepted", "Rejected", "Timeout"], default="Accepted"
    )
    parser.add_argument(
        "--omit-stop",
        action="store_true",
        help="Accept remote stop but omit StopTransaction to test the 2-minute review",
    )
    parser.add_argument(
        "--omit-start",
        action="store_true",
        help="Accept remote start without StartTransaction to test the 60-second wait",
    )
    parser.add_argument(
        "--start-delay",
        type=float,
        default=1,
        help="Delay actual StartTransaction by this many seconds",
    )
    args = parser.parse_args()
    if args.start_delay < 0 or args.start_delay > 120:
        parser.error("--start-delay must be between 0 and 120")
    if args.id_tag and args.transaction_id is not None:
        parser.error("Use either --id-tag or --transaction-id")
    if args.transaction_id is not None and args.transaction_id <= 0:
        parser.error("--transaction-id must be positive")
    asyncio.run(
        run(
            args.url,
            args.code,
            args.id_tag,
            args.outcome,
            args.omit_stop,
            args.transaction_id,
            args.omit_start,
            args.start_delay,
        )
    )
