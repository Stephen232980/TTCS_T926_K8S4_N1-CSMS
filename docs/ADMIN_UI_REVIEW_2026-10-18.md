# Rà soát giao diện admin — 18/10/2026

Bản sửa cục bộ trên nhánh `fix/admin-ui-review-20261018`, từ `origin/develop` commit `4362b68`. Thay đổi chỉ gồm frontend, kiểm thử và tài liệu; không thay đổi backend/migration. Việc triển khai staging được xác minh riêng sau merge.

## Thay đổi theo yêu cầu

- Nạp tiền thủ công: textarea lý do có cùng font, border, bo góc, chiều rộng và focus với input. Bỏ chú thích dưới tham chiếu chứng từ; chỉ gắn mô tả lỗi khi có lỗi.
- Cảnh báo: hai nút cố định Đang mở / Lịch sử, có số lượng riêng và trạng thái mở tương ứng. Bấm cùng nút lần nữa đóng popup; chuyển nút đổi đúng bộ lọc, xóa dữ liệu của bộ lọc trước khi tải mới. Giữ X, Escape và bấm ngoài. Bỏ nút xem/thu gọn và refresh riêng; vẫn tự cập nhật, có Thử lại khi tải lỗi.
- Quyền riêng tư: tập trung danh sách yêu cầu, quyết định từng hồ sơ, trạng thái và điều kiện bị chặn. Hồ sơ đã xử lý thu gọn. Chỉ hiện thử lại cho hồ sơ bị chặn/cần xem xét; không hiện cho job đang xếp hàng/đang chạy.
- Bỏ bảng cleanup kỹ thuật và công cụ legal hold nhập UUID khỏi màn admin này; không xóa API hay thay đổi các kiểm tra an toàn ở backend.

## Đối chiếu AC gốc S-57

Nguồn đã đọc trực tiếp: `C:/Users/LENOVO/CSMS/.local/project-inputs/Backlog CSMS.xlsx`, sheet `Backlog CSMS`, dòng 59, cùng `docs/S57_DATA_RETENTION_PRIVACY.md` trên develop.

AC: sau khi duyệt không tra lại nơi/thời điểm sạc qua tài xế gốc; ẩn danh phiên/hóa đơn thay vì xóa; giữ doanh thu/sổ cái; ví dương phải xử lý hoàn tiền trước.

Màn hình giữ luồng duyệt/từ chối có lý do và chính sách, kết quả ẩn danh, điều kiện hoàn tiền và nghĩa vụ đang vướng. Cleanup log/telemetry nằm ngoài phạm vi AC gốc nên được lược khỏi giao diện này. Legal hold vẫn là điều kiện chặn của backend và được trình bày khi hồ sơ liên quan bị chặn. Không thêm chức năng hoàn tiền, thay policy hoặc xóa dữ liệu tài chính.

## Lỗi bổ sung đã sửa

1. Nhiều hồ sơ dùng chung lý do/chính sách/xác nhận: tách state và lỗi theo từng hồ sơ, tránh duyệt nhầm nội dung.
2. Job đang chạy vẫn hiện nút thực thi lại: chỉ cho thử lại ở trạng thái thích hợp.
3. Yêu cầu admin nhập chuỗi kỹ thuật `EXECUTE_PRIVACY_REQUEST`: đổi thành checkbox xác nhận, giữ nguyên payload API.
4. Các lớp nút primary/danger của màn privacy không khớp stylesheet admin: dùng đúng lớp để thể hiện mức độ hành động.
5. Focus popup làm cuộn vùng overflow ẩn và cắt tiêu đề admin: dùng focus không cuộn, giữ trả focus về đúng nút mở.
6. Bố cục privacy thiếu vùng cuộn và khoảng cách: dùng vùng danh sách cuộn trên desktop, xếp dọc tự nhiên trên mobile, cho mã dài xuống dòng.

## Rà soát sáu màn admin

| Màn | Nội dung kiểm tra | Kết quả trong phạm vi kiểm tra |
| --- | --- | --- |
| Tài khoản & vai trò | Bố cục danh sách/chi tiết, lọc, kiểm thử tài khoản/vai trò | Chưa phát hiện lỗi mới cần sửa |
| Nạp tiền thủ công | Form, xác nhận khoản thu, lỗi, chống gửi trùng | Sửa textarea và chú thích; kiểm thử liên quan đạt |
| Nhật ký thao tác | Nguồn dữ liệu, lọc, vùng danh sách/chi tiết | Chưa phát hiện lỗi mới cần sửa |
| Nhật ký ví | Lọc, chi tiết chứng từ, dữ liệu cũ, kiểm tra vai trò | Chưa phát hiện lỗi mới cần sửa |
| Sức khỏe hệ thống | Popup cảnh báo, chuyển bộ lọc, đóng/mở và focus | Đã sửa logic và lỗi cuộn khi lấy focus |
| Lưu trữ & quyền riêng tư | AC, danh sách, form theo hồ sơ, trạng thái job | Đã tái cấu trúc và lược phần ngoài AC |

## Kiểm chứng

- Toàn bộ frontend: 438/438 test, 71 file đạt trước khi thêm ba ca toggle vai trò cuối.
- Lần xác nhận cuối: 58/58 test admin/cảnh báo, gồm ba ca toggle mới cho owner/operator/admin.
- TypeScript và build đạt; lint đạt; diff không có lỗi khoảng trắng.
- Hai lượt kiểm tra hiển thị: desktop 1440×1000 và mobile 390×844 cho cả sáu route; không tràn ngang và không có lỗi JavaScript runtime trong dữ liệu mẫu.
- Kiểm thử vai trò dùng chung và toàn bộ frontend bảo vệ các màn owner/operator dùng AlertsPanel.

## Giới hạn

Kiểm tra trình duyệt dùng API giả lập để không tạo tài khoản, nạp tiền, duyệt yêu cầu hay gửi thông báo trên staging. Ảnh chỉ minh họa giao diện cục bộ. Fixture biểu đồ không đại diện chuỗi thời gian thực, nên ảnh health không dùng làm bằng chứng độ chính xác biểu đồ. Cần kiểm tra lại dữ liệu thực sau triển khai. Build còn cảnh báo bundle chính khoảng 591 kB; đây không phải lỗi build và chưa tối ưu trong phạm vi lần này.
