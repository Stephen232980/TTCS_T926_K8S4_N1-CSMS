# T-92 — Cổng thanh toán giả lập (FakeGateway) và Webhook Simulator

T-92 triển khai adapter `FakeGateway` cho `PaymentGateway` (S-35), trang thanh toán mô phỏng HTML và endpoint nhận thử webhook (T-95/S-39), phục vụ kiểm thử end-to-end quy trình nạp tiền ví tài xế mà không cần cổng thanh toán thật.

## 1. Cấu hình và điều kiện kích hoạt

| Biến môi trường | Giá trị yêu cầu | Ý nghĩa |
|---|---|---|
| `PAYMENT_GATEWAY` | `fake` | Bật adapter và route mô phỏng. Khi khác `fake` (e.g. `disabled`, `sandbox`), tất cả route giả lập trả HTTP 404. |
| `PAYMENT_WEBHOOK_SECRET` | Chuỗi secret | Khóa bí mật dùng để ký HMAC-SHA256 trên toàn bộ bytes body webhook. Không đưa khóa vào frontend hoặc log. |
| `PAYMENT_RETURN_URL` | URL frontend | URL quay về sau khi hoàn tất thanh toán. Mặc định: `http://localhost:5173/wallet/topup/return`. |

## 2. Các thành phần triển khai

### Adapter `FakeGateway` (`src/modules/payments/fake_gateway.py`)
- Cài đặt giao diện `PaymentGateway`:
  - `create_payment(request: PaymentRequest) -> PaymentRedirect`: Tạo đường dẫn chuyển hướng sang trang thanh toán giả lập `GET /api/v1/payments/fake/pay` kèm query parameters `order_id`, `amount_vnd`, `return_url`.
  - `verify_webhook(raw_body: bytes, headers: Mapping[str, str]) -> GatewayEvent`: Xác thực chữ ký `X-Payment-Signature` (HMAC-SHA256) trên đúng raw body bytes trước khi parse JSON sang `GatewayEvent`. Nếu sai chữ ký ném `InvalidWebhookSignature` (HTTP 401); nếu payload sai schema ném `InvalidWebhookPayload` (HTTP 400).
- Nối `FakeGateway` vào `src/modules/payments/dependencies.py:get_payment_gateway()`: Trả về `FakeGateway` khi `PAYMENT_GATEWAY=fake`, trả `None` khi `disabled` hoặc `sandbox`.
- Helper `build_return_url(return_url, order_id)`: Nối query parameter `order_code=<order_id>` vào return URL trong khi giữ nguyên các query parameter có sẵn.

### Trang thanh toán giả lập (`GET /api/v1/payments/fake/pay`)
- Hiển thị thông tin đơn nạp: Mã đơn hàng (`order_id`), Số tiền nạp (`amount_vnd`).
- Gồm đầy đủ 5 nút tương tác:
  1. **Thành công** (`succeeded`): Gửi webhook trạng thái thành công.
  2. **Thất bại** (`failed`): Gửi webhook trạng thái thất bại kèm lý do.
  3. **Hủy** (`cancelled`): Gửi webhook trạng thái hủy giao dịch.
  4. **Gửi lại webhook 5 lần** (`repeat_count=5`): Mô phỏng gửi lại cùng mã giao dịch `gateway_transaction_id` và cùng dữ liệu để kiểm thử tính idempotent (chống trùng).
  5. **Trễ webhook 10 giây** (`delay_seconds=10`): Mô phỏng độ trễ mạng hoặc tình huống polling trạng thái pending.
- Liên kết / Chuyển hướng quay về ứng dụng tài xế: `PAYMENT_RETURN_URL` với `order_code=<order_id>`.

### Endpoint kích hoạt Webhook (`POST /api/v1/payments/fake/dispatch`)
- Nhận yêu cầu từ trang thanh toán, thực hiện ký HMAC-SHA256 phía server (bảo mật khóa bí mật) và gửi webhook tới endpoint backend.

### Endpoint nhận Webhook thử nghiệm (`POST /api/v1/payments/webhook`)
- Tiếp nhận webhook, kiểm tra chữ ký HMAC (`X-Payment-Signature`), xác thực payload `GatewayEvent`. Không tự cộng tiền vào ví (phần cập nhật ví và chống trùng thuộc T-95/T-96).

## 3. Kiểm thử (T-92 & T-98)

- `tests/test_t92_fake_gateway.py` (10 test cases):
  - Kiểm tra `build_return_url` bảo tồn query và nối `order_code`.
  - Kiểm tra `FakeGateway.create_payment` tạo URL chuyển hướng hợp lệ.
  - Kiểm tra `get_payment_gateway()` trả đúng instance theo cấu hình.
  - Kiểm tra trả 404 cho mọi route giả lập khi `PAYMENT_GATEWAY != 'fake'`.
  - Kiểm tra giao diện HTML trang thanh toán render đủ 5 nút, thông tin đơn và không lộ secret.
  - Kiểm tra dispatch webhook gửi đúng chữ ký, lặp 5 lần cùng transaction ID, và cơ chế trễ.
- `tests/test_t98_webhook_tests.py` (10 test cases):
  - 9 ca kiểm thử chuẩn mực cho Webhook simulator:
    1. Webhook thành công hợp lệ (`succeeded`).
    2. Webhook sai chữ ký -> 401.
    3. Webhook thiếu header chữ ký -> 401.
    4. Webhook có nhiều hơn 1 header chữ ký trùng lặp -> 401.
    5. Webhook sai payload schema -> 400.
    6. Webhook thất bại hợp lệ kèm lý do (`failed`).
    7. Webhook hủy hợp lệ kèm lý do (`cancelled`).
    8. Trạng thái thất bại/hủy sau khi đã có giao dịch thành công.
    9. Trạng thái thành công sau khi đã có giao dịch thất bại.
  - Ca kiểm thử replay lặp lại 5 lần cùng giao dịch (Idempotency verification).
