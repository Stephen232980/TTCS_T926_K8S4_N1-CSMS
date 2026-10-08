from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo


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
    Hàm chia đoạn (S-30).
    Cắt phiên sạc thành các đoạn dựa trên ranh giới khung giờ biểu giá và ranh giới nửa đêm.
    """
    if session_start >= session_end:
        return []

    tz = ZoneInfo(station_timezone)
    start_local = session_start.astimezone(tz)
    end_local = session_end.astimezone(tz)

    cut_points = set()
    cut_points.add(session_start)
    cut_points.add(session_end)

    current_date = start_local.date()
    end_date = end_local.date()

    while current_date <= end_date:
        # Nửa đêm
        midnight = datetime.combine(current_date, time(0, 0), tzinfo=tz)
        if session_start < midnight < session_end:
            cut_points.add(midnight)

        # Biên biểu giá
        tariffs = daily_tariffs.get(current_date, [])
        for tf in tariffs:
            st_parts = list(map(int, tf.start_time.split(":")))
            et_parts = list(map(int, tf.end_time.split(":")))

            st_h, st_m, st_s = (
                st_parts[0],
                st_parts[1],
                st_parts[2] if len(st_parts) > 2 else 0,
            )
            et_h, et_m, et_s = (
                et_parts[0],
                et_parts[1],
                et_parts[2] if len(et_parts) > 2 else 0,
            )

            st_dt = datetime.combine(current_date, time(st_h, st_m, st_s), tzinfo=tz)
            if et_h == 24:
                et_dt = datetime.combine(
                    current_date + timedelta(days=1), time(0, 0), tzinfo=tz
                )
            else:
                et_dt = datetime.combine(
                    current_date, time(et_h, et_m, et_s), tzinfo=tz
                )

            if session_start < st_dt < session_end:
                cut_points.add(st_dt)
            if session_start < et_dt < session_end:
                cut_points.add(et_dt)

        current_date += timedelta(days=1)

    sorted_points = sorted(list(cut_points))
    segments = []

    for i in range(len(sorted_points) - 1):
        seg_start = sorted_points[i]
        seg_end = sorted_points[i + 1]

        # Chọn ngày local (lấy trung điểm để an toàn nằm trong đoạn)
        mid_point = seg_start + (seg_end - seg_start) / 2
        seg_local_date = mid_point.astimezone(tz).date()

        applied_tariff = None
        for tf in daily_tariffs.get(seg_local_date, []):
            st_parts = list(map(int, tf.start_time.split(":")))
            et_parts = list(map(int, tf.end_time.split(":")))

            st_h, st_m, st_s = (
                st_parts[0],
                st_parts[1],
                st_parts[2] if len(st_parts) > 2 else 0,
            )
            et_h, et_m, et_s = (
                et_parts[0],
                et_parts[1],
                et_parts[2] if len(et_parts) > 2 else 0,
            )

            st_dt = datetime.combine(seg_local_date, time(st_h, st_m, st_s), tzinfo=tz)
            if et_h == 24:
                et_dt = datetime.combine(
                    seg_local_date + timedelta(days=1), time(0, 0), tzinfo=tz
                )
            else:
                et_dt = datetime.combine(
                    seg_local_date, time(et_h, et_m, et_s), tzinfo=tz
                )

            if st_dt <= mid_point < et_dt:
                applied_tariff = tf
                break

        if not applied_tariff:
            # Dự phòng nếu không tìm thấy giá (ít xảy ra vì input chuẩn)
            continue

        start_wh, start_interp = interpolate_meter_value(seg_start, meter_values)
        end_wh, end_interp = interpolate_meter_value(seg_end, meter_values)

        energy_consumed_wh = end_wh - start_wh

        # Tính tiền T-71
        price = applied_tariff.price_vnd_per_kwh
        amount = (energy_consumed_wh * price / Decimal(1000)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )

        segments.append(
            {
                "local_date": seg_local_date,
                "start_time": seg_start,
                "end_time": seg_end,
                "energy_consumed_wh": energy_consumed_wh,
                "price_vnd_per_kwh": price,
                "amount_vnd": int(amount),
                "tariff_version": applied_tariff.tariff_version,
                "frame_label": applied_tariff.frame_label,
                "start_interpolated": start_interp,
                "end_interpolated": end_interp,
            }
        )

    return segments
