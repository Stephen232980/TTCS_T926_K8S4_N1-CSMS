# Quản trị đặt mật khẩu mới cho tài khoản

Bổ sung theo yêu cầu trưởng nhóm ngày 12/10/2026 vào màn hình Tài khoản & vai trò.
Đây là phần mở rộng quản lý tài khoản; không tự thay đổi AC hoặc trạng thái Jira.

## Cách dùng

Admin chọn tài khoản -> Đổi mật khẩu -> nhập và nhập lại -> Tiếp tục -> xác nhận
đúng email. Mật khẩu tối thiểu 12, tối đa 1024 ký tự, cùng quy tắc cấp tài khoản.
Form không lưu mật khẩu vào local/sessionStorage hoặc hiển thị trong bước xác
nhận. Không gửi trước khi xác nhận; khóa gửi trùng; xóa form sau xử lý.

Tài khoản active/suspended được đặt mật khẩu mới, giữ nguyên vai trò/trạng thái.
Không dùng thao tác này để mở khóa tài khoản. Deactivated/pending_deletion/
anonymized chỉ xem, cả UI lẫn API không cho đặt mật khẩu. Đổi mật khẩu của
admin đang đăng nhập sẽ thu hồi phiên hiện tại và đưa về đăng nhập.

## API và transaction

POST /api/v1/admin/accounts/{user_id}/password
- Cookie session, quyền admin.accounts.manage, scope all, chỉ admin đang active.
- Body: expected_updated_at (ISO-8601 có timezone), password, confirm_password.
- 200 AccountResponse không chứa mật khẩu/hash; Cache-Control: no-store.
- 401 chưa đăng nhập/phiên hết hạn; 403 không có quyền; 404 không có tài khoản;
  409 dữ liệu cũ hoặc trạng thái không được sửa; 422 mật khẩu sai quy tắc.
- AdminAccountRoute trả validation error đã lọc input, không echo mật khẩu.

Hash bằng Argon2id hiện có trước khi giữ khóa giao dịch. Trong một transaction:
kiểm lại admin, khóa target user (cùng khóa với login), kiểm updated_at, đổi hash,
thu hồi mọi session chưa bị thu hồi, ghi audit và commit. Lỗi audit/DB rollback
cả hash và thu hồi session. updated_at chống xác nhận từ tab có dữ liệu cũ.

Nhật ký tài khoản có action account_password_reset, nhãn Đổi mật khẩu và bộ lọc.
AccountAudit chỉ lưu email/vai trò/trạng thái, không có mật khẩu/hash/token.
AuditLog account.credentials_reset lưu actor/target và revoked_sessions, cùng
permission/actor_roles. Cả hai audit cùng transaction với đổi mật khẩu.

## Migration

f200020a2026 nối e190019a2026, mở rộng check constraint action của account_audits.
Không sửa migration đã merge. DB thử đã chạy upgrade/downgrade/upgrade.
Downgrade khi còn account_password_reset bị từ chối trước DDL để giữ chứng cứ;
không sửa/xóa audit hoặc đổi nhãn lịch sử để cho downgrade chạy qua.

## Coverage

| Yêu cầu | Bằng chứng |
|---|---|
| Admin-only/không selector quyền | HTTP anonymous 401, operator 403, service kiểm lại role/status |
| Hash/đăng nhập | mới đăng nhập được, cũ bị 401; không có plaintext trong response/audit |
| Phiên cũ | token tài xế sau reset 401; tự reset admin cũng hết phiên |
| Sai mật khẩu/dữ liệu cũ | mismatch/ngắn/dài 422; stale 409, không đổi hash/audit |
| Audit nguyên tử | lỗi ghi audit trả lỗi và giữ hash/token cũ; journal lọc đúng action |
| UI | nhập lại, xác nhận email, gửi một lần, xóa inputs, nhắc self logout |
| Migration | roundtrip DB mới, guard audit tồn tại |

Browser local dùng API fixtures ở 360px/1280px, không đổi mật khẩu tài khoản thật
trên staging. Sau merge/deploy, admin có thể kiểm trên tài khoản thử được chỉ định.
