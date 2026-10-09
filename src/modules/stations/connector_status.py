"""Display/report groups derived from detailed OCPP observations.

Groups are not permission to start charging; callers must still check the
station, liveness, connector and active-session state.
"""

from types import MappingProxyType
from typing import Literal

ConnectorStatusGroup = Literal[
    "available", "occupied", "reserved", "unavailable", "faulted", "unknown"
]

OCPP_STATUS_GROUPS: MappingProxyType[str, ConnectorStatusGroup] = MappingProxyType(
    {
        "Available": "available",
        "Preparing": "occupied",
        "Charging": "occupied",
        "SuspendedEV": "occupied",
        "SuspendedEVSE": "occupied",
        "Finishing": "occupied",
        "Reserved": "reserved",
        "Unavailable": "unavailable",
        "Faulted": "faulted",
    }
)


def connector_status_group(status: str | None) -> ConnectorStatusGroup:
    """Keep unknown/legacy observations distinct from faulted or available."""
    return (
        OCPP_STATUS_GROUPS.get(status, "unknown") if status is not None else "unknown"
    )
