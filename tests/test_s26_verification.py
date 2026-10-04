"""S-26: verifier reports each broken simulator result so CI failures are actionable."""

from simulator.verification import validate_report


def _report() -> dict[str, object]:
    return {
        "scenario": "recovery",
        "count": 2,
        "elapsed_seconds": 12.4,
        "chargers": [
            {
                "code": "SIM-001",
                "transaction_id": 101,
                "expected_meter_stop_wh": 3500,
                "expected_energy_kwh": "2.5",
                "reconnects": 2,
            },
            {
                "code": "SIM-002",
                "transaction_id": 102,
                "expected_meter_stop_wh": 3500,
                "expected_energy_kwh": "2.5",
                "reconnects": 1,
            },
        ],
    }


def test_s26_verifier_accepts_a_complete_recovery_report() -> None:
    """S-26 accepts all expected outcomes before querying the running services."""
    assert validate_report(_report(), 2) == []


def test_s26_verifier_lists_charger_and_energy_discrepancies() -> None:
    """S-26 names every broken charger field so a CI failure is diagnosable."""
    report = _report()
    rows = report["chargers"]
    assert isinstance(rows, list)
    first = rows[0]
    assert isinstance(first, dict)
    first["error"] = "websocket disconnected"
    first["expected_energy_kwh"] = "1.5"
    first["reconnects"] = 0
    second = rows[1]
    assert isinstance(second, dict)
    second["code"] = "SIM-001"
    second["transaction_id"] = 101

    issues = validate_report(report, 2)

    assert any("SIM-001 failed" in issue for issue in issues)
    assert any("SIM-001 appears more than once" in issue for issue in issues)
    assert any("reused transaction_id 101" in issue for issue in issues)
    assert any("expected energy must be 2.5 kWh" in issue for issue in issues)
    assert any("did not complete a reconnect" in issue for issue in issues)
