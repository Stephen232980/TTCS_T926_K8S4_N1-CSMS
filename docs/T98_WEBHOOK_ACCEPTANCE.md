# T-98 — Acceptance webhook với FakeGateway

Thuộc S-39, tiếp nối bộ kiểm thử đã merge cùng T-92 trong PR #106. Phần bổ sung chạy trên nền T-95/T-96/T-97, giữ nguyên đóng góp ban đầu và không thay đổi API, migration hoặc nghiệp vụ thanh toán.

## Phạm vi bằng chứng

`tests/test_t98_webhook_tests.py` giữ các ca receiver ban đầu, bổ sung biến thể `cancelled`, chữ ký trùng khác kiểu chữ và kiểm tra callback lỗi trên đơn thực sự tồn tại.

`tests/test_t98_simulator_acceptance.py` tạo người dùng/session thật, gọi API tạo đơn để nhận link thanh toán đã ký, mở trang FakeGateway và gửi qua dispatch thật tới webhook. Không thay thế gateway, xác thực hay settlement bằng mock. Mỗi lần kiểm tra dùng session PostgreSQL mới và đối chiếu API đơn nạp, ví, lịch sử giao dịch.

| Nhóm | Kết quả cần chứng minh |
| --- | --- |
| Thành công/thất bại/hủy | Gửi lặp 5 lần rồi thêm 5 lần; mã giao dịch ổn định; chỉ thành công tăng số dư và có đúng một ledger |
| Sai thứ tự | Thành công rồi thất bại/hủy vẫn thành công; thất bại/hủy rồi thành công chuyển `needs_review`, không cộng tiền; mỗi loại cảnh báo chỉ ghi một lần |
| Đồng thời | 5 dispatch chạy đồng thời, mỗi dispatch gửi 5 callback; 25 callback vẫn chỉ cộng một lần |
| Trễ | Chờ thật 10 giây; trước callback đơn còn pending, ví và ledger chưa tăng; sau đó thành công đúng một lần |
| Xác thực/schema | Thiếu/sai chữ ký trả 401; payload sai trả 400; trạng thái, ví và ledger không thay đổi |
| Đơn không tồn tại | 5 callback trả 404 và có một cảnh báo; simulator chuyển lỗi receiver thành 502 |
| Sai số tiền | Pending/failed/cancelled chuyển review; succeeded được giữ; không thêm tiền/ledger; cảnh báo được gom |
| Đơn review | Vẫn kiểm tra chữ ký và số tiền trước; callback hợp lệ giữ review, không tự khôi phục settlement |
| Bảo mật cảnh báo | Có IP khi chữ ký lỗi; không lộ secret, chữ ký, raw payload hoặc lý do riêng của gateway |

## Chạy kiểm thử

Dùng PostgreSQL riêng cho test, đặt `DATABASE_URL`, chạy migration lên head rồi:

```powershell
python -m pytest tests/test_t98_webhook_tests.py tests/test_t98_simulator_acceptance.py -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

Full suite cần database test sạch riêng vì một số regression kiểm tra baseline audit. Không xóa ledger/audit hoặc tắt trigger để tái sử dụng dữ liệu. Các test kiểm tra trạng thái dùng điều kiện chờ sự kiện; ca delay giữ thời gian chờ thật.

Đây là bằng chứng HTTP/ASGI và PostgreSQL cho FakeGateway. Kết quả không xác nhận cổng thanh toán bên ngoài, trình duyệt staging hay trạng thái Done trên Jira. Hợp đồng xử lý lỗi và gom cảnh báo được mô tả tại [T-97](T97_WEBHOOK_ERRORS.md).
