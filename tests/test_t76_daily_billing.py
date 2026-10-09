from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.modules.billing.segmentation import (
    MeterValue,
    TariffFrame,
    tinh_tien_theo_ngay,
)


def test_t75_group_by_day_different_tariffs() -> None:
    """T-75: Phiên sạc qua nửa đêm, mỗi ngày có bảng giá khác nhau, gom nhóm theo ngày."""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 23, 0, tzinfo=tz)
    end = datetime(2023, 10, 26, 1, 0, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal(10000)),
        MeterValue(end, Decimal(30000)),
    ]
    # Ngày 25 giá 2000, Ngày 26 giá 3000
    tariffs = {
        date(2023, 10, 25): [TariffFrame("00:00:00", "24:00:00", 2000, "v1", "Day1")],
        date(2023, 10, 26): [TariffFrame("00:00:00", "24:00:00", 3000, "v2", "Day2")],
    }

    result = tinh_tien_theo_ngay(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")

    assert len(result) == 2
    day1 = result[date(2023, 10, 25)]
    day2 = result[date(2023, 10, 26)]

    # Nửa đêm cắt đôi: mỗi bên 10000 Wh (10 kWh)
    assert len(day1["segments"]) == 1
    assert day1["total_energy_wh"] == Decimal(10000)
    assert day1["total_amount_vnd"] == 20000  # 10 * 2000

    assert len(day2["segments"]) == 1
    assert day2["total_energy_wh"] == Decimal(10000)
    assert day2["total_amount_vnd"] == 30000  # 10 * 3000


def test_t75_session_longer_than_24_hours() -> None:
    """T-75: Phiên sạc kéo dài hơn 24 giờ, hoá đơn nhóm theo ngày."""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 12, 0, tzinfo=tz)
    end = datetime(2023, 10, 27, 12, 0, tzinfo=tz)  # 48 tiếng

    # 25: 12 tiếng, 26: 24 tiếng, 27: 12 tiếng. Giả sử tốc độ sạc đều 1kWh/h.
    mvs = [
        MeterValue(start, Decimal(0)),
        MeterValue(end, Decimal(48000)),
    ]

    tariffs = {
        date(2023, 10, 25): [TariffFrame("00:00:00", "24:00:00", 1000, "v1", "Day1")],
        date(2023, 10, 26): [TariffFrame("00:00:00", "24:00:00", 2000, "v2", "Day2")],
        date(2023, 10, 27): [TariffFrame("00:00:00", "24:00:00", 3000, "v3", "Day3")],
    }

    result = tinh_tien_theo_ngay(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")

    assert len(result) == 3
    assert result[date(2023, 10, 25)]["total_energy_wh"] == Decimal(12000)
    assert result[date(2023, 10, 25)]["total_amount_vnd"] == 12000

    assert result[date(2023, 10, 26)]["total_energy_wh"] == Decimal(24000)
    assert result[date(2023, 10, 26)]["total_amount_vnd"] == 48000

    assert result[date(2023, 10, 27)]["total_energy_wh"] == Decimal(12000)
    assert result[date(2023, 10, 27)]["total_amount_vnd"] == 36000


def test_t76_timezone_utc_and_partial_hour() -> None:
    """T-76: Múi giờ địa phương lệch nửa giờ (Ấn Độ +05:30). Không dùng UTC."""
    # UTC: 18:30 (25/10) -> Ấn Độ: 00:00 (26/10)
    tz_india = ZoneInfo("Asia/Kolkata")

    # Từ 23:00 ngày 25 -> 01:00 ngày 26 (Ấn Độ)
    start = datetime(2023, 10, 25, 23, 0, tzinfo=tz_india)
    end = datetime(2023, 10, 26, 1, 0, tzinfo=tz_india)

    mvs = [
        MeterValue(start, Decimal(0)),
        MeterValue(end, Decimal(20000)),
    ]

    tariffs = {
        date(2023, 10, 25): [TariffFrame("00:00:00", "24:00:00", 1500, "v1", "Day1")],
        date(2023, 10, 26): [TariffFrame("00:00:00", "24:00:00", 2500, "v2", "Day2")],
    }

    result = tinh_tien_theo_ngay(start, end, mvs, tariffs, "Asia/Kolkata")

    assert len(result) == 2
    assert result[date(2023, 10, 25)]["total_energy_wh"] == Decimal(10000)
    assert result[date(2023, 10, 25)]["total_amount_vnd"] == 15000

    assert result[date(2023, 10, 26)]["total_energy_wh"] == Decimal(10000)
    assert result[date(2023, 10, 26)]["total_amount_vnd"] == 25000
