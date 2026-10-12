"""T-108 CLI: fresh per-run fixtures, OCPP fleet and settlement reconciliation."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse
from uuid import uuid5

from simulator.t108_contract import RunManifest, new_manifest, readings, save_json


async def run_charger(
    manifest: RunManifest, participant, url: str, directory: Path
) -> dict:
    from websockets.asyncio.client import connect
    from websockets.typing import Subprotocol

    from simulator.client import _call

    path = directory / f"trace-{participant.index:03d}.json"
    samples = readings(manifest)
    trace = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {
            "run_id": str(manifest.run_id),
            "index": participant.index,
            "samples": [{"at": at.isoformat(), "wh": str(wh)} for at, wh in samples],
            "session_id": None,
            "acknowledged": [],
            "completed": False,
        }
    )
    if trace["run_id"] != str(manifest.run_id) or trace["samples"] != [
        {"at": at.isoformat(), "wh": str(wh)} for at, wh in samples
    ]:
        raise ValueError("Trace does not match immutable run input")
    save_json(path, trace)
    async with connect(
        f"{url.rstrip('/')}/ocpp/{participant.charge_point_code}",
        subprotocols=[Subprotocol("ocpp1.6")],
        open_timeout=10,
    ) as socket:

        async def paced_wait(stamp: datetime) -> None:
            if manifest.mode == "staging":
                while (remaining := (stamp - datetime.now(UTC)).total_seconds()) > 0:
                    if remaining > 15:
                        await _call(socket, "Heartbeat", {})
                    await asyncio.sleep(min(15, remaining))

        async def call(action: str, payload: dict, key: str) -> dict:
            trace["last_intent"] = key
            save_json(path, trace)
            result = await _call(
                socket,
                action,
                payload,
                str(uuid5(manifest.run_id, f"{participant.index}:{key}")),
            )
            if key not in trace["acknowledged"]:
                trace["acknowledged"].append(key)
            save_json(path, trace)
            return result

        boot = await _call(
            socket,
            "BootNotification",
            {
                "chargePointVendor": "CSMS T108",
                "chargePointModel": "Virtual acceptance",
            },
        )
        if boot.get("status") != "Accepted":
            raise RuntimeError("Fixture boot refused")
        if trace["session_id"] is None:
            authorization = await _call(
                socket, "Authorize", {"idTag": participant.card_tag}
            )
            if authorization.get("idTagInfo", {}).get("status") != "Accepted":
                raise RuntimeError("Fixture authorization refused")
            if (
                manifest.mode == "staging"
                and datetime.now(UTC) > manifest.started_at
                and trace.get("last_intent") != "start"
            ):
                raise RuntimeError(
                    "Missed scheduled start; use a new run, never alter the tariff"
                )
        if not trace["completed"]:
            await paced_wait(manifest.started_at)
            if "start_delay_seconds" not in trace:
                trace["start_delay_seconds"] = (
                    datetime.now(UTC) - manifest.started_at
                ).total_seconds()
            started = await call(
                "StartTransaction",
                {
                    "connectorId": 1,
                    "idTag": participant.card_tag,
                    "meterStart": 1000,
                    "timestamp": manifest.started_at.isoformat(),
                },
                "start",
            )
            if (
                type(started.get("transactionId")) is not int
                or started.get("idTagInfo", {}).get("status") != "Accepted"
            ):
                raise RuntimeError("Fixture start refused")
            if trace["session_id"] not in {None, started["transactionId"]}:
                raise RuntimeError("Replay changed session identity")
            trace["session_id"] = started["transactionId"]
            save_json(path, trace)
            if "charging" not in trace["acknowledged"]:
                await call(
                    "StatusNotification",
                    {
                        "connectorId": 1,
                        "status": "Charging",
                        "errorCode": "NoError",
                        "timestamp": manifest.started_at.isoformat(),
                    },
                    "charging",
                )
            for index, (stamp, wh) in enumerate(samples[1:-1], 1):
                key = f"meter:{index}"
                if key in trace["acknowledged"]:
                    continue
                await paced_wait(stamp)
                await call(
                    "MeterValues",
                    {
                        "connectorId": 1,
                        "transactionId": trace["session_id"],
                        "meterValue": [
                            {
                                "timestamp": stamp.isoformat(),
                                "sampledValue": [
                                    {
                                        "value": str(wh),
                                        "unit": "Wh",
                                        "measurand": "Energy.Active.Import.Register",
                                        "location": "Outlet",
                                    }
                                ],
                            }
                        ],
                    },
                    key,
                )
            await paced_wait(manifest.ended_at)
        stop = {
            "transactionId": trace["session_id"],
            "meterStop": 1000 + manifest.energy_wh,
            "timestamp": manifest.ended_at.isoformat(),
            "reason": "EVDisconnected",
        }
        await call("StopTransaction", stop, "stop")
        await call("StopTransaction", stop, "stop")
        trace["completed"] = True
        save_json(path, trace)
    return trace


async def execute(
    manifest: RunManifest, url: str, directory: Path, factory, timeout: int
) -> dict:
    from simulator.t108_report import compare, inspect_participant, write_evidence

    results = await asyncio.gather(
        *(run_charger(manifest, p, url, directory) for p in manifest.participants),
        return_exceptions=True,
    )
    errors = [
        p.index
        for p, result in zip(manifest.participants, results, strict=True)
        if isinstance(result, BaseException)
    ]
    if errors:
        save_json(
            directory / "report.json",
            {
                "run_id": str(manifest.run_id),
                "passed": False,
                "environment": manifest.mode,
                "failed_participants": errors,
                "failure": "ocpp_fleet_incomplete",
            },
        )
        raise RuntimeError(
            f"OCPP fleet incomplete at participant(s): {errors}; inspect traces and server logs"
        )
    traces = {
        str(p.index): result
        for p, result in zip(manifest.participants, results, strict=True)
    }
    deadline = monotonic() + timeout
    while True:
        async with factory() as db:
            actual = [
                await inspect_participant(db, manifest, p)
                for p in manifest.participants
            ]
        if all(row.get("settled") for row in actual) or monotonic() >= deadline:
            break
        await asyncio.sleep(1)
    rows = [
        compare(manifest, p, traces[str(p.index)], row)
        for p, row in zip(manifest.participants, actual, strict=True)
    ]
    report = write_evidence(directory, manifest, traces, rows)
    print(
        "Charger | Session | kWh | Expected | Invoice | Before | After | Debits | Result"
    )
    for row in rows:
        actual = row["actual"]
        print(
            f"{row['code']} | {row['session_id']} | {manifest.energy_wh / 1000} | {row['expected_total_vnd']} | {actual.get('total_vnd')} | {row['balance_before_vnd']} | {actual.get('balance_vnd')} | {len(actual.get('debit_amounts', []))} | {'PASS' if row['passed'] else 'FAIL'}"
        )
        for segment in row["expected_segments"]:
            print(
                f"  {segment['started_at']} -> {segment['ended_at']} | {segment['energy_wh']} Wh | {segment['rate_vnd']} VND/kWh | {segment['amount_vnd']} VND"
            )
    return report


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T-108 manifest, OCPP and independent reconciliation"
    )
    parser.add_argument("action", choices=["plan", "run", "cleanup", "verify-suite"])
    parser.add_argument("--output", type=Path, default=Path(".local/t108"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mode", choices=["staging", "ci"], default="staging")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--duration-seconds", type=int, default=360)
    parser.add_argument("--boundary-seconds", type=int, default=180)
    parser.add_argument("--rates", nargs=3, type=int, default=(2000, 3000, 2500))
    parser.add_argument("--amount-vnd", type=int, default=100000)
    parser.add_argument("--energy-wh", type=int, default=2000)
    parser.add_argument("--sample-seconds", type=int, default=30)
    parser.add_argument("--ocpp-url", default="ws://localhost:8000")
    parser.add_argument("--admin-email")
    parser.add_argument("--confirm-test-environment", action="store_true")
    parser.add_argument("--settlement-timeout", type=int, default=60)
    parser.add_argument("--reports", type=Path, nargs="+")
    args = parser.parse_args()
    if args.manifest and any(
        flag in {argument.split("=", 1)[0] for argument in sys.argv[1:]}
        for flag in (
            "--mode",
            "--count",
            "--duration-seconds",
            "--boundary-seconds",
            "--rates",
            "--amount-vnd",
            "--energy-wh",
            "--sample-seconds",
        )
    ):
        parser.error("A saved manifest owns all run configuration; do not override it")
    return args


def verify_suite(paths: list[Path]) -> bool:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    return (
        len(reports) == 3
        and len({r["run_id"] for r in reports}) == 3
        and len({r.get("station_id") for r in reports}) == 3
        and all(
            r.get("staging_acceptance_candidate")
            and r.get("environment") == "staging"
            and r.get("passed") is True
            and r.get("count") == 20
            and len(r.get("rows", [])) == 20
            and {row.get("index") for row in r["rows"]} == set(range(1, 21))
            and len({row.get("code") for row in r["rows"]}) == 20
            and len({row.get("session_id") for row in r["rows"]}) == 20
            and all(row.get("session_id") is not None for row in r["rows"])
            and all(row.get("passed") and not row.get("failures") for row in r["rows"])
            for r in reports
        )
    )


async def main() -> None:
    args = arguments()
    if args.action == "verify-suite":
        if not args.reports or not verify_suite(args.reports):
            raise SystemExit("Three distinct successful staging runs are required")
        print("Three-run evidence suite PASS; TV6 review still required")
        return
    revision = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], text=True
        )
    ).strip()
    if (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "status", "--porcelain"], text=True
        )
    ).strip():
        revision += "+dirty"
    if args.manifest:
        manifest = RunManifest.model_validate_json(
            args.manifest.read_text(encoding="utf-8")
        )
        directory = args.manifest.parent
    else:
        if args.action == "cleanup":
            raise SystemExit("Cleanup requires --manifest")
        manifest = new_manifest(
            revision=revision,
            mode=args.mode,
            count=args.count,
            duration=args.duration_seconds,
            boundary=args.boundary_seconds,
            rates=tuple(args.rates),
            amount=args.amount_vnd,
            energy_wh=args.energy_wh,
            sample_seconds=args.sample_seconds,
        )
        directory = args.output / str(manifest.run_id)
        args.manifest = directory / "manifest.json"
        save_json(args.manifest, manifest.model_dump(mode="json"))
    if args.action == "plan":
        print(f"Plan saved: {args.manifest}; no database connection")
        return
    if (
        not args.confirm_test_environment
        or os.environ.get("T108_ALLOW_TEST_RUN") != "YES"
    ):
        raise SystemExit(
            "Set T108_ALLOW_TEST_RUN=YES and --confirm-test-environment for the verified isolated test environment"
        )
    parsed = urlparse(args.ocpp_url)
    if (
        parsed.scheme not in {"ws", "wss"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.path not in {"", "/"}
    ):
        raise SystemExit("Use a ws/wss server origin without credentials/query/path")
    if not 1 <= args.settlement_timeout <= 600:
        raise SystemExit("Settlement timeout must be 1..600 seconds")
    from sqlalchemy import text

    from scripts.t107_manifest_run import apply_run, cleanup_run
    from simulator.t108_fixture import lock_key, prepare_station
    from src.platform.database.session import SessionFactory

    async with SessionFactory() as guard:
        key = lock_key(manifest) + 1
        if not await guard.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
        ):
            raise SystemExit("This run is already running or cleaning up")
        try:
            async with SessionFactory() as db, db.begin():
                if args.action == "cleanup":
                    await cleanup_run(db, manifest)
                else:
                    if not args.admin_email:
                        raise SystemExit("Run requires --admin-email for T-88")
                    await prepare_station(db, manifest)
                    await apply_run(db, manifest, args.admin_email)
            save_json(args.manifest, manifest.model_dump(mode="json"))
            if args.action == "run":
                report = await execute(
                    manifest,
                    args.ocpp_url,
                    directory,
                    SessionFactory,
                    args.settlement_timeout,
                )
                if not report["passed"]:
                    raise SystemExit(
                        "Reconciliation FAIL; see report.json and reconciliation.xlsx"
                    )
            else:
                print("Logical cleanup complete; financial evidence retained")
        finally:
            await guard.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})


if __name__ == "__main__":
    import selectors

    asyncio.run(
        main(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )
