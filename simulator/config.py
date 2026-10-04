"""S-26: đọc và kiểm tra cấu hình bộ trụ ảo từ biến môi trường."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

MAX_SIMULATED_CHARGERS = 100
_PREFIX = re.compile(r"[A-Z0-9-]+")
_SCENARIOS = {"online", "recovery"}


@dataclass(frozen=True)
class SimulatorSettings:
    """Runtime configuration shared by the seed, simulator and verifier."""

    count: int
    code_prefix: str
    tag_prefix: str
    ocpp_url: str
    scenario: str
    max_reconnects: int
    hold_seconds: int
    heartbeat_seconds: int
    report_path: str
    seed: int

    def code_for(self, index: int) -> str:
        """Return a stable, namespaced charger code for a one-based index."""
        self._validate_index(index)
        return f"{self.code_prefix}{index:03d}"

    def tag_for(self, index: int) -> str:
        """Return a simulator-only authorization tag for a one-based index."""
        self._validate_index(index)
        return f"{self.tag_prefix}{index:03d}"

    def _validate_index(self, index: int) -> None:
        if not 1 <= index <= self.count:
            raise ValueError(f"Simulator index must be between 1 and {self.count}")


def load_settings(values: Mapping[str, str] | None = None) -> SimulatorSettings:
    """Load S-26 settings without silently accepting unsafe or ambiguous values."""
    environment = os.environ if values is None else values
    count = _positive_int(
        environment, "SIMULATOR_COUNT", default=20, maximum=MAX_SIMULATED_CHARGERS
    )
    code_prefix = _prefix(
        environment.get("SIMULATOR_CODE_PREFIX", "SIM-"), "SIMULATOR_CODE_PREFIX", 61
    )
    tag_prefix = _prefix(
        environment.get("SIMULATOR_TAG_PREFIX", "SIMTAG-"), "SIMULATOR_TAG_PREFIX", 17
    )
    ocpp_url = _ocpp_url(environment.get("OCPP_URL", "ws://app:8000"))
    scenario = environment.get("SIMULATOR_SCENARIO", "online").strip().lower()
    if scenario not in _SCENARIOS:
        allowed = ", ".join(sorted(_SCENARIOS))
        raise ValueError(f"SIMULATOR_SCENARIO must be one of: {allowed}")
    return SimulatorSettings(
        count=count,
        code_prefix=code_prefix,
        tag_prefix=tag_prefix,
        ocpp_url=ocpp_url,
        scenario=scenario,
        max_reconnects=_positive_int(
            environment, "SIMULATOR_MAX_RECONNECTS", default=3, maximum=10
        ),
        hold_seconds=_non_negative_int(
            environment, "SIMULATOR_HOLD_SECONDS", default=0, maximum=600
        ),
        heartbeat_seconds=_positive_int(
            environment, "SIMULATOR_HEARTBEAT_SECONDS", default=5, maximum=300
        ),
        report_path=environment.get(
            "SIMULATOR_REPORT_PATH", "/reports/simulator-results.json"
        ).strip(),
        seed=_non_negative_int(environment, "SIMULATOR_RANDOM_SEED", default=2600),
    )


def _positive_int(
    values: Mapping[str, str], name: str, default: int, maximum: int
) -> int:
    result = _integer(values, name, default)
    if not 1 <= result <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return result


def _non_negative_int(
    values: Mapping[str, str], name: str, default: int, maximum: int | None = None
) -> int:
    result = _integer(values, name, default)
    if result < 0 or (maximum is not None and result > maximum):
        upper = f" and {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be between 0{upper}")
    return result


def _integer(values: Mapping[str, str], name: str, default: int) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error


def _prefix(value: str, name: str, maximum_length: int) -> str:
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > maximum_length
        or not _PREFIX.fullmatch(normalized)
    ):
        raise ValueError(
            f"{name} must contain only A-Z, 0-9 or '-' and fit generated IDs"
        )
    return normalized


def _ocpp_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc or parsed.query:
        raise ValueError(
            "OCPP_URL must be a WebSocket server URL without a query string"
        )
    return normalized
