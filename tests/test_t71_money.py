from datetime import datetime
from decimal import Decimal, localcontext
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from src.modules.billing import segmentation
from src.modules.billing.money import tien_dong


@pytest.mark.parametrize(
    ("energy_wh", "price", "expected"),
    [
        (1, 2500, 3),
        (3, 2500, 8),
        (5, 3800, 19),
        (0, 3800, 0),
        (10**40 + 1, 2500, 25 * 10**39 + 3),
        (1, 2499, 2),
        (1, 2501, 3),
        (Decimal("1166.5"), 3000, 3500),
        (Decimal("0.0001"), 1000, 0),
        (-1, 2500, -3),
    ],
)
def test_rounding_table(energy_wh: int | Decimal, price: int, expected: int) -> None:
    amount = tien_dong(energy_wh, price)
    assert type(amount) is int
    assert amount == expected


def test_decimal_context_does_not_change_amount_or_input() -> None:
    reading = Decimal("10000000000000000000000000000000000000001.5")
    with localcontext() as context:
        context.prec = 6
        assert tien_dong(reading, 1000) == 10**40 + 2
    assert reading == Decimal("10000000000000000000000000000000000000001.5")


@pytest.mark.parametrize("energy_wh", [1.0, True, "1"])
def test_reject_inexact_or_wrong_energy_type(energy_wh: object) -> None:
    with pytest.raises(TypeError, match="energy_wh"):
        tien_dong(cast(int, energy_wh), 2500)


@pytest.mark.parametrize("price", [2500.0, True, Decimal(2500)])
def test_rate_must_be_integer_vnd(price: object) -> None:
    with pytest.raises(TypeError, match="price_vnd_per_kwh"):
        tien_dong(1, cast(int, price))


@pytest.mark.parametrize("reading", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_reject_nonfinite_reading(reading: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        tien_dong(Decimal(reading), 2500)


def test_chia_doan_uses_common_rounding_for_each_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Decimal, int]] = []

    def recording_rounding(energy_wh: Decimal, price: int) -> int:
        calls.append((energy_wh, price))
        return tien_dong(energy_wh, price)

    monkeypatch.setattr(segmentation, "tien_dong", recording_rounding)
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 21, 0, tzinfo=tz)
    boundary = datetime(2023, 10, 25, 22, 0, tzinfo=tz)
    end = datetime(2023, 10, 25, 23, 0, tzinfo=tz)
    meter_values = [
        segmentation.MeterValue(start, Decimal(0)),
        segmentation.MeterValue(boundary, Decimal("1166.5")),
        segmentation.MeterValue(end, Decimal(2333)),
    ]
    tariffs = {
        start.date(): [
            segmentation.TariffFrame("00:00", "22:00", 3000, "v1", "A"),
            segmentation.TariffFrame("22:00", "24:00", 3000, "v1", "B"),
        ]
    }
    segments = segmentation.chia_doan(start, end, meter_values, tariffs, tz.key)

    assert calls == [(Decimal("1166.5"), 3000), (Decimal("1166.5"), 3000)]
    assert [segment["amount_vnd"] for segment in segments] == [3500, 3500]
    assert sum(segment["amount_vnd"] for segment in segments) == 7000
    assert tien_dong(2333, 3000) == 6999
