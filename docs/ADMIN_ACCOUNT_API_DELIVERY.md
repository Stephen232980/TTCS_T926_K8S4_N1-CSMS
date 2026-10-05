# API quản trị — Tài khoản và vai trò

Phạm vi: nhóm đầu tiên trong ba màn hình quản trị đã chọn. API backend thật,
chưa triển khai giao diện. S-61 được làm sớm phục vụ demo Sprint 2–3; backlog
còn Later/chưa refine, không coi đây là nghiệm thu toàn bộ story hoặc sprint.

Nhóm tiếp theo đã bổ sung API đọc nhật ký tài khoản và Sức khỏe hệ thống;
xem [contract hiện tại](ADMIN_MONITORING_API_DELIVERY.md). Các ghi chú "chưa"
dưới đây mô tả phạm vi nhóm tài khoản ban đầu, không phải tổng trạng thái mới.

## Phạm vi ba màn hình

| Màn hình | Thiết kế đã chọn | Backend |
| --- | --- | --- |
| Tài khoản & vai trò | Mẫu 1, hướng dẫn mở/thu gọn | Nhóm API trong thay đổi này |
| Nhật ký thao tác | Mẫu 3, nhóm theo người thực hiện | Tận dụng nhật ký điều khiển S-27; chưa gộp nhật ký tài khoản vào API đó |
| Sức khỏe hệ thống | Mẫu 2, bốn biểu đồ | Chưa xây dựng API tổng hợp/lịch sử S-63 trong thay đổi này |

API S-63 cần chốt định nghĩa trực tuyến, phiên đang chạy, tin nhắn lỗi, ranh giới
đo độ trễ, cách lưu/tổng hợp lịch sử 24 giờ trước khi triển khai. Không thay
API này bằng số liệu giả hoặc suy tổng tin nhắn lỗi từ đầu nối lỗi.

## API

Tất cả endpoint dưới đây yêu cầu phiên cookie còn hiệu lực, tài khoản `active`
và role `admin`. Các role khác, kể cả operator và chủ trạm, nhận 403; chưa đăng
nhập hoặc phiên bị thu hồi nhận 401. Response có `Cache-Control: no-store`.

| Method | URL | Công dụng |
| --- | --- | --- |
| GET | `/api/v1/admin/roles` | Danh sách năm vai trò đang được seed trong DB, gồm `code`, `name` |
| GET | `/api/v1/admin/accounts` | Danh sách, tìm email, lọc vai trò/trạng thái và phân trang |
| GET | `/api/v1/admin/accounts/{id}` | Chi tiết tài khoản |
| POST | `/api/v1/admin/accounts` | Tạo tài khoản hoạt động kèm một hoặc nhiều vai trò; trả 201 |
| PATCH | `/api/v1/admin/accounts/{id}` | Thay danh sách vai trò, khóa/mở khóa; có thể gửi cả hai trong một giao dịch |

GET danh sách: `page=1`, `page_size=20` (1..100), `search` tối đa 320 ký tự,
`role` một mã vai trò, `status` trạng thái trong model User. Tìm chuỗi email
không phân biệt hoa/thường; `%`/`_` là ký tự thật, không phải wildcard. Sắp xếp
`created_at DESC, id ASC`. Response gồm `items`, `page`, `page_size`, `total`,
`total_pages`; không lặp tài khoản có nhiều vai trò.

Chi tiết/item: `id`, `email`, `roles` (mảng mã sắp xếp), `status`, `created_at`,
`updated_at`. Thời gian timezone-aware/UTC, UUID chuỗi; không có mật khẩu,
hash mật khẩu hoặc thông tin phiên đăng nhập.

POST:

```json
{
  "email": "member@example.com",
  "password": "mat-khau-rieng-tu-12-ky-tu",
  "roles": ["operator", "station_owner"]
}
```

Email được chuẩn hóa lowercase; email trùng trả 409. Mật khẩu 12..1024 ký tự,
hash Argon2id, không lưu plaintext. Có 1..5 vai trò, không lặp hoặc mã ngoài
`admin/operator/station_owner/driver/accountant`. Không cho client chỉ định id,
password_hash, trạng thái hoặc field chưa hỗ trợ. Validation không echo password.

PATCH: đọc chi tiết trước, gửi nguyên `updated_at` vào `expected_updated_at`.
Thiếu timezone trả 422; bản ghi đã thay đổi trả 409 và giao diện phải tải lại.

```json
{
  "expected_updated_at": "2026-10-05T01:00:00Z",
  "roles": ["driver", "station_owner"],
  "status": "suspended"
}
```

Chỉ gửi field cần sửa; `roles` thay toàn bộ danh sách, không phải thêm dồn.
`status` chỉ nhận `active` hoặc `suspended`. Null, danh sách rỗng, patch không
thay trường nào và field lạ trả 422. Trạng thái vòng đời khác vẫn đọc được
nhưng không thể sửa/khôi phục bằng API này (409). Patch đúng trạng thái/quyền
hiện tại là no-op, không ghi audit hoặc đổi timestamp.

Lỗi API mới theo `error.code/message/fields/request_id`, request_id hiện null;
401 authentication_required, 403 permission_denied, 404 resource_not_found,
409 resource_conflict, 422 validation_error. Login/logout cũ giữ contract cũ.

## Quy tắc vận hành

- Quyết định cho phạm vi demo: nhiều vai trò theo UserRole hiện có, tối thiểu
  12 ký tự mật khẩu; không có role tùy biến hay permission editor.
- Admin không tự khóa hoặc tự bỏ role admin (409). Phải giữ một admin hoạt
  động. PostgreSQL transaction advisory lock tuần tự hóa cập nhật; kiểm tra
  lại quyền người thực hiện sau khi lấy lock, tránh hai admin đồng thời bỏ
  quyền của nhau. Hash mật khẩu chạy ngoài event loop và trước lock.
- Khóa thu hồi mọi session chưa thu hồi trong cùng giao dịch. Auth từ chối
  cả session revoked và user không active. Mở khóa không hồi sinh phiên cũ;
  phải đăng nhập lại. Các trụ/phiên sạc không bị dừng theo khóa tài khoản.
- Đổi role không cần logout: role đọc lại từ DB ở lần gọi API kế tiếp. Request
  đã bắt đầu xử lý không bị hủy giữa chừng.
- Audit `account_audits` lưu actor/target, thời gian UTC và email/roles/status
  trước/sau, cùng giao dịch với thay đổi. Không lưu secret. Chưa có endpoint
  sửa/xóa audit, chưa mở API xem audit tài khoản trong nhóm này. S-27 là nhật
  ký lệnh OCPP riêng; không gọi hai loại nhật ký là cùng nguồn dữ liệu.
- Chưa có reset mật khẩu, mời qua email, xóa tài khoản, bắt buộc đổi mật khẩu
  lần đầu. Không tự cấp tài khoản quản trị qua endpoint công khai.

## Chạy và kiểm chứng

Nâng schema trước khi khởi động backend phiên bản mới:

```powershell
cd C:\Users\LENOVO\CSMS
.venv\Scripts\alembic.exe upgrade head
```

Migration mới `b610003a2026`, sau `a4d901ce8207`; thêm bảng audit, không đổi dữ
liệu người dùng cũ. Cần có admin hoạt động đã seed và đăng nhập để dùng API.
API có thể thử tại `/docs` trên backend đang chạy phiên bản mới. Chưa có
giao diện quản trị thật và chưa công bố CI/remote/deployment thành công.

Kiểm chứng tập trung: 41 test đạt, gồm 12 test mới qua HTTP/PostgreSQL thật,
auth service/repository/dependency, login integration và role policy.
Bao phủ tạo/login, multi-role, duplicate email, tìm/lọc/phân trang, dữ liệu
không hợp lệ và không lộ mật khẩu, sửa với timestamp cũ, quyền cập nhật ở
request kế tiếp, khóa/mở khóa, tự bảo vệ và hai admin sửa đồng thời.

Toàn bộ backend trên database PostgreSQL kiểm thử riêng: **371 đạt, 1 không
đạt**. Bài `test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms`
đo 206 ms, vượt ngưỡng 200 ms; chưa giải quyết NFR này trong nhóm tài khoản.
Không gọi kết quả này là toàn suite xanh. Chạy trên DB demo trước đó bị ảnh
hưởng bởi dữ liệu trạm sẵn có và thư mục Temp Windows, nên kết quả đầy đủ ở
trên dùng DB riêng và `--basetemp` riêng; giữ nguyên dữ liệu demo.

Ruff lint/format, mypy toàn src và `git diff --check` đạt. Alembic upgrade
head từ database trống, downgrade về `a4d901ce8207`, upgrade lại đều đạt;
`alembic check` không có schema drift. Database kiểm thử tạo riêng đã được
xóa sau khi chạy; migration đã áp dụng cho DB phát triển local. Chưa commit,
push hoặc tạo PR, chưa kiểm chứng CI remote.
