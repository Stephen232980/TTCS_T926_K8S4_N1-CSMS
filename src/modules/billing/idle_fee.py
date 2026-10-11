"""Pure idle-fee calculation shared by invoice callers (T-64)."""

from datetime import UTC, datetime, timedelta


def tinh_phi_chiem_tru(
    idle_since: datetime | None,
    session_end: datetime,
    grace_minutes: int,
    idle_rate_vnd_per_minute: int,
) -> tuple[int, int]:
    """Return (billable minutes, whole VND) after grace, rounding minutes up.

    session_end is the StopTransaction end time. Missing idle_since means
    no idle fee. Aware timestamps are compared as actual instants in UTC.
    """
    for name, value in (
        ("grace_minutes", grace_minutes),
        ("idle_rate_vnd_per_minute", idle_rate_vnd_per_minute),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be int")
        if value < 0:
            raise ValueError(f"{name} must be nonnegative")
    if session_end.utcoffset() is None:
        raise ValueError("session_end must have timezone")
    if idle_since is None:
        return 0, 0
    if idle_since.utcoffset() is None:
        raise ValueError("idle_since must have timezone")

    elapsed = session_end.astimezone(UTC) - idle_since.astimezone(UTC)
    if elapsed < timedelta(0):
        raise ValueError("session_end precedes idle_since")
    minute_us = 60_000_000
    excess_us = elapsed // timedelta(microseconds=1) - grace_minutes * minute_us
    billable_minutes = max(0, (excess_us + minute_us - 1) // minute_us)
    return billable_minutes, billable_minutes * idle_rate_vnd_per_minute
