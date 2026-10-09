# Nhóm 6 — tài xế theo dõi và bắt đầu sạc

Phạm vi: S-22, S-24 theo `.local/project-inputs/Backlog CSMS.xlsx`.
Nhánh triển khai: `feature/driver-charging`. Cần nâng migration `c60318a4d962`
trước khi chạy phiên bản này. Tài liệu ghi bằng chứng cục bộ; không thay trạng thái Jira,
CI remote hay nghiệm thu thiết bị thực.

## Đối chiếu AC

| Story | Điều kiện | Triển khai và kiểm chứng |
|---|---|---|
| S-22 | Hiển thị trụ, thời điểm bắt đầu, kWh và thời gian sạc của tài xế | Màn hình tài xế đọc phiên thật từ tài khoản đăng nhập; API current không nhận driver/session ID do trình duyệt lựa chọn. |
| S-22 | MeterValues cập nhật trong 2 giây, không reload | SSE đọc snapshot đã commit mỗi 0,5 giây theo mẫu T-25, phát dữ liệu khi phiên/số đo/yêu cầu bắt đầu thay đổi. Đồng hồ chạy tại trình duyệt; polling 1 giây là dự phòng cho trình duyệt không hỗ trợ EventSource. Test HTTP SSE thật và test frontend phủ cập nhật, reconnect và rollback. |
| S-22 | Không có phiên: thông báo và tìm trạm | Có trạng thái trống và liên kết tới bản đồ trạm trong cùng màn hình. |
| S-22 | GET phiên tài xế khác trả 403 | Endpoint chi tiết kiểm tra driver_id với actor đăng nhập; test truy cập chéo và current trống cho tài xế khác. |
| S-24 | Bắt đầu với thẻ ảo của tài xế | Server cấp duy nhất một id_tag riêng mỗi driver trong bảng id_tags, liên kết charging_cards; tái sử dụng luồng Authorize/StartTransaction của thẻ vật lý. |
| S-24 | Accepted rồi StartTransaction mới hiện đang sạc | Request được lưu trước khi gửi; Accepted chỉ hiện chờ. StartTransaction thật gắn phiên với thẻ/tài xế, kể cả khi tin bắt đầu đến trước phản hồi lệnh. |
| S-24 | Rejected hướng dẫn kiểm tra súng | Thông báo cụ thể và cho gửi yêu cầu mới; không tạo phiên giả. |
| S-24 | Bận/Reserved chặn trước khi gửi | Khóa trụ, đầu nối và tài xế; kiểm tra phiên/yêu cầu đang chờ, trạng thái đầu nối và trạm. Chỉ Available/Preparing được gửi. |
| T-104 | Ví đủ số dư tối thiểu theo giá trạm | `5 kWh × stations.price_vnd_per_kwh + WALLET_RESERVE_VND`; kiểm tra ở driver-start và OCPP Authorize. Thiếu ví/giá hoặc không đủ tiền đều bị từ chối. |
| S-24 | Accepted thiếu StartTransaction sau 60 giây | Deadline tính từ phản hồi Accepted; job 1 giây giải phóng yêu cầu, thông báo kiểm tra súng và thử lại; GET vẫn phản ánh timeout khi job chưa chạy. |

Ngưỡng dùng chung cấu hình qua `CHARGING_MINIMUM_KWH` (mặc định `5`) và
`WALLET_RESERVE_VND` (mặc định `10000`, VND). Giá `price_vnd_per_kwh` thuộc từng
station và được cập nhật qua API tạo/sửa station. T-104 chỉ kiểm tra điều kiện bắt đầu;
chưa trừ số dư, tính hóa đơn hoặc đối soát phiên sạc.

## API

Tất cả endpoint dưới đây yêu cầu session đăng nhập và role driver.

- `GET /api/v1/driver/charging/current`: `{session, start_request}` theo actor hiện tại.
- `GET /api/v1/driver/charging/current/events`: SSE cùng cấu trúc current, gửi snapshot mới nhất ngay khi kết nối/nối lại; cookie đăng nhập và role được kiểm tra lại mỗi chu kỳ. Xem [hợp đồng và kiểm chứng T-48](T48_DRIVER_REALTIME.md).
- `GET /api/v1/driver/charging/sessions/{session_id}`: chỉ phiên của chính tài xế; 403 nếu thuộc tài xế khác.
- `GET /api/v1/driver/stations/{station_id}/connectors`: đầu nối chưa archive tại trạm active, không trả owner/card data.
- `POST /api/v1/driver/charging/start`: chỉ `{request_id: UUID, connector_id: UUID}`; từ chối trường bổ sung như id_tag hoặc driver_id.

Request ID là khóa chống gửi trùng. Gửi lại cùng ID/driver/connector trả kết quả đã lưu,
không gửi thêm OCPP; đổi chủ thể/đầu nối với cùng ID trả 409. Mất phản hồi mạng ở UI
giữ nguyên ID khi thử lại. Server không gửi lại lệnh sau khởi động lại.

Trạng thái: Pending, Accepted, Started, Rejected, StartNotConfirmed, Offline,
Timeout, Disconnected, ProtocolError. Accepted có deadline; Started có session_id thật.
Lệnh dùng transport chung với Reset/RemoteStopTransaction, thời hạn phản hồi 30 giây,
và nhật ký bất biến RemoteStartTransaction. Audit chỉ giữ connectorId, tuyệt đối không
ghi idTag thô. Token thẻ ảo 20 ký tự được giữ riêng tại server để gửi OCPP;
API/UI chỉ dùng thông tin phiên. Cần kiểm soát quyền truy cập DB và tránh ghi payload
OCPP chứa thẻ vào log bên ngoài ứng dụng.

## Giới hạn được giữ rõ

- Chưa có mô hình đặt chỗ và xác minh người sở hữu reservation. Mọi đầu nối Reserved
  đều bị chặn an toàn, kể cả của chính người dùng; phân biệt chủ đặt chỗ thuộc phần đặt chỗ sau.
- Thời gian/điện năng phản ánh tin thật từ trụ; khi mất mạng hiển thị cảnh báo dữ liệu cũ.
  T-104 chỉ kiểm tra số dư tối thiểu, không trừ tiền, tính hóa đơn hoặc đối soát tài chính.
- Accepted không thay thế xác nhận cáp vật lý. Checkbox là xác nhận của tài xế;
  trụ quyết định Accepted/Rejected và gửi StartTransaction.
- Tin bắt đầu đến muộn vẫn hiển thị phiên thật theo thẻ đã được xác thực. Không tạo
  phiên hay giả vờ sạc chỉ từ kết quả lệnh.
- Registry WebSocket đang ở bộ nhớ của một process như nhóm trước; nhiều worker
  cần cơ chế định tuyến/kênh gửi lệnh chung trước khi triển khai.
- UI được bổ sung chức năng theo thiết kế hiện tại; nâng cấp toàn diện giao diện vẫn theo
  quyết định của người dùng sau khi hoàn thành các nhóm.

## Kiểm thử thủ công

1. Đăng nhập tài xế; thấy Phiên sạc của bạn trống và liên kết tìm trạm. Operator đơn vai
   không có nút Tài xế; tài khoản có cả driver và quản lý có khu vực Tài xế riêng.
2. Chọn trạm trên danh sách/bản đồ, chọn đúng trụ/đầu nối. Nút bắt đầu chưa hoạt động
   cho tới khi xác nhận đã cắm súng. Đầu nối không sẵn sàng không thể chọn.
3. Với simulator kết nối trụ đã đăng ký, chạy:

   ```powershell
   python scripts/ocpp_control_simulator.py --url ws://127.0.0.1:8001 --code MA-TRU --start-delay 10
   ```

   Không truyền id-tag: server gửi thẻ ảo của tài xế trong RemoteStartTransaction.
   Bấm bắt đầu; thấy Accepted/chờ, sau StartTransaction thật mới có kWh/thời gian.
   Simulator gửi MeterValues mỗi 2 giây; số đo tăng, không reload. Tải lại trang vẫn
   thấy phiên của tài khoản đăng nhập. Đây là số liệu mô phỏng, không phải thiết bị thực.
4. Dừng simulator và chạy với `--outcome Rejected`: chọn đầu nối sẵn sàng và kiểm tra
   thông báo kiểm tra súng, không có phiên mới. Dùng `--outcome Timeout` để kiểm tra
   trụ không trả lời; dùng `--omit-start` để Accepted nhưng thiếu StartTransaction
   sau 60 giây. Mỗi tình huống cần đầu nối không có phiên đang mở.
5. Kiểm tra trụ offline và đầu nối Charging/Reserved/Faulted: không gửi lệnh khi không
   đủ điều kiện. Thử hai tài xế bắt đầu cùng đầu nối: chỉ một yêu cầu được giữ.
6. Tài xế khác không thấy phiên trong current; truy cập endpoint chi tiết ID phiên
   của người thứ nhất nhận 403. Admin có thể xem audit bắt đầu từ ứng dụng;
   nội dung audit không chứa thẻ ảo.

## Bằng chứng kiểm thử

Bổ sung T-48 ngày 08/10/2026: SSE và phục hồi/phân quyền đã kiểm chứng;
tổng 869 ca backend qua hồi quy Linux, hai gate latency riêng và Compose
trên Windows; frontend 205 ca đạt. HTTP SSE khoảng 537 ms; OCPP WebSocket
20 trụ tối đa 106,5 ms. Quality gate đạt, build còn cảnh báo chunk lớn.
Chi tiết và giới hạn tải tại [T48_DRIVER_REALTIME.md](T48_DRIVER_REALTIME.md).
Các số liệu nhóm 6 dưới đây là bằng chứng lịch sử trước bổ sung T-48.

Đã kiểm tra Ruff lint/format, mypy, ESLint, TypeScript/build; migration downgrade nhóm6,
upgrade head và Alembic check không có schema drift. Bộ backend có 310 test đạt trên
Windows và Python3.12/Linux tương tự CI; frontend có 152 test đạt trong 28 file Vitest.
Đã kiểm tra trình duyệt ở desktop và mobile390px, Accepted chờ phiên thật, số đo thay
đổi không reload, khôi phục sau tải lại và hết 60 giây thì nút thử lại hoạt động.
Reviewer giao diện chấm hai sửa chữa cuối (tên đầu nối mobile và màu CTA) resolved;
ghi chú thiết kế lưu riêng tại .local/driver-design. Commit/push/CI remote thực hiện riêng.
