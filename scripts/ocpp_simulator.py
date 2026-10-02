"""Minimal real WebSocket charger for the OCPP foundation demo."""

import argparse
import asyncio
import json
from uuid import uuid4

from websockets.asyncio.client import connect


async def run(url: str, code: str, hold: int, message_id: str) -> None:
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:
        boot = json.dumps(
            [
                2,
                message_id,
                "BootNotification",
                {
                    "chargePointVendor": "CSMS Simulator",
                    "chargePointModel": "Demo 1.6J",
                    "firmwareVersion": "1.0",
                },
            ]
        )
        await socket.send(boot)
        first = await socket.recv()
        print("Boot reply:", first, flush=True)
        await socket.send(boot)
        assert await socket.recv() == first, "Duplicate Boot reply changed"
        print("Duplicate replay verified; connection stays open.", flush=True)
        await asyncio.sleep(hold)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument(
        "--code", required=True, help="Previously registered charger code"
    )
    parser.add_argument("--hold", type=int, default=600)
    parser.add_argument("--message-id", default=str(uuid4()))
    args = parser.parse_args()
    asyncio.run(run(args.url, args.code, args.hold, args.message_id))
