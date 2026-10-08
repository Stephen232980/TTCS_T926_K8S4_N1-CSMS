# T-57 phần A nền tảng nhật ký dùng chung

Nguồn yêu cầu: dòng T-57, sheet Tasks của Nền tảng vận hành trạm sạc xe điện
(CSMS).xlsx; S-27 trong Backlog CSMS; các quyết định tách A/B đã thống nhất.
Phần A chỉ cung cấp nền tảng; không nối vào Reset, dừng từ xa, đóng tay, ví
hay giao diện. AC hai lệnh tạo hai dòng audit và hiển thị kết quả qua join
thuộc phần B, cần người nghiệm thu S-27 xác nhận.

## Hợp đồng ghi nhật ký

Import `ghi_nhat_ky` từ `src.platform.audit.service` và `AuditLog` từ
`src.platform.audit.models`. Helper nhận AsyncSession và các keyword:
`actor_id` (UUID hoặc None cho hệ thống), `action`, `object_type`, `object_id`
(chuỗi, caller chuyển UUID/int thành chuỗi), `data` (JSON object tùy chọn),
`permission`, `actor_roles` (tùy chọn). Trả UUID sau flush, không commit,
không tự xác thực hoặc phân quyền người gọi. Service nghiệp vụ phải thực
hiện phân quyền trước và ghi audit trong cùng transaction với nguồn chi tiết.

`audit_logs` có id, occurred_at mặc định now(), actor_id nullable FK users
RESTRICT, action, object_type, object_id text, data JSONB mặc định {}, cùng
permission và actor_roles nullable. Chỉ mục occurred_at DESC và cặp
object_type/object_id. Action và loại đối tượng dài tối đa 100 ký tự,
các mã không được rỗng; roles được loại trùng và sắp xếp trước khi lưu.

Quy tắc nguồn: bảng nghiệp vụ sở hữu chi tiết, chống trùng và kết quả.
Audit là chỉ mục tóm tắt và mã tham chiếu. Chống trùng theo từng hành động
thuộc service nghiệp vụ, không tự suy khoá unique chỉ từ object_id vì một
đối tượng có thể có nhiều hành động. Adjustment tiếp tục tham chiếu
wallet_audits.id; phần A không đổi cơ chế đó hoặc thiết kế mở khoá ví T-87.

## Bảo vệ JSON và quyền database

SENSITIVE_KEYS nằm ở một nơi trong helper. So khoá sau casefold và bỏ ký
tự không phải chữ/số, kiểm đệ quy cả dict và array. Từ chối các khoá mã thẻ,
email, điện thoại, token, mật khẩu, bí mật và định danh cá nhân. Từ chối
giá trị không phải JSON và NaN/Infinity, sao chép dữ liệu để caller không
thể sửa dict lồng làm thay đổi snapshot. Chốt chặn theo khoá không nhận biết
mọi dữ liệu nhạy cảm trong giá trị; caller chỉ truyền các trường tóm tắt
đã thống nhất, không truyền nguyên payload hoặc chuỗi lý do tự do.

Migration b150015a2026 sau f130014a2026 REVOKE ALL từ PUBLIC, tạo hàm và
trigger riêng cấp câu lệnh để chặn UPDATE/DELETE/TRUNCATE kể cả table owner.
`scripts/grant_audit_logs.sql` REVOKE ALL trên bảng khỏi runtime role rồi
chỉ GRANT SELECT/INSERT; cấp thêm USAGE schema. Chạy script bằng migration
owner với `psql -v app_role=<role-đã-tạo>` trên database đích. Runtime role
phải khác owner, không SUPERUSER, không kế thừa quyền owner hay vai trò rộng.
Script không tự tạo tài khoản/password hoặc sửa quyền của các bảng khác.

Downgrade xoá riêng audit_logs và hàm trigger. Chỉ chạy downgrade trên
database thử hoặc có kế hoạch sao lưu phù hợp; dữ liệu audit thật sẽ mất.

## Ma trận kiểm chứng

| Yêu cầu phần A | Cài đặt | Bằng chứng |
| --- | --- | --- |
| Schema chung và mã đối tượng đa kiểu | Model, migration, hai chỉ mục | Test dữ liệu, mặc định và migration |
| Helper trả UUID, không commit | Flush trên session người gọi | Reader khác chưa thấy; rollback không còn audit |
| System actor và thông tin phân quyền | Nullable actor/permission/roles | Test actor None, roles đã chuẩn hoá, FK actor |
| Không ghi khoá nhạy cảm | Kiểm đệ quy và chuẩn hoá khoá | idTag/id_tag/ID-Tag, object lồng array, dữ liệu sạch |
| Runtime chỉ đọc/chèn | Script grants và role đăng nhập riêng | INSERT/SELECT thành công; ba mutations trả 42501 |
| Runtime không sở hữu/kế thừa owner | Role riêng NOSUPERUSER NOINHERIT | Kiểm pg_roles, pg_has_role và table owner |
| Owner cũng không sửa/xoá/truncate | Trigger cấp câu lệnh | Ba mutations bị trigger chặn |
| Một Alembic head, schema tiến/lùi | Revision sau head develop | Test head và downgrade/upgrade trên DB riêng |

T-88 giữ nguyên worktree và phần audit chưa commit cho tới khi A được
review/merge. Sau đó cập nhật T-88 lên develop, bỏ model/helper/migration
audit riêng và dùng nền tảng này. Không merge cả hai migration tạo audit_logs.
Jira và thông báo nhóm chưa được cập nhật trong phần triển khai local.

## Kiểm chứng local ngày 08 tháng 10 năm 2026

Worktree sạch từ origin/develop `567612a`; nhánh
`feature/S-27-T-57-audit-foundation`. Nhánh T-88 không bị sửa.

- 33 test nền tảng và chain migration đạt, gồm kết nối runtime role riêng.
- Bộ hồi quy theo cấu hình CI: 710 passed, 2 deselected (hai ca latency
  tách sang gate riêng), 4 cảnh báo deprecation có sẵn.
- PostgreSQL 16 trên database thử riêng: upgrade từ rỗng thành công;
  test downgrade về f130014a2026 và upgrade lại đạt, bảng điều khiển OCPP
  vẫn tồn tại. Một head b150015a2026.
- Ruff toàn source/test/migration đạt; format check 179 file đạt;
  mypy 86 file source và git diff check đạt.

Kiểm chứng local chưa thay thế CI, review, staging hoặc nghiệm thu
toàn bộ T-57/S-27. Runtime role trong test là role đăng nhập thử riêng;
chưa áp dụng script quyền lên tài khoản hoặc database ứng dụng hiện hành.
