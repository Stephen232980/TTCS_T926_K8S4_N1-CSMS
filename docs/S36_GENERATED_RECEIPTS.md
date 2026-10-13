# S-36 — Phiếu nạp thủ công tự sinh

Backend bổ sung theo yêu cầu trưởng nhóm. AC gốc nạp theo mã phiếu nhập tay
vẫn được giữ; frontend được thực hiện riêng. Không thay đổi Jira hoặc yêu cầu
đã ghi trong workbook.

## Hợp đồng cho frontend

POST `/api/v1/admin/drivers/{driver_id}/wallet/manual-topups`, cookie session,
chỉ admin hoạt động. Khi admin đã kiểm tra khoản thu, tạo một UUID bằng
`crypto.randomUUID()` và gửi:

```json
{
  "amount_vnd": 100000,
  "request_id": "12345678-1234-4234-8234-123456789abc",
  "payment_received": true,
  "external_reference": "CHUNG-TU-001"
}
```

Không gửi `receipt_code`. `external_reference` là mã chứng từ tùy chọn,
không phải mã phiếu bắt buộc. Backend sinh mã
`PT-AUTO-12345678123442348234123456789abc` và trả mã cùng `ledger_id`,
`actor_id`, `created_at`, số tiền, số dư sau giao dịch và ba trường mới.

Giữ nguyên key/body sau timeout hoặc mất phản hồi. Retry trả cùng phiếu,
không cộng tiền lại; số dư trong response là snapshot ngay sau lần nạp gốc.
409 `manual_topup_request_conflict` nghĩa là key đã dùng cho nội dung/admin
khác; không tự đổi key rồi gửi lại. Chỉ dùng UUID mới cho khoản thu mới.

Luồng cũ gửi amount_vnd/receipt_code vẫn nhận 201, trùng mã vẫn 409. Không
trộn hai chế độ. Prefix PT-AUTO- được dành riêng hệ thống.

`payment_received=true` xác nhận lời khai của admin đã thu tiền bên ngoài,
không chứng minh tiền đã vào ngân hàng. Không nạp tay lại khoản VNPAY đã
cộng ví. Backend chưa tạo PDF/in phiếu hoặc tích hợp phần mềm kế toán.

## Coverage

| Yêu cầu | Thực hiện / kiểm chứng |
|---|---|
| AC gốc: admin-only, tiền hợp lệ, trùng mã bị chặn | Giữ API cũ và bộ test S-36 |
| Sinh mã, lưu người/thời gian/khoản thu | WalletLedger và audit cùng transaction |
| Xác nhận đã thu tiền | Strict boolean true bắt buộc ở chế độ sinh mã |
| Retry/concurrent không cộng trùng | Khóa theo request trước khóa ví; unique ledger; 8 request đồng thời |
| Key không chuyển khoản thu sang người/số tiền khác | 409 cho đổi tài xế, admin, amount hoặc external_reference |
| Lỗi audit không cộng tiền | Rollback và retry cùng key thành công một lần |
| Tiền/phiếu/audit bất biến | Không update/delete ledger/audit, giữ trigger hiện có |
| Phối hợp giao diện | Contract/example/errors trong API_CONTRACT.md; không sửa frontend |

Không thêm bảng/migration/quyền DB. Metadata mới nằm trong audit append-only
cùng ledger_id; sổ cái vẫn là nguồn tiền. Gửi lại không thêm audit nghiệp vụ.
