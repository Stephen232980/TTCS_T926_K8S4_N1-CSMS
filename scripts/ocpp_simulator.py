"""Registered OCPP charger: Boot replay, optional monitoring and heartbeat demo."""

import argparse
import asyncio
import json
from time import monotonic
from uuid import uuid4

from websockets.asyncio.client import connect


async def run(
    url: str, code: str, hold: int, message_id: str, monitor: bool = False
) -> None:
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:

        async def call(action, payload, uid=None):
            await socket.send(json.dumps([2, uid or str(uuid4()), action, payload]))
            return json.loads(await socket.recv())

        payload = {
            "chargePointVendor": "CSMS Simulator",
            "chargePointModel": "Demo 1.6J",
            "firmwareVersion": "1.0",
        }
        first = await call("BootNotification", payload, message_id)
        print("Boot reply:", json.dumps(first), flush=True)
        assert await call("BootNotification", payload, message_id) == first, (
            "Duplicate Boot reply changed"
        )
        print("Duplicate replay verified; connection stays open.", flush=True)
        if not monitor:
            if hold == 0:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(hold)
                print("Demo duration ended; disconnecting charger.", flush=True)
            return
        if first[0] != 3 or first[2]["status"] != "Accepted":
            raise RuntimeError("Boot was not accepted")
        interval = first[2]["interval"]
        await call(
            "StatusNotification",
            {"connectorId": 0, "status": "Available", "errorCode": "NoError"},
        )
        await call(
            "StatusNotification",
            {"connectorId": 1, "status": "Charging", "errorCode": "NoError"},
        )
        await call(
            "StatusNotification",
            {
                "connectorId": 2,
                "status": "Faulted",
                "errorCode": "GroundFailure",
                "vendorErrorCode": "DEMO-E42",
            },
        )
        print(
            "Monitoring demo: connector 1 Charging; connector 2 Faulted (DEMO-E42).",
            flush=True,
        )
        end = monotonic() + hold
        while hold == 0 or monotonic() < end:
            await call("Heartbeat", {})
            await asyncio.sleep(max(0.5, interval / 2))
        print("Demo duration ended; disconnecting charger.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument(
        "--code", required=True, help="Previously registered charger code"
    )
    parser.add_argument("--hold", type=int, default=600, help="Duration in seconds; 0 runs until stopped")
    parser.add_argument("--message-id", default=str(uuid4()))
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Report declared connectors 1/2 and send heartbeats",
    )
    args = parser.parse_args()
    if args.hold < 0:
        parser.error("--hold must be zero or positive")
    asyncio.run(run(args.url, args.code, args.hold, args.message_id, args.monitor))
