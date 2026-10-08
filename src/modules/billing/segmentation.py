from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class MeterValue:
    """Lớp chứa dữ liệu điểm đo công tơ."""

    def __init__(self, timestamp: datetime, energy_wh: Decimal):
        self.timestamp = timestamp
        self.energy_wh = energy_wh


class TariffFrame:
    """Khung giá được cấu hình từ CSMS."""

    def __init__(
        self,
        start_time: str,
        end_time: str,
        price_vnd_per_kwh: int,
        tariff_version: str,
        frame_label: str,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.price_vnd_per_kwh = price_vnd_per_kwh
        self.tariff_version = tariff_version
        self.frame_label = frame_label


def interpolate_meter_value(
    target_time: datetime, meter_values: list[MeterValue]
) -> tuple[Decimal, bool]:
    """
    Task T-72: Nội suy tuyến tính tìm chỉ số điện tại một điểm giao cắt.

    :param target_time: Thời điểm cần cắt (chia đoạn).
    :param meter_values: Danh sách các bản ghi MeterValue đã được sắp xếp tăng dần theo thời gian.
    :return: (Chỉ số điện tại target_time, cờ interpolated).
    """
    if not meter_values:
        raise ValueError("Danh sách meter_values trống.")

    # Rule 3: Out of bounds -> Báo lỗi
    if (
        target_time < meter_values[0].timestamp
        or target_time > meter_values[-1].timestamp
    ):
        raise ValueError(f"Thời điểm cắt {target_time} nằm ngoài khoảng số đo.")

    # Tìm kiếm tuyến tính (do mảng ngắn, nếu mảng dài có thể dùng bisection)
    for i, mv in enumerate(meter_values):
        # Rule 1: Exact match -> Lấy chỉ số gốc, interpolated = False
        if mv.timestamp == target_time:
            return mv.energy_wh, False

        # Rule 2: Interpolation -> Nằm giữa 2 điểm
        if mv.timestamp > target_time:
            point_a = meter_values[i - 1]
            point_b = mv

            t_target = Decimal(target_time.timestamp())
            t_a = Decimal(point_a.timestamp.timestamp())
            t_b = Decimal(point_b.timestamp.timestamp())

            e_a = point_a.energy_wh
            e_b = point_b.energy_wh

            # Tính tỷ lệ nội suy
            time_ratio = (t_target - t_a) / (t_b - t_a)
            interpolated = e_a + (e_b - e_a) * time_ratio

            # Làm tròn nửa lên (ROUND_HALF_UP) về số nguyên Wh
            rounded = interpolated.quantize(Decimal(1), rounding=ROUND_HALF_UP)

            return rounded, True

    raise ValueError(f"Không thể nội suy cho {target_time}.")


def chia_doan(
    session_start: datetime,
    session_end: datetime,
    meter_values: list[MeterValue],
    daily_tariffs: dict[date, list[TariffFrame]],
    station_timezone: str,
) -> list[dict[str, Any]]:
    """
    Hàm chia đoạn (S-30). Đang trong quá trình triển khai.
    (Sẽ gọi hàm interpolate_meter_value cho các mốc chuyển giờ/đổi ngày).
    """
    return []
