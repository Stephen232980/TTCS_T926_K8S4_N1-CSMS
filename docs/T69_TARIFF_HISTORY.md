# S-34 / T-69 — Lịch sử phiên bản biểu giá

Trong chi tiết trạm của chủ trạm, lịch sử được sắp theo ngày hiệu lực giảm dần,
có ngày hiệu lực, khung giờ/đơn giá, phí chiếm trụ, ân hạn và trạng thái
`current` (đang áp dụng), `upcoming` (sắp hiệu lực), `historical` (đã áp dụng).
Ngày và trạng thái tính theo múi giờ của trạm. Khi chưa có phiên bản đã hiệu lực,
không có phiên bản mang trạng thái `current`.

## API và quy tắc

- `GET /api/v1/owner/stations/{station_id}/tariffs`: trả `today`, `timezone`,
  `items`, `page`, `page_size`, `total`; trang mặc định 1, kích thước 20, tối đa
  100. Mỗi phiên bản có `id`, `created_at`, `editable` và các trường biểu giá.
  Giá tiền trả chuỗi thập phân để giữ chính xác BIGINT. `Cache-Control: no-store`.
- `PATCH /api/v1/owner/stations/{station_id}/tariffs/{tariff_id}`: gửi đầy đủ
  nội dung phiên bản giống body tạo T-66 (flat hoặc bands, không đồng thời).
  Đây là thay thế toàn bộ trường có thể sửa, không phải patch từng trường.
  Trả phiên bản đã lưu. Ngày phải từ ngày mai theo giờ trạm và không trùng
  phiên bản khác của chính trạm đó.
- Tạo mới dùng POST T-66 và form nhiều khung T-67. Lịch sử được tải lại sau
  tạo/sửa thành công. Sửa điền sẵn nội dung và giữ nhãn của các khung giờ.
- Chỉ chủ của trạm được đọc/sửa; 401 khi chưa đăng nhập, 403 khi thiếu quyền
  hoặc truy cập trạm người khác, 404 khi không tìm thấy tài nguyên thuộc trạm.
- Cả API và UI chỉ cho sửa khi `effective_from > today` **và** `used_at` rỗng.
  Tái sử dụng khóa trạm/phiên bản và guard T-68, cùng khóa với luồng đánh dấu
  đã dùng cho hóa đơn. Đã hiệu lực hoặc đã dùng trả 409 `tariff_immutable`.
  Trùng ngày trả 409 `tariff_duplicate_date`; ngày/khung không hợp lệ trả 422.
- Kiểm tra trước khi thay các khung; thay đổi được commit nguyên tử. Giữ ID
  phiên bản, không cập nhật biểu giá đã hiệu lực, hóa đơn hoặc tiền phiên cũ.
  Không có API/nút xóa phiên bản. Xóa dòng khung trong form chỉ thuộc nội dung
  phiên bản tương lai đang được chỉnh sửa.

## Kiểm chứng nghiệm thu

`tests/test_tariff_history_api.py` dùng PostgreSQL riêng, kiểm tra tạo hôm nay
và ngày mai cho hai phiên bản current/upcoming, phân trang, múi giờ,
BIGINT, phân quyền, sửa tương lai, giữ nguyên phiên bản hiệu lực, chặn marker
đã dùng, trùng ngày, 422 không ghi dở và không có DELETE.

`TariffHistoryPanel.test.tsx` kiểm tra nút sửa theo trạng thái, điền sẵn,
PATCH giữ nhãn/BIGINT, tạo rồi tải lại lịch sử, lỗi 409 do trạng thái thay đổi,
lỗi trùng ngày giữ dữ liệu nhập, tải lại khi đọc lỗi và hủy không ghi dữ liệu.
Kiểm tra trình duyệt với API mô phỏng ở 1440px và 360px xác nhận luồng sửa,
không tràn ngang và không có page error; không thay cho nghiệm thu staging.

Không có migration mới. T-68 tiếp tục là quy tắc chung để chọn/khóa phiên bản;
T-69 không thay thuật toán tính tiền hoặc các luồng lập hóa đơn.
