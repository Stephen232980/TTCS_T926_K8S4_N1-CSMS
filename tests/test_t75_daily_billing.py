from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan, tinh_tien_theo_ngay

def test_case_8_30h_across_3_days() -> None:
    """T-75: Nhóm theo ngày - 30 giờ qua ba ngày, các ngày cùng biểu giá."""
    tz = ZoneInfo("Asia/Ho_Chi_Minh")
    # Start: 2023-10-25 20:00 -> End: 2023-10-27 02:00 (30 hours)
    start = datetime(2023, 10, 25, 20, 0, tzinfo=tz)
    end = datetime(2023, 10, 27, 2, 0, tzinfo=tz)

    # Tiêu thụ tổng 30000 Wh (đều nhau 1000 Wh mỗi giờ)
    mvs = [
        MeterValue(start, Decimal(0)),
        MeterValue(datetime(2023, 10, 26, 0, 0, tzinfo=tz), Decimal(4000)),
        MeterValue(datetime(2023, 10, 26, 20, 0, tzinfo=tz), Decimal(24000)),
        MeterValue(datetime(2023, 10, 27, 0, 0, tzinfo=tz), Decimal(28000)),
        MeterValue(end, Decimal(30000)),
    ]

    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("00:00:00", "22:00:00", 3000, "v1", "Normal"),
            TariffFrame("22:00:00", "24:00:00", 2000, "v1", "Night"),
        ],
        date(2023, 10, 26): [
            TariffFrame("00:00:00", "04:00:00", 2000, "v1", "Night"),
            TariffFrame("04:00:00", "22:00:00", 3000, "v1", "Normal"),
            TariffFrame("22:00:00", "24:00:00", 2000, "v1", "Night"),
        ],
        date(2023, 10, 27): [
            TariffFrame("00:00:00", "04:00:00", 2000, "v1", "Night"),
            TariffFrame("04:00:00", "22:00:00", 3000, "v1", "Normal"),
            TariffFrame("22:00:00", "24:00:00", 2000, "v1", "Night"),
        ],
    }

    # Tổng bằng hàm chia_doan
    segments = chia_doan(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")
    total_wh = sum(s["energy_consumed_wh"] for s in segments)
    total_amount = sum(s["amount_vnd"] for s in segments)

    # Nhóm theo ngày
    grouped = tinh_tien_theo_ngay(start, end, mvs, tariffs, "Asia/Ho_Chi_Minh")

    # Kiểm tra có 3 ngày
    assert len(grouped) == 3
    assert date(2023, 10, 25) in grouped
    assert date(2023, 10, 26) in grouped
    assert date(2023, 10, 27) in grouped

    # Kiểm tra tổng của các nhóm
    grouped_total_wh = sum(g["total_energy_wh"] for g in grouped.values())
    grouped_total_amount = sum(g["total_amount_vnd"] for g in grouped.values())

    assert grouped_total_wh == total_wh
    assert grouped_total_amount == total_amount
    assert total_wh == Decimal(30000)
