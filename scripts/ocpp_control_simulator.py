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
) -> None:
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:
        pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        transaction_id: int | None = existing_transaction_id

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
            if transaction_id is not None:
                await call(
                    "StopTransaction",
                    {
                        "transactionId": transaction_id,
                        "meterStop": 3500,
                        "reason": "Remote",
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
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
                        action in ("Reset", "RemoteStopTransaction")
                        and outcome == "Accepted"
                    )
                    if action == "RemoteStopTransaction":
                        accepted = (
                            accepted and frame[3].get("transactionId") == transaction_id
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
                await asyncio.sleep(15)
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
    args = parser.parse_args()
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
        )
    )
