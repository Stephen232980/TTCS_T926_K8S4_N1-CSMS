"""Demo an actual OCPP transaction. Set CSMS_SIMULATOR_ID_TAG to a registered tag."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from websockets.asyncio.client import connect


async def run(url: str, code: str, duration: int, regression: bool) -> None:
    tag = os.environ.get("CSMS_SIMULATOR_ID_TAG", "DEMO-CARD-2026")
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:

        async def call(action, payload, uid=None):
            await socket.send(json.dumps([2, uid or str(uuid4()), action, payload]))
            reply = json.loads(await socket.recv())
            if reply[0] != 3:
                raise RuntimeError(f"{action} was rejected: {reply[2]}")
            return reply[2]

        boot = await call(
            "BootNotification",
            {
                "chargePointVendor": "CSMS Simulator",
                "chargePointModel": "Charging 1.6J",
            },
        )
        if boot["status"] != "Accepted":
            raise RuntimeError("Boot was not accepted")
        authorization = await call("Authorize", {"idTag": tag})
        print("Card authorization:", authorization["idTagInfo"]["status"], flush=True)
        payload = {
            "connectorId": 1,
            "idTag": tag,
            "meterStart": 10000,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        uid = str(uuid4())
        started = await call("StartTransaction", payload, uid)
        assert await call("StartTransaction", payload, uid) == started
        transaction_id = started["transactionId"]
        print(
            f"Transaction #{transaction_id}; persistent duplicate replay verified.",
            flush=True,
        )
        await call(
            "StatusNotification",
            {"connectorId": 1, "status": "Charging", "errorCode": "NoError"},
        )
        await call(
            "StopTransaction",
            {
                "transactionId": 2147483647,
                "meterStop": 10000,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        meter = 10000
        counter = 0
        began = monotonic()
        last_report = began - 10
        try:
            while duration == 0 or monotonic() - began < duration:
                await call("Heartbeat", {})
                if monotonic() - last_report >= 10:
                    counter += 1
                    meter += -100 if regression and counter == 3 else 250
                    await call(
                        "MeterValues",
                        {
                            "connectorId": 1,
                            "transactionId": transaction_id,
                            "meterValue": [
                                {
                                    "timestamp": datetime.now(UTC).isoformat(),
                                    "sampledValue": [
                                        {"value": str(meter)},
                                        {
                                            "measurand": "Power.Active.Import",
                                            "value": "7.2",
                                            "unit": "kW",
                                        },
                                    ],
                                }
                            ],
                        },
                    )
                    print(
                        f"Transaction #{transaction_id}: register {meter} Wh",
                        flush=True,
                    )
                    last_report = monotonic()
                await asyncio.sleep(min(2, max(0.5, boot["interval"] / 2)))
        finally:
            await call(
                "StopTransaction",
                {
                    "transactionId": transaction_id,
                    "meterStop": meter,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "reason": "Local",
                },
            )
            await call(
                "StatusNotification",
                {"connectorId": 1, "status": "Available", "errorCode": "NoError"},
            )
            print(
                f"Transaction #{transaction_id} ended; energy {(meter - 10000) / 1000:g} kWh.",
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument("--code", required=True)
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Seconds; 0 keeps charging until Ctrl+C",
    )
    parser.add_argument(
        "--regression",
        action="store_true",
        help="Send one decreasing energy report for review",
    )
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("duration must be zero or positive")
    try:
        asyncio.run(run(args.url, args.code, args.duration, args.regression))
    except KeyboardInterrupt:
        pass
