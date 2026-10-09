# S-30 / T-71 — Làm tròn tiền dùng chung

`src.modules.billing.money.tien_dong(energy_wh, price_vnd_per_kwh)` là hàm
thuần, trả `int` đồng theo công thức Wh × đơn giá đồng/kWh / 1000, làm tròn
nửa lên ở từng đoạn. `chia_doan` gọi hàm này cho mỗi đoạn; tổng phiên cộng
các thành tiền đã làm tròn, không làm tròn lại từ tổng Wh.

- Wh nhận `int` theo yêu cầu T-71 và `Decimal` hữu hạn để tương thích hợp
  đồng T-70/T-73 hiện tại. Hàm không thay đổi hay làm tròn Wh đầu vào.
- Đơn giá nhận `int`; từ chối `float`, `bool` và kiểu sai bằng `TypeError`.
  Wh NaN/vô cực bị từ chối bằng `ValueError`.
- Phép nhân/chia và làm tròn dùng số nguyên chính xác; không phụ thuộc độ
  chính xác của Decimal context, không dùng số thực nhị phân. Với số âm,
  điểm nửa làm tròn ra xa 0 như `ROUND_HALF_UP`; tầng nghiệp vụ chịu trách
  nhiệm kiểm tra số đo/biểu giá hợp lệ.
- Ví dụ: 1 Wh × 2.500 → 3 đồng; 3 Wh × 2.500 → 8 đồng;
  5 Wh × 3.800 → 19 đồng; 0 Wh → 0 đồng.
- Hai đoạn 1.166,5 Wh × 3.000 cho 3.500 + 3.500 = 7.000 đồng;
  tính một lần từ 2.333 Wh sẽ ra 6.999 đồng và không đúng quy tắc cộng đoạn.

| Tiêu chí T-71 | Bằng chứng kiểm thử |
| --- | --- |
| Các ví dụ làm tròn, Wh bằng 0 | `test_rounding_table` |
| Số lớn không tràn, không mất chữ số | Bảng số nguyên lớn và `test_decimal_context_does_not_change_amount_or_input` |
| Không nhận float cho tiền | Test kiểu Wh/đơn giá không hợp lệ |
| Dùng chung và làm tròn từng đoạn | `test_chia_doan_uses_common_rounding_for_each_segment` |

Chạy `pytest tests/test_t71_money.py tests/test_t72_interpolation.py
tests/test_t73_segmentation.py tests/test_t76_daily_billing.py -q`.
Các hàm thuần này không cần kết nối PostgreSQL; conftest vẫn cần một
`DATABASE_URL` có cú pháp hợp lệ.

Quyết định chuẩn hoá Wh nguyên tại ranh thuộc T-70/T-73; T-71 giữ hành vi
Wh hiện có. T-74 và việc bỏ dòng 0 Wh của T-73 không thuộc thay đổi này.
