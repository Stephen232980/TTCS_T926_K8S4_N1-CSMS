# T-62 — Biểu giá trên trang chi tiết trạm

Chủ trạm đọc biểu giá đang áp dụng từ API, nhập đơn giá kWh, phí chiếm trụ/phút và ân hạn rồi lưu qua API T-61. Lần đầu chỉ có hiệu lực hôm nay; khi đã có phiên bản thì từ ngày mai trở đi, theo ngày tại trạm do backend trả về. Backend vẫn quyết định cuối cùng khi có thay đổi đồng thời.

`GET /api/v1/owner/stations/{station_id}/tariffs/context` trả `today`, `timezone`, `has_versions`, `current` và `upcoming` (phiên bản tương lai gần nhất). Chỉ chủ của trạm được truy cập; không cache. Giá tiền trả chuỗi thập phân để giữ chính xác số nguyên 64-bit. Dữ liệu nhiều khung được hiển thị theo khung, chưa có form tạo nhiều khung T-67. Không có lịch sử/chỉnh sửa/xóa phiên bản T-69 trong endpoint này.

Sau POST thành công, giao diện cập nhật dữ liệu vừa lưu và đọc lại context. Biểu giá tương lai được tách khỏi biểu giá hiện hành. Nếu POST đã thành công nhưng đọc lại thất bại, thông báo rõ đã lưu và chỉ cho tải lại dữ liệu, tránh hiểu nhầm rồi gửi một khoản tạo mới. Nếu không tải được context, không cho tạo biểu giá với dữ liệu mặc định đoán trước.

Kiểm thử gồm quy tắc ngày trước gửi, lỗi API/giữ dữ liệu, chống gửi trùng, tải lần đầu, lưu/cập nhật tại OwnerWorkspace, phân biệt biểu giá tương lai, lỗi đọc lại sau lưu, timezone trạm và giới hạn quyền đọc API. Có kiểm tra trình duyệt local bằng dữ liệu giả lập; không thay cho xác nhận staging.
