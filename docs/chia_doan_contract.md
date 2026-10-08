# Hợp đồng hàm `chia_doan` (Task T-70)

Tài liệu này định nghĩa giao diện (interface) và các ví dụ (test cases) cho hàm `chia_doan` thuộc Story S-30.

## 1. Hợp đồng (Signature / Interface)

### Cấu trúc Dữ liệu Đầu vào (Input)

- Thống nhất không sử dụng `float` cho các tính toán chỉ số điện và tiền.
- Sử dụng `Decimal` cho điện năng (Wh) để bảo toàn phần lẻ của dữ liệu gốc. Nên khởi tạo `Decimal` từ chuỗi (string) hoặc số nguyên.
- Đơn giá và Thành tiền sử dụng `int` (nguyên đồng).

```python
from typing import List, Dict
from datetime import datetime, date
from decimal import Decimal


class MeterValue:
    def __init__(self, timestamp: datetime, energy_wh: Decimal):
        self.timestamp = timestamp
        self.energy_wh = energy_wh


class TariffFrame:
    def __init__(self, start_time: str, end_time: str, price_vnd_per_kwh: int, tariff_version: str, frame_label: str):
        # start_time, end_time định dạng "HH:MM:SS"
        self.start_time = start_time
        self.end_time = end_time
        self.price_vnd_per_kwh = price_vnd_per_kwh
        self.tariff_version = tariff_version
        self.frame_label = frame_label


def chia_doan(
    session_start: datetime,
    session_end: datetime,
    meter_values: List[MeterValue],
    daily_tariffs: Dict[date, List[TariffFrame]],
    station_timezone: str,
) -> List[Dict]:
    """
    Hàm thuần cắt phiên sạc thành các đoạn dựa trên ranh giới khung giờ biểu giá và ranh giới nửa đêm.
    
    Quy tắc Nội suy (T-72):
    - Mốc trùng số đo: lấy đúng chỉ số gốc (Decimal).
    - Mốc nằm giữa: nội suy tuyến tính chính xác, làm tròn nửa lên (ROUND_HALF_UP) về Wh nguyên (Decimal không có phần lẻ), đánh cờ interpolated=True.
    - Mốc ngoài khoảng: báo lỗi.
    
    Quy tắc Tính tiền (T-71):
    - Điện năng đoạn (Wh) × đơn giá (đồng/kWh) / 1000.
    - Làm tròn nửa lên (ROUND_HALF_UP) về đồng nguyên ở từng đoạn.
    - Tổng tiền phiên = Tổng các đoạn (Không làm tròn lại từ tổng Wh cả phiên).

    :param session_start: Thời gian bắt đầu phiên sạc (có timezone).
    :param session_end: Thời gian kết thúc phiên sạc (có timezone).
    :param meter_values: Danh sách các bản ghi chỉ số (Wh) trong suốt phiên.
    :param daily_tariffs: Ánh xạ ngày địa phương (local date) của trạm sang danh sách khung giá.
    :param station_timezone: Múi giờ của trạm (VD: "Asia/Ho_Chi_Minh"). Cắt nửa đêm theo múi giờ này.
    :return: Danh sách các đoạn sạc.
    """
    pass
```

### Cấu trúc Dữ liệu Đầu ra (Output)

Hàm sẽ trả về một List các Dictionary (mỗi Dict đại diện cho một đoạn sạc):

```python
[
    {
        "local_date": date,              # Ngày địa phương của trạm
        "start_time": datetime,          # Bắt đầu đoạn
        "end_time": datetime,            # Kết thúc đoạn
        "energy_consumed_wh": Decimal,   # Điện năng tiêu thụ trong đoạn (Wh)
        "price_vnd_per_kwh": int,        # Đơn giá áp dụng (đồng/kWh)
        "amount_vnd": int,               # Thành tiền của đoạn (đã làm tròn)
        "tariff_version": str,           # Mã phiên bản biểu giá
        "frame_label": str,              # Nhãn khung giá
        "start_interpolated": bool,      # Cờ báo hiệu điểm đầu là kết quả nội suy
        "end_interpolated": bool,        # Cờ báo hiệu điểm cuối là kết quả nội suy
    },
    ...,
]
```

---

## 2. Sáu Ví dụ Mẫu (Test Cases)

Dưới đây là 6 kịch bản cần được cover bởi Unit Test cho hàm này.

### Ví dụ 1: Phiên sạc gọn trong 1 khung giờ
*   **Mô tả**: Phiên sạc không bị cắt, nằm hoàn toàn trong một khung giá.
*   **Input**:
    *   Múi giờ trạm: `Asia/Ho_Chi_Minh` (+07:00).
    *   Sạc từ `2023-10-25 10:00:00+07:00` đến `2023-10-25 11:00:00+07:00`.
    *   Chỉ số: Tại `10:00:00` là `100000 Wh`, tại `11:00:00` là `120000 Wh`.
    *   Biểu giá ngày `2023-10-25`: `08:00:00 - 12:00:00` giá `3000 đ/kWh`.
*   **Output kỳ vọng**:
    *   1 đoạn duy nhất: Tiêu thụ 20000 Wh, giá 3000 đ/kWh. 
    *   Thành tiền: `20000 * 3000 / 1000 = 60000` đ.
    *   `start_interpolated`: False, `end_interpolated`: False.

### Ví dụ 2: Phiên sạc cắt qua 2 khung giờ, cần chia đúng ranh giới
*   **Mô tả**: Giao mốc đổi giá, dùng chung một chỉ số nội suy để bảo toàn tổng năng lượng.
*   **Input**:
    *   Sạc từ `21:30:00` đến `23:30:00`.
    *   Mốc cắt lúc `22:00:00`.
    *   Chỉ số: `21:30:00` = `10000 Wh`, `23:30:00` = `50000 Wh`.
*   **Output kỳ vọng**:
    *   Nội suy lúc `22:00:00`: `10000 + (50000 - 10000) * (30 / 120) = 20000 Wh`.
    *   Đoạn 1 (21:30 - 22:00): Tiêu thụ 10000 Wh. Điểm cuối `end_interpolated` = True.
    *   Đoạn 2 (22:00 - 23:30): Tiêu thụ 30000 Wh. Điểm đầu `start_interpolated` = True.
    *   Ranh cắt dùng chung chỉ số 20000 Wh cho 2 đoạn kề nhau.

### Ví dụ 3: Phiên sạc vắt qua nửa đêm (Có múi giờ +05:30)
*   **Mô tả**: Trạm ở múi giờ `Asia/Kolkata` (+05:30). Sạc qua nửa đêm địa phương.
*   **Input**:
    *   Sạc từ `2023-10-25 23:00:00+05:30` đến `2023-10-26 01:00:00+05:30`.
    *   Biểu giá ban đêm (từ 22:00 tới 04:00) là `2000 đ/kWh`.
*   **Output kỳ vọng**:
    *   Cắt tại `2023-10-26 00:00:00+05:30`.
    *   Đoạn 1: 23:00 - 00:00. `local_date` là `2023-10-25`.
    *   Đoạn 2: 00:00 - 01:00. `local_date` là `2023-10-26`.

### Ví dụ 4: Nội suy tuyến tính đúng nửa Wh, có phần lẻ
*   **Mô tả**: Số đo gốc có phần lẻ, nội suy làm tròn nửa lên về nguyên Wh.
*   **Input**:
    *   Mốc đổi giá lúc `22:00:00`.
    *   MeterValue tại `21:50:00` là `40000.4 Wh`.
    *   MeterValue tại `22:10:00` là `60000.4 Wh`. (Chênh nhau 20000 Wh trong 20 phút).
*   **Output kỳ vọng (Nội suy)**:
    *   Tính toán tại `22:00:00`: `40000.4 + (20000 * 10 / 20) = 50000.4 Wh`.
    *   Làm tròn nửa lên về nguyên Wh (T-72): `50000 Wh`. Điểm cắt là một số Decimal không có phần lẻ.

### Ví dụ 5: Số đo đúng mốc, phần lẻ Wh
*   **Mô tả**: Có số đo khớp mốc cắt, lấy đúng nguyên bản (Decimal), không nội suy.
*   **Input**:
    *   Cắt lúc `22:00:00`.
    *   MeterValue báo tại đúng `22:00:00` là `50123.75 Wh`.
*   **Output kỳ vọng**:
    *   Dùng chính xác `50123.75 Wh` (Decimal) ở ranh giới cắt.
    *   Cờ `interpolated` (cả start và end tương ứng) = False.

### Ví dụ 6: Làm tròn đúng nửa đồng, làm tròn theo đoạn khác làm tròn phiên
*   **Mô tả**: Kiểm tra tính độc lập của đoạn (T-71) so với phiên. Làm tròn từng đoạn rồi mới cộng, không lấy tổng năng lượng phiên.
*   **Input**:
    *   Giá `3000 đ/kWh`.
    *   Đoạn 1 tiêu thụ: `1166.5 Wh`. Tính ra = `1166.5 * 3000 / 1000 = 3499.5` đồng.
    *   Đoạn 2 tiêu thụ: `1166.5 Wh`. Tính ra = `3499.5` đồng.
*   **Output kỳ vọng**:
    *   Đoạn 1 làm tròn nửa lên: `3500` đồng.
    *   Đoạn 2 làm tròn nửa lên: `3500` đồng.
    *   Tổng phiên thu: `7000` đồng.
    *   (Ghi chú: Nếu tính tổng Wh trước: `2333 Wh * 3000 / 1000 = 6999` đồng. Điều này sai quy tắc kế toán T-71. Phải cộng dồn từ đoạn).
