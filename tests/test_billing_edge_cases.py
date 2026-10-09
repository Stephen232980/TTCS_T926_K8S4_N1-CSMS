from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from src.modules.billing.segmentation import (
    MeterValue,
    TariffFrame,
    chia_doan,
    interpolate_meter_value,
    tinh_tien_theo_ngay,
)


@pytest.mark.parametrize("microsecond", [1, 17, 999997])
def test_half_wh_with_microsecond_timestamps(microsecond: int) -> None:
    start = datetime(2026, 1, 1, microsecond=microsecond, tzinfo=UTC)
    readings = [
        MeterValue(start, Decimal(0)),
        MeterValue(start + timedelta(microseconds=2), Decimal(1)),
    ]
    assert interpolate_meter_value(start + timedelta(microseconds=1), readings) == (
        Decimal(1),
        True,
    )


def test_required_fifteen_minute_interpolation() -> None:
    start = datetime(2026, 1, 1, 21, 50, tzinfo=UTC)
    readings = [
        MeterValue(start, Decimal(9000)),
        MeterValue(start + timedelta(minutes=15), Decimal(10500)),
    ]
    assert interpolate_meter_value(start + timedelta(minutes=10), readings) == (
        Decimal(10000),
        True,
    )


@pytest.mark.parametrize(
    ("first", "last"),
    [("1000.4", "1000.4"), ("1000.4", "1000.6"), ("1000.6", "1001.4")],
)
def test_fractional_readings_never_generate_negative_segments(
    first: str, last: str
) -> None:
    start = datetime(2026, 1, 1, 21, tzinfo=UTC)
    end = start + timedelta(hours=2)
    readings = [MeterValue(start, Decimal(first)), MeterValue(end, Decimal(last))]
    tariffs = {
        start.date(): [
            TariffFrame("00:00", "22:00", 3000, "v1", "A"),
            TariffFrame("22:00", "24:00", 3000, "v1", "B"),
        ]
    }
    segments = chia_doan(start, end, readings, tariffs, "UTC")
    assert sum((s["energy_consumed_wh"] for s in segments), Decimal(0)) == Decimal(
        last
    ) - Decimal(first)
    assert all(s["energy_consumed_wh"] > 0 and s["amount_vnd"] >= 0 for s in segments)
    if first == last:
        assert segments == []


@pytest.mark.parametrize("different_prices", [False, True])
def test_thirty_hours_three_daily_groups(different_prices: bool) -> None:
    start = datetime(2026, 1, 31, 16, tzinfo=UTC)  # 23:00 UTC+7
    end = start + timedelta(hours=30)
    days = [date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 2)]
    prices = [1000, 2000, 3000] if different_prices else [2000] * 3
    tariffs = {
        day: [TariffFrame("00:00", "24:00", price, str(day), "all")]
        for day, price in zip(days, prices, strict=True)
    }
    readings = [MeterValue(start, Decimal(0)), MeterValue(end, Decimal(30000))]
    groups = tinh_tien_theo_ngay(start, end, readings, tariffs, "Asia/Ho_Chi_Minh")
    assert list(groups) == days
    assert [groups[day]["total_energy_wh"] for day in days] == [1000, 24000, 5000]
    assert [groups[day]["total_amount_vnd"] for day in days] == [
        wh * price // 1000
        for wh, price in zip([1000, 24000, 5000], prices, strict=True)
    ]
    assert sum(g["total_energy_wh"] for g in groups.values()) == 30000
    segments = chia_doan(start, end, readings, tariffs, "Asia/Ho_Chi_Minh")
    assert sum(g["total_amount_vnd"] for g in groups.values()) == sum(
        s["amount_vnd"] for s in segments
    )


def test_utc_input_selects_next_local_day_and_night_band() -> None:
    start = datetime(2026, 1, 31, 17, 30, tzinfo=UTC)
    end = start + timedelta(hours=1)
    previous, following = date(2026, 1, 31), date(2026, 2, 1)
    tariffs = {
        previous: [TariffFrame("00:00", "24:00", 9000, "old", "old")],
        following: [
            TariffFrame("00:00", "06:00", 1000, "new", "night"),
            TariffFrame("06:00", "24:00", 8000, "new", "day"),
        ],
    }
    groups = tinh_tien_theo_ngay(
        start,
        end,
        [MeterValue(start, Decimal(0)), MeterValue(end, Decimal(1000))],
        tariffs,
        "Asia/Ho_Chi_Minh",
    )
    assert list(groups) == [following]
    assert groups[following]["total_amount_vnd"] == 1000
    assert groups[following]["segments"][0]["frame_label"] == "night"


def test_decreasing_readings_rejected_before_billing() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    with pytest.raises(ValueError, match="giảm"):
        chia_doan(
            start,
            end,
            [MeterValue(start, Decimal(100)), MeterValue(end, Decimal(99))],
            {start.date(): [TariffFrame("00:00", "24:00", 1000, "v1", "all")]},
            "UTC",
        )


def test_large_meter_interpolation_independent_of_decimal_context() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    base = 10**40
    readings = [
        MeterValue(start, Decimal(base)),
        MeterValue(start + timedelta(seconds=2), Decimal(base + 1)),
    ]
    with localcontext() as context:
        context.prec = 6
        assert interpolate_meter_value(start + timedelta(seconds=1), readings) == (
            Decimal(base + 1),
            True,
        )
