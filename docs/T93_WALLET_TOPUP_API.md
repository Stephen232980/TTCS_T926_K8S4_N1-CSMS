# T-93 — API tạo lệnh nạp ví và đọc trạng thái

Nhánh `feature/S-35-t93-wallet-topup-api` từ develop sau PR #102. Phụ thuộc T-90, T-91, T-85, T-06; không triển khai thay cổng giả lập T-92 hoặc webhook cộng ví T-95.

## API và quyền

| Method / path | Quyền | Scope | Vai trò |
|---|---|---|---|
| POST `/api/v1/driver/wallet/topups` | `driver.wallet.topup` | `own_wallet` | driver |
| GET `/api/v1/driver/wallet/topups/{order_id}` | `driver.wallet.topup.read` | `own_wallet` | driver |

Ví lấy từ tài xế đăng nhập, dùng cơ chế cấp ví T-85 khi chưa có ví. Không nhận wallet_id/driver_id từ body hoặc query; các selector này trả 403. Trường body khác ngoài amount_vnd trả 422. Tài khoản chưa đăng nhập trả 401; vai trò khác driver trả 403. GET chỉ tìm mã đơn cùng driver_id, trả 404 giống nhau cho lệnh lạ và lệnh của người khác.

## Tạo lệnh nạp

Body:

```json
{"amount_vnd": 100000}
```

Tiền phải là số nguyên JSON, dương và nằm trong ngưỡng bao gồm hai đầu. Float, bool, chuỗi số, số âm, số vượt BIGINT và ngoài ngưỡng đều trả 422 trước khi gọi gateway hoặc ghi lệnh nạp.

Hai biến mới:

- `WALLET_TOPUP_MIN_VND`: mặc định 10000.
- `WALLET_TOPUP_MAX_VND`: mặc định 5000000.

Settings kiểm hai ngưỡng dương, không vượt BIGINT và min <= max. `.env.example` và Compose app đã nhận hai biến này. Không thay đổi ngưỡng nạp tay của T-88 hoặc cổng local.

Trả 201 khi gateway cung cấp địa chỉ chuyển hướng:

```json
{
  "order_id": "topup-<uuid-hex>",
  "amount_vnd": 100000,
  "status": "pending",
  "reason": null,
  "created_at": "2026-10-09T00:00:00Z",
  "redirect_url": "https://gateway.example/pay/<order_id>"
}
```

`redirect_url` lấy từ PaymentRedirect của gateway, không tự tạo trong API. Backend truyền PAYMENT_RETURN_URL cấu hình sẵn; trình duyệt không được ghi đè. Mã đơn UUID có unique ở database T-91. Mỗi POST mới tạo một lệnh mới; chưa có cơ chế idempotency theo request của trình duyệt, nên frontend phải chặn gửi lặp khi đang gửi và không tự retry POST sau lỗi chưa rõ kết quả.

### Thứ tự transaction và timeout

1. Kiểm dữ liệu/quyền và adapter khả dụng.
2. Cấp/lấy ví của tài xế, ghi WalletTopup pending, commit lệnh.
3. Gọi PaymentGateway.create_payment với mã đơn đã lưu, tiền và URL quay về. Giải phóng transaction/khóa trước khi gọi mạng.
4. Giới hạn thời gian gọi gateway 10 giây. Khi có redirect, đọc lại trạng thái đã lưu trước khi trả; không ghi đè một trạng thái đã được webhook cập nhật nhanh.

Commit trước khi gọi gateway để webhook tới sớm vẫn tìm thấy lệnh. Nếu adapter báo PaymentGatewayUnavailable hoặc timeout, API trả 503 có `detail.order_id`; lệnh đã commit vẫn pending, không đánh dấu failed chỉ từ timeout. T-94 có thể GET trạng thái mã đơn đó. Không tự tạo lệnh mới để retry khi chưa biết lệnh cũ được cổng nhận chưa. Không phản hồi chi tiết exception/khóa/body từ gateway.

503 khi chưa có adapter không tạo lệnh, và không trả redirect giả. Pending sau lỗi mạng cần được xác nhận bằng webhook hoặc xử lý đối soát ở phần tiếp theo; T-93 không tự hết hạn/xác nhận thành công cho lệnh này.

Tạo lệnh nạp **không thay đổi số dư và không ghi sổ cái**. Việc xác thực webhook, chuyển trạng thái và cộng tiền thuộc T-95/T-96/T-97.

## API cho T-94

GET trả order_id, amount_vnd, status, reason và created_at; không trả redirect_url và không gọi gateway. Các trạng thái hỗ trợ: pending, succeeded, failed, cancelled, needs_review. T-94 lấy `order_code` trên URL quay về làm order_id để GET mỗi 3 giây, tối đa 2 phút, hiển thị trạng thái backend cùng lý do khi có. Tham số URL không là bằng chứng thanh toán.

## Điểm nối cho TV9 / T-92

`src/modules/payments/dependencies.py:get_payment_gateway()` là dependency của API. Hiện trả None vì chưa có adapter; API thật trả 503. TV9 bổ sung việc chọn FakeGateway khi PAYMENT_GATEWAY=fake, trả None khi disabled hoặc chưa có adapter sandbox. Không tự fallback sandbox sang fake.

Adapter cần thực hiện async create_payment(PaymentRequest) → PaymentRedirect, giữ nguyên mã đơn; verify_webhook theo contract T-90. Kiểm thử T-93 dùng dependency override và gateway thử, không đưa gateway thử vào source sản phẩm.

## Coverage / kiểm chứng local

| Yêu cầu | Kiểm chứng |
|---|---|
| Nạp 100.000: pending + redirect | PostgreSQL thực; gateway thử đọc thấy lệnh đã commit trước khi trả redirect |
| Ví theo tài xế và không cộng tiền | Kiểm số dư/sổ cái và tài xế thứ hai sau POST |
| Số tiền hợp lệ và ngưỡng cấu hình | Số âm, 0, số lẻ/float/bool/chuỗi, vượt BIGINT, ngoài ngưỡng; đúng min/max và min/max tùy chỉnh |
| Từ chối chỉ định ví/tài xế | Body và query trả 403 trước khi gọi gateway |
| Cookie/vai trò/quyền | 401/403 và inventory policy toàn bộ endpoint |
| Đọc trạng thái theo chủ sở hữu | Mã của người khác và mã lạ cùng 404; đọc đủ 5 trạng thái/lý do |
| Lệnh tới gateway nhanh hoặc lỗi mạng | Timeout thực, lỗi adapter, trạng thái cập nhật sớm không bị ghi đè; pending vẫn tồn tại |
| Khóa ngắn và mã đơn duy nhất | Gateway có thể lấy khóa user sau commit; ba POST đồng thời có ba mã khác nhau |

36 ca T-93 đạt. 83 ca liên quan T-90, inventory quyền, driver wallet, schema topup và provisioning đạt trong đợt kiểm tra trước; tổng 119 ca riêng biệt. Ruff lint/format toàn repo, mypy source và Compose config đạt. Dùng PostgreSQL 16 riêng, không thay đổi database demo. Không cần migration mới.

Chưa kiểm chứng adapter T-92, webhook T-95, UI T-94 hoặc staging. Đây là bằng chứng API và contract, không phải nghiệm thu hoàn chỉnh luồng nạp tiền.
