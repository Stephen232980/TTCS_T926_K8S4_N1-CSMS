# Khu vực làm việc và vai trò mặc định

Tiếp nối nền phân quyền PR #53 (`a494eda`). Đây là lựa chọn điều hướng,
không phải cơ chế active role hay giới hạn quyền trong phiên.

## Dữ liệu và API

- Migration `e030007a2026` thêm `user_roles.is_default`. PostgreSQL partial
  unique index bảo đảm mỗi tài khoản tối đa một vai trò mặc định; vai trò
  mặc định luôn là một assignment đã được cấp.
- Migration chỉ chọn mặc định cho tài khoản có đúng một vai trò. Tài khoản
  nhiều vai trò không được chọn theo thứ tự ưu tiên.
- `/api/v1/auth/me` trả thêm `default_role` (nullable).
- `PUT /api/v1/auth/default-role`, body `{ "role": "admin" }`, chỉ thay đổi
  tài khoản đang đăng nhập; mã quyền `identity.default_role.choose`, scope `own`.
  Vai trò không được cấp hoặc trường lạ trả 422. Response giống `/auth/me`.
- Hàm gán vai trò chung giữ mặc định nếu vai trò còn tồn tại, xóa mặc định
  khi bỏ vai trò đó trong cùng transaction. Lựa chọn mặc định không sửa roles
  và không nạp thêm quyền; backend tiếp tục đọc quyền từ DB ở mỗi request.
- Lưu mặc định cập nhật `users.updated_at`, để một lần sửa tài khoản quản trị
  với phiên bản cũ được phát hiện thay vì ghi đè đồng thời.

## Giao diện

- Một vai trò: vào thẳng khu vực tương ứng.
- Nhiều vai trò có mặc định hợp lệ: mở khu vực mặc định.
- Nhiều vai trò chưa có mặc định: người dùng chọn khu vực; ghi nhớ tùy chọn
  được lưu bằng API. Lỗi lưu không tự chuyển trang hay giả vờ thành công.
- `Đổi khu vực` mở lại lựa chọn. Nếu không ghi nhớ, khu vực mới chỉ dùng
  trong lần làm việc hiện tại; tải lại quay về mặc định đã lưu.
- Component nhận một vai trò để quyết định nút/tab trong khu vực hiện tại;
  đây chỉ là hiển thị. API xác thực tài khoản và scope đã khai báo ở endpoint.
- Chủ trạm giữ API cũ đã ràng buộc `owned`; vận hành gọi `/ops/...`, kế toán
  gọi `/accounting/charging/...`. Lệnh điều khiển/đóng tay tiếp tục gọi endpoint
  operator riêng. Admin không tự có nút điều khiển hay đóng phiên.
- Ba màn hình admin giữ bố cục đã chốt. Chi tiết nhật ký hiển thị mã quyền và
  vai trò tại thời điểm thao tác do backend lưu; bản ghi cũ thiếu dữ liệu được
  ghi rõ, không suy ra vai trò từ tài khoản hiện tại.

## Kiểm chứng

PostgreSQL kiểm tra migration một/nhiều vai trò, unique index, gỡ mặc định,
không tự chọn mặc định, không chọn vai trò chưa cấp, không sửa người khác và
quyền không thay đổi. Giao diện kiểm tra chọn/lưu mặc định, lỗi API, đổi khu vực,
admin không có thao tác vận hành. Edge thật với backend local kiểm tra cấp tài
khoản, khóa/mở khóa, nhật ký, biểu đồ, scope sở hữu và mặc định qua reload/login.

Ảnh và báo cáo local nằm trong `impeccable/review/admin-implementation/`
(Git-ignore). Các kiểm chứng này không đại diện cho CI remote hay staging.
