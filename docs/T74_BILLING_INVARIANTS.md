# S-30 / T-74 — 200 phiên kiểm tra bất biến tính tiền

`tests/test_t74_billing_invariants.py` sinh 200 phiên với seed gốc `7402026`.
Mỗi phiên có seed riêng bằng seed gốc cộng số ca; chạy riêng một ca vẫn
giữ nguyên đầu vào. Assertion in seed, múi giờ, đầu/cuối, số đo và biểu giá
đầy đủ để tái hiện khi lỗi.

- Số đo Wh nguyên tăng không giảm, đều hoặc thưa; gồm khoảng không tiêu thụ
  và phiên hoàn toàn 0 Wh. Số đo lẻ theo contract đã có test riêng T-72/T-73.
- Giờ bắt đầu bất kỳ, gồm các ranh chính xác và giây lẻ; thời lượng tới 30 giờ.
- UTC, UTC+7 và UTC+5:30; qua ngày/tháng và nhiều ngày khác biểu giá.
- Các biểu giá phủ kín mỗi ngày, nhiều khung, gồm đơn giá 0 và nửa đồng.

| Yêu cầu | Kiểm tra |
| --- | --- |
| Tổng Wh đoạn bằng Wh phiên | So với hiệu hai số đo đầu/cuối |
| Không hở/chồng | So ranh với tham chiếu độc lập; chỉ cho phép bỏ khoảng 0 Wh |
| Tổng tiền bằng tổng từng dòng | Kiểm tiền mỗi dòng bằng Decimal nửa lên độc lập rồi cộng |
| Tái hiện lỗi | Pytest ID và dữ liệu assertion chứa seed/ca/đầu vào |
| Dưới 10 giây trong CI | Test được bộ pytest CI hiện tại tự thu thập; đo thời gian khi chạy |

Tham chiếu nội suy dùng `Fraction` với thời gian nguyên giây, không gọi T-72,
T-71 hoặc T-73 để tạo đáp án. Đây là test bất biến bổ sung, không thay thế
bộ đáp án tính tay T-77/T-78 và không chứng minh toàn bộ S-30 đã Done.

Chạy: `pytest tests/test_t74_billing_invariants.py -q --durations=5`.
Chạy riêng: `pytest tests/test_t74_billing_invariants.py -q -k case-42`.
Không cần kết nối database; conftest vẫn yêu cầu DATABASE_URL đúng cú pháp.

## Kiểm chứng local ngày 09/10/2026

- Nền `develop`: `1014ad5`, đã gồm PR T-71 #93 và sửa T-73/T-75/T-76 #95–#97.
- 200 phiên T-74 đạt trong 0,52 giây; bộ T-71/T-72/T-73/T-74/T-76 gồm
  236 test đạt trong 0,44 giây.
- Ruff lint/format toàn repo, mypy file test mới và diff check đạt.
- Thử thay kết quả trong bộ nhớ: bỏ một đoạn, đổi Wh, làm chồng ranh và
  tăng thành tiền 1 đồng đều bị test phát hiện. Không sửa mã nghiệp vụ.
- Thời gian trên là đo local, chưa phải thời gian CI của thay đổi T-74.
  Không chạy lại toàn bộ test cần PostgreSQL; không suy ra S-30 đã Done.
