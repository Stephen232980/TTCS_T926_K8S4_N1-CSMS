"""S-26: verify Compose simulator output through CSMS API and PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from time import monotonic
from typing import Any, cast

import httpx
from sqlalchemy import select

from simulator.config import SimulatorSettings, load_settings
from simulator.reporting import read_current_report
from simulator.seed import SIMULATOR_OPERATOR_EMAIL
from simulator.verification import validate_report
from src.modules.charging.models import ChargingSession
from src.modules.stations.models import ChargePoint
from src.platform.database.session import SessionFactory


async def verify(settings: SimulatorSettings) -> None:
    """Fail the process when S-26 simulator, API or stored session data disagree."""
    report = await _wait_for_report(settings)
    issues = validate_report(report, settings.count)
    expected = {settings.code_for(index) for index in range(1, settings.count + 1)}
    rows = report.get("chargers")
    if isinstance(rows, list):
        reported: set[str] = set()
        for row in rows:
            if isinstance(row, dict):
                code = row.get("code")
                if isinstance(code, str):
                    reported.add(code)
        if reported != expected:
            issues.append(
                "report charger codes differ from configured fleet: "
                f"expected={sorted(expected)} actual={sorted(reported)}"
            )
    else:
        issues.append("report charger results are unavailable")
    issues.extend(await _verify_connections(settings, expected))
    issues.extend(await _verify_sessions(report))
    if issues:
        details = "\n".join(f"- {issue}" for issue in issues)
        raise RuntimeError(f"S-26 simulator verification failed:\n{details}")
    print(
        f"S-26 verified {settings.count}/{settings.count} online chargers and sessions.",
        flush=True,
    )


async def _wait_for_report(settings: SimulatorSettings) -> dict[str, Any]:
    timeout = _positive_int("SIMULATOR_VERIFY_TIMEOUT_SECONDS", 180)
    deadline = monotonic() + timeout
    latest_error: Exception | None = None
    while monotonic() < deadline:
        try:
            return read_current_report(settings.report_path)
        except (FileNotFoundError, OSError, ValueError, TypeError) as error:
            latest_error = error
            await asyncio.sleep(1)
    raise RuntimeError("Timed out waiting for simulator report") from latest_error


async def _verify_connections(
    settings: SimulatorSettings, expected_codes: set[str]
) -> list[str]:
    timeout = _positive_int("SIMULATOR_VERIFY_TIMEOUT_SECONDS", 180)
    base_url = os.environ.get("CSMS_HTTP_URL", "http://app:8000").rstrip("/")
    password = os.environ.get("SIMULATOR_OPERATOR_PASSWORD", "")
    if not password:
        return ["SIMULATOR_OPERATOR_PASSWORD must not be empty"]
    deadline = monotonic() + timeout
    latest_error = "connection API did not return all online chargers"
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": SIMULATOR_OPERATOR_EMAIL, "password": password},
        )
        if login.status_code != 200:
            return [f"simulator operator login returned HTTP {login.status_code}"]
        while monotonic() < deadline:
            try:
                response = await client.get(
                    "/api/v1/ops/ocpp/connections", params={"page": 1, "page_size": 100}
                )
                if response.status_code != 200:
                    latest_error = (
                        f"connection API returned HTTP {response.status_code}"
                    )
                else:
                    payload = response.json()
                    items = payload.get("items") if isinstance(payload, dict) else None
                    if isinstance(items, list):
                        matching: dict[str, dict[Any, Any]] = {}
                        for item in items:
                            if isinstance(item, dict):
                                code = item.get("code")
                                if isinstance(code, str) and code in expected_codes:
                                    matching[code] = item
                        online = {
                            code
                            for code, item in matching.items()
                            if item.get("online")
                            and item.get("connected")
                            and item.get("boot_accepted")
                        }
                        if online == expected_codes:
                            return []
                        latest_error = (
                            "online chargers="
                            f"{sorted(online)}, expected={sorted(expected_codes)}"
                        )
            except httpx.HTTPError as error:
                latest_error = f"connection API error: {error}"
            await asyncio.sleep(1)
    return [latest_error]


async def _verify_sessions(report: dict[str, Any]) -> list[str]:
    rows = report.get("chargers")
    if not isinstance(rows, list):
        return ["cannot verify sessions without charger results"]
    expected: dict[int, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            transaction_id = row.get("transaction_id")
            if type(transaction_id) is int:
                expected[transaction_id] = cast(dict[str, Any], row)
    if not expected:
        return ["report did not contain transaction IDs"]
    async with SessionFactory() as session:
        sessions = (
            await session.execute(
                select(ChargingSession, ChargePoint.code)
                .join(ChargePoint, ChargePoint.id == ChargingSession.charge_point_id)
                .where(ChargingSession.id.in_(expected))
            )
        ).all()
    issues: list[str] = []
    found: dict[int, tuple[ChargingSession, str]] = {
        item.id: (item, charge_point_code) for item, charge_point_code in sessions
    }
    for transaction_id, row in expected.items():
        item = found.get(transaction_id)
        raw_code = row.get("code")
        code = raw_code if isinstance(raw_code, str) else "unknown"
        if item is None:
            issues.append(f"charger {code} is missing session {transaction_id}")
            continue
        charging_session, charge_point_code = item
        if charge_point_code != code:
            issues.append(
                f"charger {code} report references session {transaction_id} "
                f"owned by {charge_point_code}"
            )
        if charging_session.ended_at is None:
            issues.append(f"charger {code} session {transaction_id} is still open")
        if charging_session.meter_stop_wh != Decimal(3500):
            issues.append(
                f"charger {code} meter stop expected 3500 Wh, "
                f"actual {charging_session.meter_stop_wh}"
            )
        if charging_session.energy_kwh != Decimal("2.5"):
            issues.append(
                f"charger {code} energy expected 2.5 kWh, "
                f"actual {charging_session.energy_kwh}"
            )
    return issues


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def main() -> None:
    """Run S-26 verification as the Compose/CI success or failure process."""
    try:
        asyncio.run(verify(load_settings()))
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
        print(str(error), file=sys.stderr, flush=True)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
