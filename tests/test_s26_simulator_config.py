"""S-26: simulator settings retain stable, isolated charger and tag identifiers."""

import pytest

from simulator.config import load_settings


def test_simulator_defaults_create_twenty_namespaced_chargers() -> None:
    """S-26 keeps the default fleet deterministic for local and CI scenarios."""
    settings = load_settings({})

    assert settings.count == 20
    assert settings.code_for(1) == "SIM-001"
    assert settings.code_for(20) == "SIM-020"
    assert settings.tag_for(1) == "SIMTAG-001"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"SIMULATOR_COUNT": "0"}, "SIMULATOR_COUNT"),
        ({"SIMULATOR_COUNT": "many"}, "SIMULATOR_COUNT"),
        ({"SIMULATOR_CODE_PREFIX": "sim space"}, "SIMULATOR_CODE_PREFIX"),
        ({"OCPP_URL": "http://app:8000"}, "OCPP_URL"),
        ({"SIMULATOR_SCENARIO": "unknown"}, "SIMULATOR_SCENARIO"),
    ],
)
def test_simulator_rejects_invalid_runtime_configuration(
    values: dict[str, str], message: str
) -> None:
    """S-26 fails before connecting when Compose configuration is invalid."""
    with pytest.raises(ValueError, match=message):
        load_settings(values)


def test_simulator_accepts_a_configured_charger_count_and_prefix() -> None:
    """S-26 allows the one-command Compose scenario to select its fleet size."""
    settings = load_settings(
        {
            "SIMULATOR_COUNT": "3",
            "SIMULATOR_CODE_PREFIX": "CI-",
            "SIMULATOR_TAG_PREFIX": "TAG-",
            "OCPP_URL": "wss://csms.example.test/ocpp",
            "SIMULATOR_SCENARIO": "recovery",
        }
    )

    assert [settings.code_for(index) for index in range(1, 4)] == [
        "CI-001",
        "CI-002",
        "CI-003",
    ]
    assert settings.tag_for(3) == "TAG-003"
    assert settings.ocpp_url == "wss://csms.example.test/ocpp"
