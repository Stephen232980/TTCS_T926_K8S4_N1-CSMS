# Giao diện quản trị — phạm vi demo Sprint 2–3

Triển khai trên `feature/admin-interface`, đã cập nhật main `a494eda` sau PR #53.
Ba màn hình giữ phong cách chủ trạm và bố cục đã duyệt: tài khoản mẫu 1,
nhật ký mẫu 3, sức khỏe mẫu 2. Dùng API thật; dữ liệu không được thay bằng
mock khi backend lỗi. Không khẳng định toàn bộ S-61/S-63 Later đã nghiệm thu.

## Tài khoản & vai trò

- Danh sách phân trang, tìm theo email, lọc vai trò/trạng thái; tải chi tiết
  mới khi chọn tài khoản. Bộ vai trò lấy từ `/admin/roles`.
- Hướng dẫn 3 bước có thể thu gọn; chỉ trạng thái mở/đóng được lưu local.
- Cấp tài khoản qua 3 bước: email/mật khẩu, chọn một hoặc nhiều vai trò,
  kiểm tra và POST `/admin/accounts`. Mật khẩu tối thiểu 12 ký tự; chỉ giữ
  trong bộ nhớ khi đang nhập, không lưu trình duyệt và không hiện lại ở bước kiểm tra.
- Đổi vai trò; khóa/mở khóa có xác nhận. PATCH gửi `expected_updated_at`.
  Khi 409, tải lại chi tiết và yêu cầu kiểm tra lại; không tự ghi đè.
- Không tự khóa hoặc bỏ admin của tài khoản đang đăng nhập. Trạng thái
  ngoài active/suspended chỉ cho xem. Không có nút reset mật khẩu, xóa hoặc gửi thư.
- Backend thu hồi phiên khi khóa; mở khóa cần đăng nhập lại.

## Nhật ký thao tác

- Hai nguồn trong cùng màn hình: `/ocpp/control-audit` và `/admin/account-audit`.
- Nhóm theo người thực hiện **trên trang hiện tại**, không tuyên bố tổng toàn bộ
  thao tác của người đó. Danh sách/detail cuộn riêng, khung chung giữ nguyên.
- Lọc email chính xác, mã trụ với nguồn điều khiển hoặc loại thao tác với nguồn
  tài khoản, thời gian Việt Nam và phân trang. Đổi nguồn xóa bộ lọc không liên quan.
- Chi tiết điều khiển có kết quả, thời gian phản hồi, phiên và payload.
  Accepted chỉ là chấp nhận lệnh, không xác nhận hành động vật lý hoàn tất.
- Chi tiết tài khoản có trạng thái trước/sau, vai trò và đối tượng.
  Không sửa/xóa nhật ký hoặc gửi lệnh ở màn hình này.

## Sức khỏe hệ thống

- Snapshot `/admin/system-health`, lịch sử `/admin/system-health/history`.
  Bốn biểu đồ đồng thời, phóng to/thu gọn, chọn mốc và độ phân giải.
- Hiển thị trụ trực tuyến, phiên đang sạc, lượt trao đổi OCPP có lỗi/5 phút
  và thời gian backend phản hồi. Định nghĩa đầy đủ ở
  [ADMIN_MONITORING_API_DELIVERY.md](ADMIN_MONITORING_API_DELIVERY.md).
- Theo `refresh_after_seconds`, mặc định 30 giây; hủy request khi rời màn hình,
  không chồng lượt tải; tạm dừng và cập nhật thủ công, hạn chế poll khi tab ẩn.
- Giữ giá trị lần đo trước khi lỗi tải, ghi rõ thời điểm. Dữ liệu quá hạn
  theo `stale_after_seconds` được đánh dấu cũ. Trạng thái freshness không phải
  kết luận hệ thống tốt/xấu.
- Không nội suy qua null, không cộng rolling-5m thành tổng giờ, không tạo dữ
  liệu quá khứ. Không có mẫu độ trễ thì `—`; cửa sổ 5 phút chưa đủ có giải thích.
- Phạm vi API hiện tại một backend process; không cam kết toàn mạng nhiều replica.

## Điều hướng và bố cục

Một vai trò vào thẳng khu vực tương ứng. Nhiều vai trò mở mặc định đã lưu;
chưa có mặc định thì chọn khu vực, không tự ưu tiên chủ trạm hay admin.
Nút `Đổi khu vực` chỉ hiện khi có nhiều vai trò. Ghi nhớ tùy chọn qua API
`/auth/default-role`. Chi tiết ở [DEFAULT_ROLE_DELIVERY.md](DEFAULT_ROLE_DELIVERY.md).
Khu vực chủ trạm chỉ hiển thị quyền chủ trạm và dùng scope sở hữu; vận hành
dùng `/ops`, kế toán dùng `/accounting`. Backend vẫn kiểm quyền mỗi request.
Khu vực quản trị tải riêng để tránh thêm chi phí tải ban đầu cho chủ trạm.

Desktop 1366×768 giữ một màn hình tổng thể; chỉ nội dung dài cuộn. Điện thoại
390×844 xếp dọc, không tràn ngang. CSS quản trị được giới hạn bằng `admin-*`.

## Kiểm chứng local

- Build production và ESLint đạt. **185/185 tests**, 32 files đạt, gồm 12 test
  mới về cấp tài khoản, xác nhận/phiên bản cập nhật, 409, trạng thái chỉ xem,
  guide lưu lựa chọn, nhật ký, timezone, khoảng trống, pause và lỗi tải.
  Thêm kiểm thử chọn/lưu mặc định, lỗi lưu và đổi khu vực cho tài khoản nhiều vai trò.
- Trình duyệt Edge thật với backend local/PostgreSQL: cấp tài khoản, đổi vai
  trò, khóa (đăng nhập bị từ chối), mở khóa, nhật ký thực và bốn biểu đồ đạt.
  Sau mở khóa, thành viên đăng nhập được với vai trò đã lưu; API quản trị
  từ chối người không có admin (403).
- 14 ảnh desktop/mobile và báo cáo layout được lưu trong
  `impeccable/review/admin-implementation/`, thư mục đã Git-ignore.
- Có cảnh báo bundle chính khoảng 531 kB; chunk quản trị riêng khoảng 33 kB.
  Không coi đây là bằng chứng tải/hiệu năng trên staging.
- Chưa commit/push, chưa kiểm chứng CI remote. Có bổ sung migration và API nhỏ để lưu vai trò mặc định; backend **405/405** tests đạt trên PostgreSQL tách biệt, Ruff/mypy và Alembic check đạt.

## Chạy local

Cần backend main hiện tại và migration `e030007a2026`. Vite proxy mặc định
`localhost:8001`; có thể đặt `CSMS_DEV_API_TARGET` trước khi chạy frontend
nếu backend dùng port khác. Không đưa tài khoản/mật khẩu demo vào code frontend.

```powershell
cd C:\Users\LENOVO\CSMS\frontend
$env:CSMS_DEV_API_TARGET = 'http://127.0.0.1:8015'
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```
