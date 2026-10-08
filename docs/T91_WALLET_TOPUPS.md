# T-91 bảng giao dịch nạp ví

T-91 thuộc S-35, chỉ bổ sung schema giao dịch nạp. API tạo lệnh, xác thực
webhook, chuyển trạng thái và cộng ví do các task tiếp theo triển khai.
Schema không thay đổi số dư ví. Phạm vi dựa trên Backlog CSMS S-35/S-39
và dòng T-91 của Chia_viec_Sprint_4-5_cap_nhat.xlsx.

## Hợp đồng dữ liệu

`WalletTopup` nằm ở `src.modules.wallet.topup_models`. Bảng `wallet_topups`
lưu UUID `id`, `driver_id` tham chiếu users với RESTRICT, BIGINT `amount_vnd`
dương, `order_id` duy nhất toàn bảng, `gateway_transaction_id` duy nhất toàn
bảng nhưng cho phép NULL khi chưa nhận mã cổng, `reason` tùy chọn và hai
mốc `created_at`, `updated_at` có múi giờ. Không tự tạo dòng sổ cái.

Trạng thái: `pending` (chờ, mặc định), `succeeded` (thành công), `failed`
(thất bại), `cancelled` (huỷ), `needs_review` (cần xem xét). T-97 sở hữu quy
tắc chuyển trạng thái; T-91 chỉ giới hạn tập giá trị. `updated_at` được ORM
cập nhật khi sửa; bên ghi SQL trực tiếp phải đặt mốc này rõ ràng.

Giới hạn số tiền mỗi lần và kiểm số tiền lẻ ở request thuộc T-93. Mã đơn
và mã cổng không được rỗng hoặc chỉ có khoảng trắng. Chỉ mục theo tài xế
và thời điểm phục vụ truy vấn lịch sử. Mã định danh dài tối đa 128 ký tự.

## Ma trận kiểm chứng

| Yêu cầu T-91 | Cài đặt | Bằng chứng |
| --- | --- | --- |
| Lưu đủ giao dịch, trạng thái và lý do | Model và migration | Test mặc định, cập nhật trạng thái/lý do, năm trạng thái |
| Mã đơn không trùng | Unique tại database | Test trùng giữa hai tài xế |
| Mã giao dịch cổng không trùng, cho phép chưa có | Unique nullable | Test trùng giữa hai tài xế và hai dòng NULL |
| Dữ liệu tài chính hợp lệ | BIGINT, FK RESTRICT, check | Test số lớn, âm/0, trạng thái lạ, mã rỗng, FK và xoá tài xế |
| Migration tiến/lùi | f130014a2026 sau e120013a2026 | Upgrade/downgrade/upgrade trên PostgreSQL riêng |

Không coi phần schema này là nghiệm thu toàn bộ S-35 hoặc S-39. Chống cộng
ví hai lần, chữ ký webhook và cổng thanh toán không nằm trong T-91.

Downgrade xoá bảng giao dịch nạp; chỉ kiểm thử trên database riêng. Không
downgrade database chứa dữ liệu nghiệp vụ khi chưa có kế hoạch sao lưu.

## Kết quả local ngày 08 tháng 10 năm 2026

Baseline `origin/develop`: `2419b8b`. Ruff check và format check đạt;
mypy đạt trên 83 file source; Alembic có một head `f130014a2026` và sinh
SQL upgrade/downgrade thành công.

Sau khi Docker hoạt động, đã kiểm chứng trên PostgreSQL 16 trong container
riêng `csms-t91-test-20261008`, cổng loopback 55491, database `t91_test`:

- Upgrade từ database rỗng đến head thành công.
- 14 test `test_wallet_topup_schema.py` đạt.
- Downgrade về `e120013a2026` thành công; truy vấn xác nhận bảng
  `wallet_topups` không còn; upgrade lại đến head thành công.
- Sau vòng migration, test T-91 và `test_wallet_schema.py`: 41 passed,
  3 cảnh báo deprecation từ fixture event loop có sẵn.
- Alembic current là `f130014a2026 (head)`; `git diff --check` đạt.

Kết nối dùng `127.0.0.1` với `connect_timeout=10` vì kết nối `localhost`
bị chờ trên máy này. Không thay đổi database ứng dụng hoặc cấu hình dự án.
Chưa có bằng chứng CI, review hoặc nghiệm thu toàn bộ story.
