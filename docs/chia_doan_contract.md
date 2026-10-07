# Hợp đồng hàm `chia_doan` (Task T-70)

Tài liệu này định nghĩa giao diện (interface) và các ví dụ (test cases) cho hàm `chia_doan` thuộc Story S-30.

## 1. Hợp đồng (Signature / Interface)

### Cấu trúc Dữ liệu Đầu vào (Input)

```python
from typing import List, Dict
from datetime import datetime, date


class MeterValue:
    def __init__(self, timestamp: datetime, energy_kwh: float):
        self.timestamp = timestamp
        self.energy_kwh = energy_kwh


class TariffFrame:
    def __init__(self, start_time: str, end_time: str, price: float):
        # start_time, end_time định dạng "HH:MM:SS"
        self.start_time = start_time
        self.end_time = end_time
        self.price = price


def chia_doan(
    session_start: datetime,
    session_end: datetime,
    meter_values: List[MeterValue],
    daily_tariffs: Dict[date, List[TariffFrame]],
) -> List[Dict]:
    """
    Hàm thuần cắt phiên sạc thành các đoạn dựa trên ranh giới khung giờ biểu giá và ranh giới nửa đêm.

    :param session_start: Thời gian bắt đầu phiên sạc.
    :param session_end: Thời gian kết thúc phiên sạc.
    :param meter_values: Danh sách các bản ghi chỉ số công tơ điện trong suốt phiên sạc.
    :param daily_tariffs: Ánh xạ từ ngày (date) sang danh sách các khung giá trong ngày đó.
    :return: Danh sách các đoạn sạc đã được chia nhỏ, bao gồm thời gian, kWh, đơn giá và thành tiền.
    """
    pass
```

### Cấu trúc Dữ liệu Đầu ra (Output)

Hàm sẽ trả về một List các Dictionary (mỗi Dict đại diện cho một đoạn sạc):

```python
[
    {
        "start_time": datetime,  # Bắt đầu đoạn
        "end_time": datetime,  # Kết thúc đoạn
        "energy_consumed_kwh": float,  # Lượng điện tiêu thụ trong đoạn (được nội suy nếu cần)
        "price_per_kwh": float,  # Đơn giá áp dụng cho đoạn này
        "total_cost": float,  # Thành tiền của đoạn (đã làm tròn)
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
    *   Sạc từ `2023-10-25 10:00:00` đến `2023-10-25 11:00:00`.
    *   Chỉ số điện: Tại `10:00:00` là `100 kWh`, tại `11:00:00` là `120 kWh`.
    *   Biểu giá: `08:00:00 - 12:00:00` giá `3000 đ/kWh`.
*   **Output kỳ vọng**:
    *   1 đoạn duy nhất: Từ 10:00 đến 11:00, tiêu thụ 20 kWh, giá 3000 đ/kWh, thành tiền 60.000 đ.

### Ví dụ 2: Phiên sạc cắt qua 2 khung giờ trong cùng 1 ngày
*   **Mô tả**: Phiên sạc giao với mốc thay đổi giá, cần chia làm 2 đoạn.
*   **Input**:
    *   Sạc từ `2023-10-25 21:30:00` đến `2023-10-25 23:30:00`.
    *   Mốc đổi giá lúc `22:00:00`.
    *   Giá `20:00-22:00` là `4000 đ/kWh`, `22:00-00:00` là `2000 đ/kWh`.
    *   MeterValue tại `21:30:00` là `10 kWh`, tại `22:00:00` là `30 kWh`, tại `23:30:00` là `50 kWh`.
*   **Output kỳ vọng**:
    *   Đoạn 1: 21:30 - 22:00 (20 kWh), giá 4000, thành tiền 80.000.
    *   Đoạn 2: 22:00 - 23:30 (20 kWh), giá 2000, thành tiền 40.000.

### Ví dụ 3: Phiên sạc vắt qua nửa đêm
*   **Mô tả**: Sạc từ đêm hôm trước sang ngày hôm sau, phải cắt tại `00:00:00`.
*   **Input**:
    *   Sạc từ `2023-10-25 23:00:00` đến `2023-10-26 01:00:00`.
    *   Biểu giá ban đêm (từ 22:00 hôm trước tới 04:00 hôm sau) là `2000 đ/kWh`.
    *   Mặc dù cùng giá, nhưng vẫn phải cắt chốt tại `00:00:00` để map đúng biểu giá của từng ngày.
*   **Output kỳ vọng**:
    *   Đoạn 1: 23:00 - 00:00 (thuộc ngày 25).
    *   Đoạn 2: 00:00 - 01:00 (thuộc ngày 26).

### Ví dụ 4: Không có số đo đúng mốc (Yêu cầu nội suy tuyến tính)
*   **Mô tả**: Giống ví dụ 2 (cắt lúc 22:00), nhưng CSMS không nhận được bản tin MeterValue lúc đúng 22:00.
*   **Input**:
    *   Mốc đổi giá lúc `22:00:00`.
    *   MeterValue có tại: `21:50:00` là `40 kWh`, `22:10:00` là `60 kWh`. (Chênh nhau 20 phút, 20 kWh).
*   **Output kỳ vọng (Nội suy)**:
    *   Lúc `22:00:00` (ở giữa) sẽ được tính nội suy: `40 + (60 - 40) * (10 phút / 20 phút) = 50 kWh`.
    *   Đoạn 1 lấy chỉ số kết thúc là 50 kWh. Đoạn 2 lấy chỉ số bắt đầu là 50 kWh.

### Ví dụ 5: Có số đo đúng mốc (Không cần nội suy)
*   **Mô tả**: Trùng với điểm cắt, trạm sạc gửi đúng một bản tin MeterValue.
*   **Input**:
    *   Cắt lúc `22:00:00`. Có MeterValue chính xác lúc `22:00:00` báo 50 kWh.
*   **Output kỳ vọng**:
    *   Lấy luôn giá trị 50 kWh mà không thực hiện phép tính nội suy nào, đảm bảo độ chính xác tuyệt đối từ phần cứng.

### Ví dụ 6: Sai số làm tròn tiền
*   **Mô tả**: Kiểm tra quy tắc làm tròn (làm tròn từng đoạn rồi cộng).
*   **Input**:
    *   Đoạn 1: Tiêu thụ 1.333 kWh, Giá 3000 đ/kWh => Tính ra: 3999.0 đ
    *   Đoạn 2: Tiêu thụ 1.333 kWh, Giá 3000 đ/kWh => Tính ra: 3999.0 đ
    *   Tổng phiên (nếu không chia đoạn): 2.666 kWh * 3000 = 7998.0 đ
    *   Giả sử quy tắc làm tròn đến hàng đơn vị.
*   **Output kỳ vọng**:
    *   Hóa đơn sẽ ghi nhận: Đoạn 1 = 3999 đ, Đoạn 2 = 3999 đ. Tổng = 7998 đ. Phải khớp logic tính của kế toán, làm tròn tại cấp độ đoạn (segment level) rồi dùng phép cộng đơn giản, tránh trường hợp tổng từng dòng không bằng dòng tổng cộng.
