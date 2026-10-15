# S-57: Tối ưu query/clean up dữ liệu định kỳ & lưu trữ (Data Retention, Cleanup Pipeline & Privacy Anonymization)

## 1. Tổng quan & Mục tiêu

Story **S-57** hoàn thiện giải pháp toàn diện cho:
1. **Chính sách lưu trữ & dọn dẹp dữ liệu tạm thời (Data Retention Policies & Cleanup Pipeline)**:
   - Dọn dẹp định kỳ và theo yêu cầu các dữ liệu tạm thời, bản ghi snapshot, nhật ký IP lỗi, phiên web đã thu hồi, mẫu telemetry OCPP, email cảnh báo và mẫu đo sức khỏe hệ thống.
   - Giảm tải dung lượng database và tối ưu query scan/index cho PostgreSQL.
2. **Quyền riêng tư & Ẩn danh hóa an toàn (Privacy Anonymization / Right to be Forgotten)**:
   - Nghiêm cấm hoàn toàn hành vi xóa cứng (`DELETE`) đối với các bảng tài chính cốt lõi: `invoices`, `wallets`, `wallet_ledger`, `charging_sessions`.
   - Áp dụng kỹ thuật **Soft Anonymization**: cập nhật `user.status = 'anonymized'`, mã hóa/thay thế email `anonymized_{uuid[:12]}@deleted.local`, vô hiệu hóa hash mật khẩu, thu hồi toàn bộ phiên làm việc và vai trò.
   - Giữ nguyên các khóa ngoại `driver_id` và trigger bất biến tài chính để phục vụ đối soát, kiểm toán kế toán.
3. **Cơ chế Tạm giữ pháp lý (Legal Hold Guard)**:
   - Chặn đứng mọi hành vi xóa/ẩn danh hóa tài khoản nếu tài khoản đang có phiên sạc hoạt động hoặc đang trong trạng thái tạm giữ pháp lý (`privacy.legal_hold`), trả về HTTP `409 Conflict`.

---

## 2. Bảng chính sách lưu trữ dữ liệu (Retention Policies)

Hệ thống cấu hình ngưỡng lưu trữ thông qua `Settings` (`src/config.py`):

| Bảng dữ liệu | Mục đích dữ liệu | Ngưỡng lưu trữ mặc định (`Settings`) | Điều kiện dọn dẹp |
| :--- | :--- | :--- | :--- |
| `login_ip_attempts` | Khóa IP sau các lần thử đăng nhập thất bại | `retention_login_attempts_days = 1` | `(locked_until IS NULL OR locked_until < now) AND updated_at < cutoff` |
| `sessions` | Phiên đăng nhập web | `retention_expired_sessions_days = 30` | `revoked_at IS NOT NULL AND revoked_at < cutoff` |
| `station_create_idempotency` | Khóa chống trùng lặp tạo trạm | `retention_idempotency_days = 7` | `created_at < cutoff` |
| `charging_pending_messages` | Tin nhắn OCPP chờ xử lý mồ côi | `retention_pending_messages_days = 7` | `received_at < cutoff` |
| `ocpp_telemetry_buckets` | Mẫu đo lường telemetry OCPP | `retention_telemetry_hours = 25` | `timestamp < cutoff` |
| `alert_emails` | Nhật ký email cảnh báo outbox | `retention_sent_alert_emails_days = 30` | `status = 'sent' AND sent_at IS NOT NULL AND sent_at < cutoff` |
| `system_health_samples` | Mẫu đo sức khỏe hệ thống | `retention_health_samples_days = 30` | `timestamp < cutoff` |

---

## 3. Danh mục API & Endpoint Authorization

Tất cả các endpoint được bảo vệ nghiêm ngặt bằng `@user_policy` và đã được ghi nhận trong `docs/ROUTE_ACCESS_INVENTORY.csv`:

| Phương thức | Đường dẫn | Phân quyền (Permission) | Phạm vi (Scope) | Vai trò (Roles) | Mô tả |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/admin/privacy/retention-policies` | `admin.privacy.view` | `all` | `admin` | Xem cấu hình ngưỡng và số lượng bản ghi đủ điều kiện dọn |
| `POST` | `/api/v1/admin/privacy/cleanup` | `admin.privacy.manage` | `all` | `admin` | Kích hoạt dọn dẹp dữ liệu tạm theo yêu cầu |
| `POST` | `/api/v1/admin/privacy/anonymize/{user_id}` | `admin.privacy.manage` | `all` | `admin` | Ẩn danh hóa tài khoản người dùng theo yêu cầu |
| `GET` | `/api/v1/admin/privacy/holds/{user_id}` | `admin.privacy.view` | `all` | `admin` | Tra cứu trạng thái tạm giữ pháp lý và phiên sạc |
| `POST` | `/api/v1/admin/privacy/holds/{user_id}` | `admin.privacy.manage` | `all` | `admin` | Bật hoặc tắt trạng thái tạm giữ pháp lý với lý do |
| `POST` | `/api/v1/driver/privacy/anonymize-request` | `driver.privacy.request` | `own` | `driver` | Tài xế tự gửi yêu cầu ẩn danh hóa tài khoản của chính mình |

---

## 4. Kiến trúc Background Worker & Lifecycle

- **Worker**: `src/modules/privacy/worker.py`
  - Hàm `retention_cleanup_loop()` chạy nền theo chu kỳ `settings.retention_cleanup_interval_seconds` (mặc định 86,400 giây / 24 giờ).
  - Tự động gọi `PrivacyRetentionService.run_retention_cleanup` trong `SessionFactory()` độc lập.
  - Xử lý `asyncio.CancelledError` khi ứng dụng tắt, không làm treo graceful shutdown.
  - Ghi nhật ký audit `system.retention_cleanup` với phân rã chi tiết số lượng dòng bị xóa ở từng bảng.
- **Tích hợp Lifecycle**: `src/entrypoints/lifecycle.py`
  - Đăng ký `retention_cleanup_loop()` cùng `reconciliation_loop()` trong `application_lifespan()`.

---

## 5. Giao diện Frontend Admin (`AdminPrivacyRetention.tsx`)

Tích hợp tab **Lưu trữ & Quyền riêng tư** vào `AdminWorkspace.tsx`:
1. **Bảng thống kê chính sách lưu trữ**: Hiển thị 7 bảng dữ liệu tạm, thời hạn lưu trữ và số bản ghi đủ điều kiện dọn.
2. **Thực thi dọn dẹp on-demand**: Nút bấm có modal xác nhận cảnh báo an toàn và bảng kết quả thông báo chi tiết số dòng đã dọn dẹp.
3. **Bảng điều khiển Tạm giữ pháp lý (Legal Hold)**: Tra cứu nhanh theo User ID, xem tình trạng tạm giữ và phiên sạc, bật/tắt tạm giữ với lý do lưu vết audit.
4. **Form Ẩn danh hóa an toàn**: Yêu cầu nhập đúng cụm từ xác nhận `CONFIRM_ANONYMIZE`, cảnh báo bảo toàn các chứng từ hóa đơn và giao dịch ví tiền.

---

## 6. Ma trận kiểm thử & Kết quả xác minh (Test Evidence)

| Test File | Số test case | Trạng thái | Nội dung kiểm tra |
| :--- | :---: | :---: | :--- |
| `tests/test_privacy_schemas.py` | 9 | **PASS** | Kiểm tra serialize, parse, validate regex, constraints của các DTO/Schema |
| `tests/test_privacy_service.py` | 13 | **PASS** | Kiểm tra logic dọn dẹp, kiểm tra phiên sạc chưa kết thúc, tạm giữ pháp lý, cấm ẩn danh admin duy nhất, ẩn danh và bảo toàn hóa đơn |
| `tests/test_privacy_router.py` | 9 | **PASS** | Kiểm tra phân quyền RBAC (401, 403, 200), xử lý validation error (422) |
| `tests/test_privacy_worker.py` | 3 | **PASS** | Kiểm tra worker loop, xử lý ngoại lệ DB, hủy task nền an toàn |
| `tests/test_endpoint_policy_inventory.py` | 11 | **PASS** | Kiểm tra 100% route trong `app.routes` khớp tuyệt đối với `docs/ROUTE_ACCESS_INVENTORY.csv` |
| **Tổng cộng** | **45** | **PASS 100%** | Không có lỗi, ruff check sạch sẽ, mypy check thành công |
