# T-90 — Contract cổng thanh toán

T-90 cung cấp contract để T-92 (cổng giả lập), T-93 (tạo lệnh nạp), T-95 (webhook) và T-94 (trang quay về) dùng chung. Hiện luồng dự kiến dùng **cổng giả lập**; cổng thanh toán sandbox thật thuộc **S-67**. T-90 chưa triển khai adapter, route thanh toán hay cộng ví.

## Ba biến môi trường

| Biến | Giá trị / quy tắc |
|---|---|
| `PAYMENT_GATEWAY` | `disabled` (mặc định), `fake` (local/test), `sandbox` (adapter S-67). Không có adapter tương ứng thì báo không khả dụng, không tự rơi về fake. |
| `PAYMENT_WEBHOOK_SECRET` | Khóa bí mật từ môi trường. Bắt buộc khi chọn fake/sandbox; không có khóa mặc định. Không commit khóa thật và không ghi khóa vào log. |
| `PAYMENT_RETURN_URL` | URL frontend cấu hình ở backend. Local: `http://localhost:5173/wallet/topup/return`. Chỉ HTTP/HTTPS, không chứa username/password hoặc fragment. |

`Settings` và Compose app đã nhận ba biến. `.env.example` để cổng disabled và khóa trống để ứng dụng hiện có vẫn khởi động. Bật fake chỉ trên môi trường thử; môi trường dùng dữ liệu thật phải tắt fake. T-92 chỉ đăng ký route giả lập khi chọn fake; những chế độ khác trả 404 cho route giả lập. Việc chọn sandbox chưa có nghĩa là adapter thật đã được triển khai.

Tạo khóa riêng cho local bằng `python -c "import secrets; print(secrets.token_hex(32))"`, lưu vào `.env` đã được bỏ qua bởi Git. Khi chia sẻ lỗi cấu hình, không ghi giá trị biến hoặc nội dung input của ValidationError vào log.

## Hai hàm

Contract Python: `src/modules/payments/contracts.py`.

```python
class PaymentGateway(Protocol):
    async def create_payment(self, request: PaymentRequest) -> PaymentRedirect: ...
    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> GatewayEvent: ...
```

### Tạo thanh toán

`PaymentRequest`: `order_id` (chuỗi 1–128 ký tự), `amount_vnd` (số nguyên dương <= BIGINT), `return_url` (HttpUrl). Không nhận số thực, bool hoặc chuỗi thay cho số tiền. Mã không chứa khoảng trắng ở hai đầu hoặc ký tự điều khiển. Không trim mã để tránh làm hai mã khác nhau thành một.

`PaymentRedirect`: `redirect_url` (HttpUrl). Không bao gồm số dư hoặc kết quả thanh toán. Adapter truyền nguyên `order_id` cho cổng và dùng cùng mã khi retry; không tạo một lệnh nạp mới chỉ vì HTTP timeout. T-93 lưu giao dịch pending và chủ ví trước khi gọi adapter, dùng `PAYMENT_RETURN_URL` từ backend, không lấy URL tùy ý từ trình duyệt.

Ví dụ gọi (khi T-92 đã cung cấp adapter):

```python
request = PaymentRequest(
    order_id=topup.order_id,
    amount_vnd=topup.amount_vnd,
    return_url=settings.payment_return_url,
)
redirect = await gateway.create_payment(request)
```

### Xác thực webhook

Nhận **bytes gốc** và mapping header; kiểm chữ ký trước khi đọc JSON. Chỉ trả `GatewayEvent` đã được xác thực/chuẩn hóa, không cập nhật database hay ví trong adapter.

| Trường sự kiện | Kiểu / quy tắc |
|---|---|
| `gateway_transaction_id` | Chuỗi 1–128 ký tự; giữ nguyên khi gửi lại cùng giao dịch |
| `order_id` | Mã đơn của T-93, khớp `wallet_topups.order_id` |
| `amount_vnd` | Số nguyên dương đồng Việt Nam; phải kiểm khớp số tiền đã lưu ở T-95 |
| `status` | `succeeded`, `failed`, `cancelled` |
| `reason` | Tùy chọn, chuỗi tối đa 500 ký tự; diễn giải an toàn cho thất bại/hủy |

`pending` và `needs_review` là trạng thái nội bộ của CSMS, không phải sự kiện kết quả từ cổng. Model từ chối trường thừa. Trạng thái thành công trong webhook không đủ để cộng ví: T-95 còn kiểm mã đơn/số tiền, T-96 kiểm chống trùng, T-97 kiểm chuyển trạng thái. Dùng `gateway_transaction_id` làm tham chiếu sổ cái theo contract T-95/T-86.

## Chữ ký của cổng giả lập T-92

- Header duy nhất: `X-Payment-Signature`; tên header không phân biệt hoa thường.
- Giá trị: `sha256=` nối 64 ký tự hex **chữ thường** của HMAC-SHA256.
- Key: UTF-8 của `PAYMENT_WEBHOOK_SECRET`. Message: toàn bộ bytes HTTP body, không parse, trim, đổi thứ tự thuộc tính hoặc serialize lại trước khi kiểm.
- So sánh bằng `hmac.compare_digest`. Helper `verify_hmac_sha256` có sẵn trong `src/modules/payments/signatures.py`.
- Thiếu/sai/malformed chữ ký: `InvalidWebhookSignature`; cùng thông báo chung, không phản hồi chữ ký hoặc body.
- Endpoint phải từ chối nhiều header chữ ký (`request.headers.getlist(...)`) trước khi chuyển sang mapping, vì mapping có thể làm mất các giá trị header trùng.
- Chỉ sau khi helper đạt mới parse JSON và dựng GatewayEvent; lỗi schema/JSON đổi thành `InvalidWebhookPayload` với thông báo chung. Không trả trực tiếp ValidationError chứa dữ liệu gốc.

Ví dụ webhook mẫu (không có newline cuối):

```json
{"gateway_transaction_id":"fake-tx-1","order_id":"topup-1","amount_vnd":100000,"status":"succeeded"}
```

Tạo header từ đúng mẫu bytes, lấy khóa ở môi trường:

```python
import hashlib
import hmac
import os

body = b'{"gateway_transaction_id":"fake-tx-1","order_id":"topup-1","amount_vnd":100000,"status":"succeeded"}'
signature = "sha256=" + hmac.new(
    os.environ["PAYMENT_WEBHOOK_SECRET"].encode("utf-8"),
    body,
    hashlib.sha256,
).hexdigest()
headers = {"Content-Type": "application/json", "X-Payment-Signature": signature}
# Gửi chính body này, không truyền json=... rồi giữ chữ ký cũ.
```

Thất bại/hủy dùng cùng cấu trúc với status `failed`/`cancelled` và reason. Gửi lại webhook giữ nguyên mã giao dịch, mã đơn, số tiền và kết quả. HMAC chứng minh nguồn gửi; không tự chống replay. T-96 đảm nhiệm chống trùng ở database.

Đây là quy tắc chữ ký của **fake**. Adapter sandbox S-67 xác thực theo tài liệu cổng thật rồi chuẩn hóa về cùng GatewayEvent; không mặc định cổng thật cũng dùng chữ ký này.

## Quy ước tích hợp cho các task tiếp theo

Các endpoint dưới đây là quy ước để triển khai sau, **chưa có route hoạt động trong T-90**:

- T-93: `POST /api/v1/driver/wallet/topups`, lấy tài xế từ phiên đăng nhập và trả order_id, trạng thái pending, redirect_url. Kiểm ngưỡng tiền 10.000–5.000.000 theo cấu hình T-93 trước khi gọi gateway.
- T-94: `GET /api/v1/driver/wallet/topups/{order_id}` để hỏi trạng thái; backend kiểm đúng chủ ví, không cho đọc lệnh của người khác.
- T-95: `POST /api/v1/payments/webhook`, công khai và xác thực bằng chữ ký, không yêu cầu cookie. Bản giả lập T-92 gửi tới endpoint này; dùng URL backend hiện có theo môi trường, không thêm biến thứ tư trong T-90. Nếu T-92 gửi qua HTTP từ container, dùng địa chỉ backend nội bộ phù hợp.
- Trang quay về: `/wallet/topup/return?order_code=<URL-encoded-order_id>`. `order_code` trên URL là cùng giá trị với `order_id` của backend, không phải một mã khác. Adapter nối query bằng công cụ xử lý URL để không làm mất query cấu hình sẵn.
- T-94 hỏi trạng thái mỗi 3 giây, tối đa 2 phút; chờ webhook khi còn pending, hiện lý do cho failed/cancelled. Không dựa vào tham số status trên URL để cộng tiền hoặc kết luận thành công.

## Lỗi và trách nhiệm

| Tình huống | Exception / mã HTTP tại endpoint triển khai sau |
|---|---|
| Cổng disabled, chưa có adapter, timeout/lỗi gọi cổng | `PaymentGatewayUnavailable` → 503, phản hồi chung không lộ cấu hình |
| Thiếu/sai chữ ký | `InvalidWebhookSignature` → 401 |
| Chữ ký đúng nhưng JSON/schema không hợp lệ | `InvalidWebhookPayload` → 400 |
| Không có mã đơn | T-95/T-97 → 404 |
| Số tiền lệch | T-95/T-97 → 400, không cộng ví; needs_review |
| Webhook trùng | T-96 → 200, không cộng lần nữa |

Adapter phải chuyển lỗi SDK/network/parser sang exception contract; không gắn body, header chữ ký, khóa hoặc dữ liệu SDK vào thông báo lỗi. T-95 không log body/header; cảnh báo chỉ ghi mã đơn/mã giao dịch đã xác thực và thông tin cần thiết theo task. Việc ghi trạng thái/sổ cái trong một transaction database thuộc T-95/T-96, không thuộc gateway.

## Kiểm chứng và giới hạn

38 test contract/cấu hình/chữ ký đạt: đọc ba biến môi trường, bật cổng thiếu khóa, che khóa, dữ liệu tiền/mã/trạng thái/URL, HMAC đúng bytes, sai key/body, header thiếu/sai/trùng và ví dụ webhook. Không cần migration hoặc database cho T-90. Chưa có cổng giả lập, polling UI, cộng ví hoặc tích hợp sandbox thật.

Kiểm tra bổ sung: tổng 55 ca contract, CI pipeline, identity schemas, simulator config, database session giả lập và HTTP root/liveness đạt; Ruff lint/format, mypy 99 source, Compose config và diff check đạt. Không chạy full suite database trong T-90.
