# S-41 / T-85 — Tạo ví tài xế và backfill

## Luồng mới

`assign_user_roles` là điểm cấp vai trò dùng chung. Khi danh sách cuối có driver, hàm gọi `ensure_driver_resources` để tạo ví và thẻ ảo trong cùng giao dịch với tài khoản/vai trò. API tạo tài khoản và cập nhật vai trò giữ quyền, audit và commit hiện tại. Thêm driver cho tài khoản cũ cũng tạo tài nguyên; tài khoản nhiều vai trò có driver vẫn chỉ có một ví.

`ensure_driver_wallet` khóa dòng user, kiểm driver role và INSERT ON CONFLICT theo unique driver_id. Ví mới có số dư 0/status active, không tạo dòng sổ cái vì không có biến động tiền. Ví đã có được trả nguyên trạng: không reset số dư, mở khóa hoặc xóa ledger. Helper không tự commit; caller commit/rollback tài khoản, vai trò, ví và thẻ cùng nhau.

`ensure_driver_resources` dùng cùng khóa user để chỉ tạo một DriverVirtualTag/ChargingCard khi gọi đồng thời. Thẻ hiện có, kể cả bị chặn, được giữ nguyên; helper không tự kích hoạt lại. `virtual_tag` khi bắt đầu sạc gọi cùng provisioning để tương thích tài xế cũ chưa có ví/thẻ, rồi vẫn kiểm thẻ hợp lệ như trước.

`scripts/create_test_accounts.py` dùng assign_user_roles với replace=False và một giao dịch cho từng tài khoản. Giữ password/status/role cũ, không commit user trước ví; chạy lại không tạo thêm ví/thẻ. Không chạy script này trên dữ liệu demo/staging trong quá trình triển khai T-85.

## Backfill và downgrade

Migration `d110012a2026`, nối `c100011a2026`, INSERT SELECT những tài khoản có role driver với ON CONFLICT DO NOTHING. Bao gồm driver nhiều vai trò hoặc không active; trạng thái tài khoản vẫn kiểm soát đăng nhập/sạc. Không tạo ví cho non-driver, không thay đổi ví hiện có và không backfill thẻ ảo. Driver cũ nhận thẻ qua luồng hiện có khi dùng hoặc cấp lại vai trò.

Migration dùng gen_random_uuid có sẵn trên PostgreSQL 16. Không thêm extension, bảng, trigger hoặc cấp quyền database. Runtime cần SELECT/INSERT wallets và quyền đọc/khóa user, như hạ tầng hiện tại; role runtime tách biệt phải được cấp các quyền này bởi tài khoản migration. Script grant_wallet_ledger chỉ cấp ledger/audit, không thay thế quyền bảng wallets.

Downgrade chỉ lùi revision, cố ý giữ ví backfill để không xóa ví đã có ledger bất biến. Upgrade lại an toàn và không reset tiền. Khi gỡ role driver, giữ ví/thẻ/lịch sử; khi cấp lại dùng tài nguyên cũ. Không hard-delete tài khoản có dữ liệu tài chính hoặc bỏ khóa ngoại để xóa nó.

## Kiểm tra

Tests test_driver_wallet_provisioning kiểm API tạo mới, non-driver/multi-role, rollback tài khoản–role–ví–thẻ, seed lặp/lỗi, cấp/bỏ/cấp lại role, thẻ bị chặn, backfill hai lần, số dư/ví khóa đã có, hai kết nối thật và migration tiến/lùi/tiến với ledger. Fixtures tài khoản quản trị dọn ví/thẻ trống thuộc riêng test trước khi xóa user; không vô hiệu trigger/FK. Phép đếm thẻ trong test sạc giới hạn đúng tài xế, không giả định toàn hệ thống chỉ có một tài xế.

Tests commit/migration dùng database tạm của fixture đã có từ T-68, cần CREATEDB; không dùng tài khoản runtime để chạy test và không trỏ tests vào demo/staging. Chưa có API ví/nạp tiền/job đối soát trong T-85.
