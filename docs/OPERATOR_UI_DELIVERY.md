# Giao diện vận hành — Sprint 2–3

## Phạm vi và thiết kế đã duyệt

Triển khai mẫu 3 của màn hình vận hành: nhóm trụ **Cần chú ý → Đang sạc → Sẵn sàng và trạng thái khác**, giữ hệ màu, hình trụ, đầu nối dạng ký hiệu và bố cục của chủ trạm. Khi bấm phần trụ, chọn đầu nối có số 1; nếu chưa khai báo số 1 thì chọn đầu nối có số nhỏ nhất. Bấm riêng đầu nối để đổi lựa chọn. Không tự chọn lại đầu nối khi nhận bản cập nhật.

Ba mục điều hướng: Giám sát trụ, Phiên sạc, Cần xem xét. Desktop 1366×768 và 1920×1080 giữ toàn bộ khung trang, danh sách và chi tiết cuộn riêng. Trên điện thoại điều hướng chuyển thành thanh phía trên; chọn trụ chuyển sang chi tiết và có nút quay lại.

Giao diện tài xế và kế toán chưa được thiết kế lại trong đợt này.

## API và nghiệp vụ

- Giám sát: `GET /api/v1/ops/ocpp/connections` và SSE `/api/v1/ops/ocpp/connections/events`, phân trang 100 trụ. SSE tự nối lại; tải snapshot khi nối lại. Không để phản hồi GET cũ ghi đè snapshot SSE mới.
- Tìm kiếm và nhóm trạng thái chỉ áp dụng **trang đang xem**, có nhãn rõ và phân trang. Trụ lỗi, ngoại tuyến, đầu nối không khả dụng hoặc chưa rõ trạng thái được ưu tiên. Có lỗi và đang sạc đồng thời vẫn nằm nhóm Cần chú ý; trạng thái riêng từng đầu nối giữ nguyên theo backend.
- Chi tiết đầu nối đối chiếu hồ sơ phiên mở theo mã trụ và số đầu nối, đọc số đo mới nhất ở trang 1; không lấy số đo của đầu nối khác. Trụ báo Charging nhưng không tìm thấy hồ sơ phiên sẽ hiển thị thông báo kiểm tra, không tự tạo dữ liệu.
- Phiên, số đo và sự kiện phục hồi: `/api/v1/ops/charging/sessions`, `/sessions/{id}/samples`, `/sessions/{id}/events`. Dùng chung `OwnerCharging` và `MeterChart`, thêm phạm vi `ops`; mặc định của chủ trạm giữ nguyên. Số đo/phiên tải lại mỗi 5 giây khi trang đang hiện.
- Cần xem xét mở bộ lọc `review`; bộ lọc `abnormal` xem các phiên bất thường còn mở. Bản tin chờ đối chiếu đọc `/api/v1/ops/charging/pending`; chỉ đọc và hệ thống tự đối chiếu khi đủ dữ liệu.
- Reset Soft/Hard dùng `POST /api/v1/ocpp/charge-points/{id}/reset`, xác nhận và theo dõi lệnh Pending/Accepted/Rejected/Offline/Timeout/Disconnected/ProtocolError bằng thành phần điều khiển hiện có.
- RemoteStop dùng `POST /api/v1/ocpp/sessions/{id}/stop`. Accepted là nhận lệnh; chỉ tin StopTransaction thật hoặc nghiệp vụ đóng hồ sơ mới kết thúc phiên.
- Đóng hồ sơ chỉ xuất hiện khi phiên còn mở và backend cung cấp `abnormal_since`. Yêu cầu lý do, xác nhận đã kiểm tra và số đo hợp lệ. `POST /api/v1/charging/sessions/{id}/close` chỉ gửi reason; backend tính điện năng từ số đo cuối, không nhận điện năng người dùng nhập. Thao tác này không gửi lệnh dừng trụ.
- Backend ghi nhật ký điều khiển/đóng hồ sơ theo cơ chế hiện có. Quản trị xem nhật ký ở giao diện quản trị. Đợt này không sửa backend hay quyền.
- Không có nút quản lý trạm/trụ hay cấp thẻ trong khu vực vận hành này. Tab chờ đối chiếu có dữ liệu thật. Không thêm chức năng tài chính chưa hỗ trợ.

## Kiểm tra local ngày 05/10/2026

- Toàn bộ frontend: 188 ca đạt (33 file), sau bổ sung kiểm thử mặc định đầu nối 1, đổi đầu nối không giữ số đo cũ, cập nhật lựa chọn từ SSE, phạm vi ops, điều kiện và payload đóng hồ sơ. Kiểm thử điều hướng cũ được cập nhật theo khu vực vận hành mới.
- Build TypeScript/Vite và ESLint đạt. Vite vẫn cảnh báo chunk nền lớn hơn 500 kB; khu vực vận hành tải riêng qua lazy import.
- Trình duyệt Edge headless, backend local thật và 20 trụ giả lập OCPP đang kết nối, thêm 1 trụ cũ ngoại tuyến: danh sách 21 trụ tải trong 1.545 giây ở lần đo local; không coi đây là kết quả kiểm tải production.
- Bấm trụ UI-DEMO-002 mở đầu nối 1 và phiên #89 với công suất/nhiệt độ/điện năng thật. Chi tiết phiên dùng biểu đồ và bảng số đo như chủ trạm.
- Reset Soft UI-DEMO-001 nhận Accepted qua WebSocket giả lập. Bộ giả lập chỉ trả lời Reset; kiểm tra này không chứng minh phần cứng khởi động lại.
- Dừng từ xa phiên #87 tại UI-DEMO-012 nhận StopTransaction thật, chốt 10.92 kWh và đầu nối Available. Sau kiểm tra còn 3 phiên demo mở.
- Phân quyền local: vận hành xem 21 trụ, chủ trạm demo thứ nhất xem 10 trụ; chủ trạm gọi ops trả 403; tài khoản admin đơn vai trò gửi Reset trả 403.
- Đóng hồ sơ được kiểm tra bằng test giao diện và cơ chế backend đã có; chưa tạo ca bất thường mới trong DB demo để đóng tay thực tế ở đợt này.
- Chụp màn hình 1366×768, 1920×1080, điện thoại 390 px; desktop không cuộn cả trang. Bằng chứng và mẫu đã duyệt lưu trong `impeccable/`, tiếp tục được Git bỏ qua.

Trước khi bàn giao PR, đã chạy lại toàn bộ frontend: 189 ca đạt (33 file), ESLint và build TypeScript/Vite đạt. CI remote được theo dõi trên PR; kết quả local không thay cho kết quả CI.

## Điều chỉnh sau khi người dùng kiểm tra (05/10/2026)

- Ô đầu nối có bốn vị trí cố định mỗi hàng; một đầu nối không giãn hết thẻ, đầu nối thứ 5 trở đi xuống hàng.
- Danh sách vận hành giữ các hàng phiên ngang như mẫu đã duyệt: trạng thái, trạm/mã trụ/đầu nối, kWh, thời lượng và số đo gần nhất. Không dùng lưới nhóm phiên của chủ trạm ở danh sách vận hành.
- Tìm kiếm/trạm lọc trong trang hiện tại, trạng thái lọc trên backend; có hướng dẫn thu gọn. Chỉ chọn một phiên mới tải số đo và mở chi tiết dùng chung với chủ trạm. Quay lại giữ bộ lọc và danh sách.
- Bộ giả lập local cố ý báo Faulted/GroundFailure tại đầu nối 4 của UI-DEMO-005 và UI-DEMO-015. Reset hiện chỉ trả Accepted, chưa phát trạng thái khôi phục. UI không tự xóa lỗi, không coi Accepted là Available: cần StatusNotification mới từ trụ/giả lập.
- Đã kiểm tra trình duyệt với backend thật ở 1366×768, 1920×1080 và 390px; một đầu nối rộng khoảng 49px ở desktop 1366px. Khi còn ở danh sách không tải samples hay hiển thị biểu đồ; bấm phiên mở chi tiết ops thật. 16 kiểm thử operator/owner đạt trong vòng kiểm tra điều chỉnh.
