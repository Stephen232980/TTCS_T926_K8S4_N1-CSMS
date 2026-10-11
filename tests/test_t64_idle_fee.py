from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.modules.billing.idle_fee import tinh_phi_chiem_tru


@pytest.mark.parametrize(
    ("elapsed_us", "grace", "expected_minutes", "expected_amount"),
    [
        (None, 5, 0, 0),
        (4 * 60_000_000, 5, 0, 0),
        (5 * 60_000_000, 5, 0, 0),
        (35 * 60_000_000, 5, 30, 6000),
        (35 * 60_000_000 + 20_000_000, 5, 31, 6200),
        (30 * 60_000_000 + 20_000_000, 0, 31, 6200),
        (5 * 60_000_000 + 1, 5, 1, 200),
    ],
)
def test_required_table(
    elapsed_us: int | None, grace: int, expected_minutes: int, expected_amount: int
) -> None:
    start = datetime(2026, 10, 9, tzinfo=UTC)
    end = start + timedelta(microseconds=elapsed_us or 0)
    assert tinh_phi_chiem_tru(
        start if elapsed_us is not None else None, end, grace, 200
    ) == (expected_minutes, expected_amount)


def test_offsets_and_midnight_use_actual_elapsed_time() -> None:
    start = datetime(2026, 10, 9, 23, 50, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    end = datetime(2026, 10, 9, 17, 20, tzinfo=UTC)
    assert tinh_phi_chiem_tru(start, end, 5, 200) == (25, 5000)


def test_zero_rate_keeps_billable_minutes() -> None:
    start = datetime(2026, 10, 9, tzinfo=UTC)
    assert tinh_phi_chiem_tru(start, start + timedelta(seconds=61), 0, 0) == (2, 0)


def test_large_amount_is_exact() -> None:
    start = datetime(2026, 10, 9, tzinfo=UTC)
    assert tinh_phi_chiem_tru(start, start + timedelta(minutes=2), 0, 10**40) == (
        2,
        2 * 10**40,
    )


@pytest.mark.parametrize(
    ("grace", "rate"), [(True, 200), (0, True), (1.5, 200), (0, 200.5)]
)
def test_reject_noninteger_parameters(grace: int, rate: int) -> None:
    with pytest.raises(TypeError):
        tinh_phi_chiem_tru(None, datetime(2026, 10, 9, tzinfo=UTC), grace, rate)


@pytest.mark.parametrize(("grace", "rate"), [(-1, 200), (0, -1)])
def test_reject_negative_parameters(grace: int, rate: int) -> None:
    with pytest.raises(ValueError):
        tinh_phi_chiem_tru(None, datetime(2026, 10, 9, tzinfo=UTC), grace, rate)


def test_reject_reversed_times() -> None:
    start = datetime(2026, 10, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="precedes"):
        tinh_phi_chiem_tru(start, start - timedelta(seconds=1), 0, 200)


@pytest.mark.parametrize("naive_start", [True, False])
def test_reject_naive_timestamp(naive_start: bool) -> None:
    aware = datetime(2026, 10, 9, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        tinh_phi_chiem_tru(
            naive if naive_start else aware, aware if naive_start else naive, 0, 200
        )
