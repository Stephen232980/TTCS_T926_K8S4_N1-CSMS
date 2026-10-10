# T-92 — Cổng thanh toán giả lập

## Phạm vi và giới hạn

Adapter `FakeGateway`, trang thanh toán và bộ gửi webhook ký HMAC thuộc S-35/T-92. Năm nút gửi trạng thái thành công, thất bại, hủy, lặp năm lần và trễ mười giây đến route `/api/v1/payments/webhook` trên chính ứng dụng ASGI đang chạy.

Endpoint nhận trong PR #106 hiện chỉ kiểm tra chữ ký/schema, chưa ghi `WalletTopup`, chưa cộng ví và chưa có idempotency trong database. T-95/T-96 phải hoàn thiện nghiệp vụ này; các ca T-98 hiện chỉ chứng minh tiếp nhận/xác thực. Không dùng kết quả HTTP 200 hoặc năm lần tiếp nhận làm bằng chứng ví đã được cộng đúng một lần.

## Cấu hình

- `PAYMENT_GATEWAY=fake` bật adapter và simulator. Khi `disabled` hoặc `sandbox`, hai route `/payments/fake/pay` và `/payments/fake/dispatch` trả 404.
- `PAYMENT_WEBHOOK_SECRET` bắt buộc khi bật gateway; lấy từ môi trường, không xuất vào HTML/log. Webhook dùng HMAC-SHA256 trên chính bytes JSON UTF-8 gửi đi, header `X-Payment-Signature: sha256=<hex>`.
- `PAYMENT_FAKE_BASE_URL`: địa chỉ backend mà trình duyệt truy cập được, mặc định `http://localhost:8000`. Ví dụ backend demo cổng 8003 thì đặt `http://localhost:8003`; cấu hình riêng từng máy, không đổi cổng chung của nhóm.
- `PAYMENT_RETURN_URL`: URL frontend theo hợp đồng T-90/T-93. Bảo tồn query đã mã hóa và bổ sung `order_code`. Không giải mã URL lần thứ hai.
- Không bật `fake` tại môi trường có dữ liệu thật. Simulator có khả năng tạo các trạng thái thanh toán tùy chọn và chỉ dành cho kiểm thử.

## Liên kết và gửi webhook

`create_payment` cấp URL gồm order/amount/return URL, hạn dùng 30 phút và token ràng buộc các trường này. Token ký bằng namespace riêng với khóa server, tách khỏi chữ ký webhook. GET pay và POST dispatch kiểm tra token/hạn dùng; thiếu, hết hạn hoặc sửa order/amount/return URL đều bị chặn. Phải tạo link qua adapter/API T-93, không tự gõ URL thiếu token.

Dispatch chỉ nhận thông tin đã được ký cùng status/reason/repeat/delay. Không nhận `webhook_url` hoặc mã giao dịch do trình duyệt chỉ định. Callback dùng ASGITransport nội bộ tới endpoint đã đăng ký, không phụ thuộc cổng mạng, Host header hoặc nhánh đặc biệt dành cho testserver. Không cần bật kết nối HTTP đến localhost của container.

Mã giao dịch giả lập ổn định theo order; gửi lại dùng cùng mã và cùng raw body. Mỗi lần gửi phải có HTTP 2xx; lỗi mạng hoặc endpoint trả 3xx/4xx/5xx tạo lỗi 502 từ dispatch, không báo gửi thành công và không tự retry. Không trả chữ ký webhook cho trình duyệt. Nút bị khóa trong khi gửi; trang hiển thị kết quả tiếp nhận và hướng dẫn kiểm tra trạng thái đơn nạp sau khi quay về, không khẳng định đã cộng tiền.

Trang standalone dùng nền sáng, teal và typography của CSMS hiện có, hỗ trợ màn hình nhỏ, focus bàn phím và thông báo trạng thái đọc được bởi trình đọc màn hình. Liên kết không được cache, không gửi referrer chứa token.

## Kiểm thử

```powershell
python -m pytest tests/test_t92_fake_gateway.py tests/test_t92_gateway_hardening.py tests/test_t98_webhook_tests.py tests/test_t90_payment_contract.py tests/test_endpoint_policy_inventory.py -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

Các regression T-92 kiểm tra base URL khác cổng 8000, callback từ hostname thông thường, tamper/expiry, từ chối URL callback/mã giao dịch tùy ý, số tiền strict, HMAC đúng raw bytes có tiếng Việt, lặp cùng mã/body, delay 10 giây, lỗi HTTP/mạng và không lộ chữ ký. Kiểm thử ví/ledger thật và thứ tự trạng thái vẫn là acceptance của T-95/T-96/T-98.
