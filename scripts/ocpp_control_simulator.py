"""Local OCPP control demo. Reset acknowledges only; no physical reboot."""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_CEILING
from pathlib import Path
from time import monotonic
from uuid import uuid4

from websockets.asyncio.client import connect


@dataclass
class ConnectorState:
    status: str = "Available"
    transaction_id: int | None = None
    meter_wh: int = 1000
    starting: bool = False
    sample_count: int = 0
    fractional_wh: float = 0
    last_meter_at: float | None = None

    def reserve_start(self) -> bool:
        if (
            self.status not in {"Available", "Preparing"}
            or self.transaction_id is not None
            or self.starting
        ):
            return False
        self.starting = True
        return True


def meter_samples(
    state: ConnectorState, elapsed_seconds: float
) -> list[dict[str, str]]:
    """Simulated telemetry, with energy integrated from the reported power."""
    watts = 7200 + (state.sample_count % 5) * 180
    energy = state.fractional_wh + watts * elapsed_seconds / 3600
    whole_wh = int(energy)
    state.meter_wh += whole_wh
    state.fractional_wh = energy - whole_wh
    samples = [
        {
            "measurand": "Energy.Active.Import.Register",
            "value": str(state.meter_wh),
            "unit": "Wh",
        },
        {"measurand": "Power.Active.Import", "value": str(watts), "unit": "W"},
        {
            "measurand": "Temperature",
            "value": str(36 + (state.sample_count % 8) * 0.25),
            "unit": "Celsius",
        },
        {"measurand": "Voltage", "value": "230", "unit": "V"},
        {
            "measurand": "Current.Import",
            "value": str(round(watts / 230, 2)),
            "unit": "A",
        },
        {
            "measurand": "SoC",
            "value": str(min(90, 40 + state.sample_count // 30)),
            "unit": "Percent",
        },
        {"measurand": "Frequency", "value": "50", "unit": "Hertz"},
    ]
    state.sample_count += 1
    return samples


async def load_connectors(
    code: str, *, dispose_engine: bool = True
) -> dict[int, ConnectorState]:
    """Read registered connectors and resume their open demo sessions, never seed DB."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sqlalchemy import text

    from src.platform.database.session import SessionFactory, engine

    try:
        async with SessionFactory() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                SELECT c.connector_number, c.status, s.id AS transaction_id,
                       GREATEST(s.meter_start_wh, COALESCE((
                           SELECT m.value FROM charging_meter_samples m
                           WHERE m.session_id = s.id
                             AND m.measurand = 'Energy.Active.Import.Register'
                             AND m.unit = 'Wh' AND m.phase = '' AND m.location = 'Outlet'
                           ORDER BY m.timestamp DESC LIMIT 1
                       ), s.meter_start_wh)) AS meter_wh
                FROM charge_points p
                JOIN connectors c ON c.charge_point_id = p.id
                LEFT JOIN charging_sessions s ON s.connector_id = c.id AND s.ended_at IS NULL
                WHERE lower(p.code) = :code AND p.archived_at IS NULL AND c.archived_at IS NULL
                ORDER BY c.connector_number
            """),
                        {"code": code.strip().lower()},
                    )
                )
                .mappings()
                .all()
            )
            if not rows:
                raise ValueError(
                    "No registered connectors found in DATABASE_URL for this charger."
                )
            return {
                row["connector_number"]: ConnectorState(
                    status=row["status"]
                    if row["status"] in {"Faulted", "Reserved", "Unavailable"}
                    else "Charging"
                    if row["transaction_id"] is not None
                    else "Available",
                    transaction_id=row["transaction_id"],
                    meter_wh=int(
                        row["meter_wh"].to_integral_value(rounding=ROUND_CEILING)
                    )
                    if row["meter_wh"] is not None
                    else 1000,
                )
                for row in rows
            }
    finally:
        if dispose_engine:
            await engine.dispose()


async def run(
    url: str,
    code: str,
    tag: str | None,
    outcome: str,
    omit_stop: bool,
    existing_transaction_id: int | None = None,
    omit_start: bool = False,
    start_delay: float = 1,
    connectors: dict[int, ConnectorState] | None = None,
    tag_connector: int = 1,
    stop_event: asyncio.Event | None = None,
) -> None:
    states = connectors if connectors is not None else {1: ConnectorState()}
    if existing_transaction_id is not None:
        if connectors is None:
            states[tag_connector].transaction_id = existing_transaction_id
            states[tag_connector].status = "Charging"
        elif not any(
            s.transaction_id == existing_transaction_id for s in states.values()
        ):
            raise ValueError("The requested transaction is not open on this charger.")
    if tag and tag_connector not in states:
        raise ValueError("The requested card connector is not registered.")
    async with connect(
        f"{url.rstrip('/')}/ocpp/{code}", subprotocols=["ocpp1.6"]
    ) as socket:
        pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        tasks: set[asyncio.Task[None]] = set()
        locks = {n: asyncio.Lock() for n in states}

        async def call(action: str, payload: dict[str, object]) -> dict[str, object]:
            uid = str(uuid4())
            future = asyncio.get_running_loop().create_future()
            pending[uid] = future
            try:
                await socket.send(json.dumps([2, uid, action, payload]))
                return await asyncio.wait_for(future, 30)
            finally:
                pending.pop(uid, None)

        async def report(number: int) -> None:
            state = states[number]
            await call(
                "StatusNotification",
                {
                    "connectorId": number,
                    "status": state.status,
                    "errorCode": "OtherError"
                    if state.status == "Faulted"
                    else "NoError",
                },
            )

        async def stop_transaction(number: int, reason: str = "Remote") -> None:
            async with locks[number]:
                state = states[number]
                if state.transaction_id is None:
                    return
                await call(
                    "StopTransaction",
                    {
                        "transactionId": state.transaction_id,
                        "meterStop": state.meter_wh,
                        "reason": reason,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                state.transaction_id = None
                state.status = "Available"
                await report(number)
                print(
                    f"Connector {number}: actual StopTransaction ({reason}).",
                    flush=True,
                )

        async def start_transaction(raw_tag: str, number: int) -> None:
            state = states[number]
            try:
                await asyncio.sleep(start_delay)
                async with locks[number]:
                    result = await call(
                        "StartTransaction",
                        {
                            "connectorId": number,
                            "idTag": raw_tag,
                            "meterStart": state.meter_wh,
                            "timestamp": datetime.now(UTC).isoformat(),
                        },
                    )
                    value = result.get("transactionId")
                    if not isinstance(value, int):
                        raise TypeError("StartTransaction returned no transaction ID")
                    state.transaction_id = value
                    authorized = result.get("idTagInfo", {}).get("status") == "Accepted"
                    if authorized:
                        state.status = "Charging"
                        state.last_meter_at = monotonic()
                        await report(number)
                        print(
                            f"Connector {number}: actual StartTransaction {value}.",
                            flush=True,
                        )
                if not authorized:
                    await stop_transaction(number, "DeAuthorized")
            finally:
                state.starting = False

        def schedule(task: asyncio.Task[None]) -> None:
            tasks.add(task)

            def completed(done: asyncio.Task[None]) -> None:
                tasks.discard(done)
                if not done.cancelled() and done.exception() is not None:
                    print(
                        "Simulator command failed; inspect charger/session state.",
                        flush=True,
                    )

            task.add_done_callback(completed)

        async def receive() -> None:
            async for raw in socket:
                frame = json.loads(raw)
                if frame[0] in {3, 4}:
                    future = pending.get(frame[1])
                    if future is not None and not future.done():
                        if frame[0] == 3:
                            future.set_result(frame[2])
                        else:
                            future.set_exception(RuntimeError("Charger call rejected"))
                elif frame[0] == 2:
                    action, payload = frame[2:4]
                    if outcome == "Timeout":
                        continue
                    number = payload.get("connectorId")
                    stop_number = next(
                        (
                            n
                            for n, s in states.items()
                            if s.transaction_id is not None
                            and s.transaction_id == payload.get("transactionId")
                        ),
                        None,
                    )
                    accepted = outcome == "Accepted" and (
                        action == "Reset"
                        or (
                            action == "RemoteStopTransaction"
                            and stop_number is not None
                        )
                    )
                    if action == "RemoteStartTransaction":
                        accepted = (
                            outcome == "Accepted"
                            and type(number) is int
                            and number in states
                            and states[number].reserve_start()
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
                    print(
                        f"Received {action}, connector {number or stop_number}: {'Accepted' if accepted else 'Rejected'}.",
                        flush=True,
                    )
                    if accepted and action == "RemoteStopTransaction" and not omit_stop:
                        schedule(asyncio.create_task(stop_transaction(stop_number)))
                    if accepted and action == "RemoteStartTransaction":
                        if omit_start:

                            async def release(number: int) -> None:
                                await asyncio.sleep(60)
                                states[number].starting = False

                            schedule(asyncio.create_task(release(number)))
                        else:
                            schedule(
                                asyncio.create_task(
                                    start_transaction(payload["idTag"], number)
                                )
                            )

        receiver = asyncio.create_task(receive())
        try:
            boot = await call(
                "BootNotification",
                {
                    "chargePointVendor": "CSMS Simulator",
                    "chargePointModel": "Multi-connector demo",
                },
            )
            if boot.get("status") != "Accepted":
                raise RuntimeError("Boot was not accepted")
            for number in states:
                await report(number)
            if tag:
                if not states[tag_connector].reserve_start():
                    raise ValueError("Card connector is busy or not ready.")
                await start_transaction(tag, tag_connector)
            print(
                f"Ready: registered connectors {sorted(states)}. Reset only acknowledges.",
                flush=True,
            )
            while stop_event is None or not stop_event.is_set():
                await call("Heartbeat", {})
                for number, state in states.items():
                    async with locks[number]:
                        if state.transaction_id is None or state.status != "Charging":
                            continue
                        now = monotonic()
                        elapsed = (
                            now - state.last_meter_at
                            if state.last_meter_at is not None
                            else 2
                        )
                        state.last_meter_at = now
                        samples = meter_samples(state, elapsed)
                        await call(
                            "MeterValues",
                            {
                                "connectorId": number,
                                "transactionId": state.transaction_id,
                                "meterValue": [
                                    {
                                        "timestamp": datetime.now(UTC).isoformat(),
                                        "sampledValue": samples,
                                    }
                                ],
                            },
                        )
                if stop_event is None:
                    await asyncio.sleep(2)
                else:
                    try:
                        await asyncio.wait_for(stop_event.wait(), 2)
                    except TimeoutError:
                        pass
            if tasks:
                await asyncio.gather(*tasks)
            for number in states:
                await stop_transaction(number, "Local")
        finally:
            receiver.cancel()
            for task in list(tasks):
                task.cancel()
            await asyncio.gather(receiver, *tasks, return_exceptions=True)


async def main(args: argparse.Namespace) -> None:
    connectors = await load_connectors(args.code)
    await run(
        args.url,
        args.code,
        args.id_tag,
        args.outcome,
        args.omit_stop,
        args.transaction_id,
        args.omit_start,
        args.start_delay,
        connectors,
        args.connector,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument("--code", required=True)
    parser.add_argument(
        "--connector",
        type=int,
        default=1,
        help="Connector for --id-tag; remote starts use the selected registered connector",
    )
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
    if args.connector < 1:
        parser.error("--connector must be positive")
    try:
        if sys.platform == "win32":
            import selectors

            asyncio.run(
                main(args),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        else:
            asyncio.run(main(args))
    except KeyboardInterrupt:
        print("Simulator disconnected. Active sessions need StopTransaction to finish.")
