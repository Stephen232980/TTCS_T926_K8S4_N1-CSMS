from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.modules.billing.segmentation import MeterValue, interpolate_meter_value


def test_interpolate_exact_match():
    """T-72 Rule 1: Trùng mốc thì trả về đúng chỉ số gốc, interpolated = False."""
    mvs = [
        MeterValue(datetime(2023, 10, 25, 21, 50, tzinfo=UTC), Decimal(1000)),
        MeterValue(datetime(2023, 10, 25, 22, 0, tzinfo=UTC), Decimal("50123.75")),
        MeterValue(datetime(2023, 10, 25, 22, 10, tzinfo=UTC), Decimal(60000)),
    ]
    target = datetime(2023, 10, 25, 22, 0, tzinfo=UTC)

    val, is_interpolated = interpolate_meter_value(target, mvs)

    assert val == Decimal("50123.75")
    assert is_interpolated is False


def test_interpolate_linear_rounding():
    """T-72 Rule 2: Nằm giữa thì nội suy tuyến tính, làm tròn nửa lên về nguyên Wh."""
    # Tại 21:50, điện năng 40000.4
    # Tại 22:10, điện năng 60000.4
    # Nửa thời gian (22:00) => 40000.4 + 10000 = 50000.4
    # Cần làm tròn lên 50000 Wh.
    mvs = [
        MeterValue(datetime(2023, 10, 25, 21, 50, tzinfo=UTC), Decimal("40000.4")),
        MeterValue(datetime(2023, 10, 25, 22, 10, tzinfo=UTC), Decimal("60000.4")),
    ]
    target = datetime(2023, 10, 25, 22, 0, tzinfo=UTC)

    val, is_interpolated = interpolate_meter_value(target, mvs)

    assert val == Decimal(50000)
    assert is_interpolated is True


def test_interpolate_round_half_up():
    """T-72: Test kiểm tra cụ thể ROUND_HALF_UP (nửa lên)."""
    # 21:50 -> 0 Wh
    # 22:00 -> Mốc cắt, thời điểm = 50%
    # 22:10 -> 15 Wh
    # => Nội suy 50% = 7.5 Wh. ROUND_HALF_UP của 7.5 là 8.
    mvs = [
        MeterValue(datetime(2023, 10, 25, 21, 50, tzinfo=UTC), Decimal(0)),
        MeterValue(datetime(2023, 10, 25, 22, 10, tzinfo=UTC), Decimal(15)),
    ]
    target = datetime(2023, 10, 25, 22, 0, tzinfo=UTC)

    val, is_interpolated = interpolate_meter_value(target, mvs)

    assert val == Decimal(8)
    assert is_interpolated is True


def test_interpolate_out_of_bounds():
    """T-72 Rule 3: Nằm ngoài mảng đo thì văng lỗi."""
    mvs = [
        MeterValue(datetime(2023, 10, 25, 22, 10, tzinfo=UTC), Decimal(15)),
        MeterValue(datetime(2023, 10, 25, 22, 20, tzinfo=UTC), Decimal(20)),
    ]

    # 22:00 nằm trước 22:10
    target = datetime(2023, 10, 25, 22, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="nằm ngoài khoảng"):
        interpolate_meter_value(target, mvs)
