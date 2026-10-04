"""S-26: quy tắc thuần để phát hiện báo cáo simulator không hợp lệ trong CI."""

from __future__ import annotations

from typing import Any

EXPECTED_ENERGY_KWH = "2.5"
EXPECTED_METER_STOP_WH = 3500
MAX_SCENARIO_SECONDS = 300


def validate_report(report: dict[str, Any], count: int) -> list[str]:
    """Return each actionable discrepancy without stopping at the first charger."""
    issues: list[str] = []
    if report.get("scenario") != "recovery":
        issues.append("scenario must be recovery")
    if report.get("count") != count:
        issues.append(
            f"expected {count} chargers but report declares {report.get('count')}"
        )
    elapsed = report.get("elapsed_seconds")
    elapsed_is_valid = (
        not isinstance(elapsed, bool)
        and isinstance(elapsed, (int, float))
        and 0 <= elapsed < MAX_SCENARIO_SECONDS
    )
    if not elapsed_is_valid:
        issues.append(f"scenario elapsed_seconds must be below {MAX_SCENARIO_SECONDS}")
    chargers = report.get("chargers")
    if not isinstance(chargers, list) or len(chargers) != count:
        issues.append(f"expected {count} charger results")
        return issues
    codes: set[str] = set()
    transaction_ids: set[int] = set()
    for row in chargers:
        if not isinstance(row, dict):
            issues.append("charger result must be an object")
            continue
        code = row.get("code")
        if not isinstance(code, str) or not code:
            issues.append("charger result is missing code")
        elif code in codes:
            issues.append(f"charger {code} appears more than once")
        else:
            codes.add(code)
        if row.get("error"):
            issues.append(f"charger {code or 'unknown'} failed: {row['error']}")
        transaction_id = row.get("transaction_id")
        if type(transaction_id) is not int:
            issues.append(f"charger {code} has no integer transaction_id")
        elif transaction_id in transaction_ids:
            issues.append(f"charger {code} reused transaction_id {transaction_id}")
        else:
            transaction_ids.add(transaction_id)
        if row.get("expected_meter_stop_wh") != EXPECTED_METER_STOP_WH:
            issues.append(f"charger {code} expected meter stop must be 3500 Wh")
        if row.get("expected_energy_kwh") != EXPECTED_ENERGY_KWH:
            issues.append(f"charger {code} expected energy must be 2.5 kWh")
        reconnects = row.get("reconnects")
        if type(reconnects) is not int or reconnects < 1:
            issues.append(f"charger {code} did not complete a reconnect")
    return issues
