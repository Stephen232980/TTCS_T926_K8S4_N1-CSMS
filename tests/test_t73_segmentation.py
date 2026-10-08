from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan


def test_case_1_single_frame() -> None:
    """Ví dụ 1: Phiên sạc gọn trong 1 khung giờ"""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 10, 0, tzinfo=tz)
    end = datetime(2023, 10, 25, 11, 0, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal(100000)),
        MeterValue(end, Decimal(120000)),
    ]
    tariffs = {
        date(2023, 10, 25): [TariffFrame("08:00:00", "12:00:00", 3000, "v1", "Normal")]
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    assert len(segments) == 1
    s = segments[0]
    assert s["energy_consumed_wh"] == Decimal(20000)
    assert s["price_vnd_per_kwh"] == 3000
    assert s["amount_vnd"] == 60000
    assert s["start_interpolated"] is False
    assert s["end_interpolated"] is False


def test_case_2_two_frames() -> None:
    """Ví dụ 2: Phiên sạc cắt qua 2 khung giờ, cần chia đúng ranh giới"""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 21, 30, tzinfo=tz)
    end = datetime(2023, 10, 25, 23, 30, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal(10000)),
        MeterValue(end, Decimal(50000)),
    ]
    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("20:00:00", "22:00:00", 3000, "v1", "Khung 1"),
            TariffFrame("22:00:00", "24:00:00", 2000, "v1", "Khung 2"),
        ]
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    assert len(segments) == 2

    assert segments[0]["start_time"] == start
    assert segments[0]["end_time"] == datetime(2023, 10, 25, 22, 0, tzinfo=tz)
    assert segments[0]["energy_consumed_wh"] == Decimal(10000)
    assert segments[0]["end_interpolated"] is True

    assert segments[1]["start_time"] == datetime(2023, 10, 25, 22, 0, tzinfo=tz)
    assert segments[1]["end_time"] == end
    assert segments[1]["energy_consumed_wh"] == Decimal(30000)
    assert segments[1]["start_interpolated"] is True


def test_case_3_midnight_cross() -> None:
    """Ví dụ 3: Phiên sạc vắt qua nửa đêm (Có múi giờ +05:30)"""
    tz = ZoneInfo("Asia/Kolkata")
    start = datetime(2023, 10, 25, 23, 0, tzinfo=tz)
    end = datetime(2023, 10, 26, 1, 0, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal(10000)),
        MeterValue(end, Decimal(30000)),
    ]
    tariffs = {
        date(2023, 10, 25): [TariffFrame("22:00:00", "24:00:00", 2000, "v1", "Night")],
        date(2023, 10, 26): [TariffFrame("00:00:00", "04:00:00", 2000, "v1", "Night")],
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Kolkata")
    assert len(segments) == 2

    assert segments[0]["local_date"] == date(2023, 10, 25)
    assert segments[0]["end_time"] == datetime(2023, 10, 26, 0, 0, tzinfo=tz)
    assert segments[1]["local_date"] == date(2023, 10, 26)
    assert segments[1]["start_time"] == datetime(2023, 10, 26, 0, 0, tzinfo=tz)


def test_case_4_rounding() -> None:
    """Ví dụ 4: Nội suy tuyến tính đúng nửa Wh, có phần lẻ"""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 21, 50, tzinfo=tz)
    end = datetime(2023, 10, 25, 22, 10, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal("40000.4")),
        MeterValue(end, Decimal("60000.4")),
    ]
    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("00:00:00", "22:00:00", 2000, "v1", "T1"),
            TariffFrame("22:00:00", "24:00:00", 3000, "v1", "T2"),
        ]
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    assert len(segments) == 2
    # At 22:00: 40000.4 + (20000 * 10 / 20) = 50000.4 -> rounded to 50000
    assert segments[0]["energy_consumed_wh"] == Decimal(50000) - Decimal("40000.4")
    assert segments[1]["energy_consumed_wh"] == Decimal("60000.4") - Decimal(50000)


def test_case_5_exact_decimal() -> None:
    """Ví dụ 5: Số đo đúng mốc, phần lẻ Wh"""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 21, 50, tzinfo=tz)
    end = datetime(2023, 10, 25, 22, 10, tzinfo=tz)
    mvs = [
        MeterValue(start, Decimal(40000)),
        MeterValue(datetime(2023, 10, 25, 22, 0, tzinfo=tz), Decimal("50123.75")),
        MeterValue(end, Decimal(60000)),
    ]
    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("00:00:00", "22:00:00", 2000, "v1", "T1"),
            TariffFrame("22:00:00", "24:00:00", 3000, "v1", "T2"),
        ]
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    assert len(segments) == 2
    assert segments[0]["end_interpolated"] is False
    assert segments[1]["start_interpolated"] is False
    assert segments[0]["energy_consumed_wh"] == Decimal("50123.75") - Decimal(40000)


def test_case_6_segment_amount_rounding() -> None:
    """Ví dụ 6: Làm tròn đúng nửa đồng, làm tròn theo đoạn khác làm tròn phiên"""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    start = datetime(2023, 10, 25, 21, 0, tzinfo=tz)
    end = datetime(2023, 10, 25, 23, 0, tzinfo=tz)

    mvs = [
        MeterValue(start, Decimal(0)),
        MeterValue(datetime(2023, 10, 25, 22, 0, tzinfo=tz), Decimal("1166.5")),
        MeterValue(end, Decimal(2333)),
    ]
    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("00:00:00", "22:00:00", 3000, "v1", "T1"),
            TariffFrame("22:00:00", "24:00:00", 3000, "v1", "T2"),
        ]
    }

    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    assert len(segments) == 2
    assert segments[0]["amount_vnd"] == 3500
    assert segments[1]["amount_vnd"] == 3500
    assert segments[0]["amount_vnd"] + segments[1]["amount_vnd"] == 7000
