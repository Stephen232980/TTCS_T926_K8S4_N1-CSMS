from datetime import UTC, date, datetime
from decimal import Decimal

from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan


def test_case_9_utc_input_to_local_station() -> None:
    """
    T-76: Múi giờ
    Đầu vào 17:30 UTC, trạm UTC+7 phải xử lý như 00:30 hôm sau, áp biểu giá 00:00–06:00.
    """
    tz_station = "Asia/Ho_Chi_Minh"  # UTC+7

    # Input is in UTC: 2023-10-25 17:30 UTC -> 2023-10-26 00:30 Local
    # End: 2023-10-25 18:30 UTC -> 2023-10-26 01:30 Local
    start_utc = datetime(2023, 10, 25, 17, 30, tzinfo=UTC)
    end_utc = datetime(2023, 10, 25, 18, 30, tzinfo=UTC)

    mvs = [
        MeterValue(start_utc, Decimal(0)),
        MeterValue(end_utc, Decimal(10000)),
    ]

    # Cấu hình giá theo ngày local (26/10)
    tariffs = {
        date(2023, 10, 25): [
            TariffFrame("00:00:00", "24:00:00", 3000, "v1", "Day25"),
        ],
        date(2023, 10, 26): [
            TariffFrame("00:00:00", "06:00:00", 1500, "v1", "Night26"),
            TariffFrame("06:00:00", "24:00:00", 3000, "v1", "Day26"),
        ],
    }

    segments = chia_doan(start_utc, end_utc, mvs, tariffs, tz_station)

    # Phải có 1 đoạn
    assert len(segments) == 1
    seg = segments[0]

    # Kiểm tra local date là 26/10
    assert seg["local_date"] == date(2023, 10, 26)

    # Kiểm tra áp giá của khung 00:00 - 06:00
    assert seg["frame_label"] == "Night26"
    assert seg["price_vnd_per_kwh"] == 1500

    # Khẳng định nếu ép dùng UTC thì sẽ lấy giá của ngày 25 (Day25)
    segments_utc = chia_doan(start_utc, end_utc, mvs, tariffs, "UTC")
    assert len(segments_utc) == 1
    assert segments_utc[0]["local_date"] == date(2023, 10, 25)
    assert segments_utc[0]["frame_label"] == "Day25"
    assert segments_utc[0]["price_vnd_per_kwh"] == 3000
