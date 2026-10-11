# T-48 — realtime phiên của tài xế

Nguồn phạm vi: S-22 trong `.local/project-inputs/Backlog CSMS.xlsx`, phụ thuộc
S-19; task kỹ thuật T-48 sử dụng API T-47 và mẫu SSE snapshot của T-25.
Nhánh `feature/S-22-T-48-driver-realtime`, từ `origin/develop` tại `1e57186`.
T-40 đã merge qua PR #87. Dữ liệu năng lượng dùng đúng hợp đồng Wh của T-40.

## Coverage Matrix

| AC / yêu cầu | Triển khai | Kiểm chứng |
| --- | --- | --- |
| Mở màn hình thấy trụ, thời điểm bắt đầu, kWh, thời gian | REST current và SSE dùng chung current_snapshot theo actor | Test tài xế cũ và snapshot SSE đầu tiên |
| Số đo mới hiển thị trong 2 giây | SSE lấy snapshot đã commit mỗi 0,5 giây; gửi khi dữ liệu thay đổi | HTTP SSE thật, MeterValues qua service OCPP, thời gian commit → nhận dữ liệu dưới 2 giây |
| Reconnect phục hồi phiên hiện tại | Mỗi kết nối gửi full snapshot mới nhất; EventSource tự retry 1 giây | Test backend reconnect, frontend mất luồng/phục hồi và phản hồi REST cũ |
| Phiên trống có thông báo và tìm trạm | Payload session=null dùng trạng thái trống hiện tại | Test frontend cũ và snapshot sau đóng phiên |
| Không đọc phiên tài xế khác | Cookie/role xác định actor, query luôn lọc driver_id | Hai stream riêng biệt; API chi tiết trả 403; query session_id không đổi chủ thể |
| Rollback không phát dữ liệu chưa commit | Mỗi lượt đọc dùng transaction/connection độc lập | Flush chưa commit, rollback và commit số đo bằng writer riêng |
| Quyền thay đổi trong lúc mở kết nối | Kiểm tra token, thời hạn, trạng thái tài khoản và role mỗi chu kỳ | Logout, hết hạn, suspended, gỡ driver role, identity mismatch |
| Giữ hành vi giao diện và lệnh bắt đầu | EventSource cập nhật current; thời gian tăng tại trình duyệt; fallback polling | Hồi quy frontend, Accepted vẫn chờ Started đúng session_id |

## Cơ chế và giới hạn

`GET /api/v1/driver/charging/current/events` dùng cookie session,
quyền `driver.current`, scope `own`, role `driver`. Header
`Content-Type: text/event-stream`, `Cache-Control: no-store`,
`X-Accel-Buffering: no`. Lỗi trước kết nối: 401/403 như API current.

Message mặc định chứa JSON `{session, start_request}` cùng cấu trúc REST.
`retry: 1000` hướng dẫn trình duyệt nối lại. Snapshot đầu tiên gửi ngay ở
mỗi kết nối. Các lượt tiếp theo đọc trạng thái đã commit; khi nội dung
nghiệp vụ thay đổi thì gửi full snapshot, còn lại gửi comment keepalive.
Thời gian elapsed_seconds không làm phát thêm snapshot; UI tăng đồng hồ
cục bộ từ giá trị server. Số đo trong một khoảng đọc được gộp thành trạng
thái mới nhất, phù hợp màn hình xem phiên; lịch sử số đo vẫn ở database.

Đây là SSE snapshot theo cách T-25 đang dùng: backend đọc database mỗi
0,5 giây, không phải PostgreSQL NOTIFY hoặc event bus. Mỗi kết nối có chu
kỳ đọc riêng và đóng connection/transaction database trước khi yield hoặc
sleep. Chi phí query tăng theo số kết nối SSE; cần đo tải mục tiêu khi
nghiệm thu staging. OCPP ghi/commit giữ nguyên, có thể đọc số đo đã commit
từ process khác nhờ database chung.

Trong lúc stream mở, token và quyền được kiểm tra lại trước từng snapshot.
Mất quyền phát `event: access-denied` rồi kết thúc. Frontend đóng stream,
xoá current/command và phát sự kiện đăng nhập lại. Lỗi database kết thúc
stream để EventSource tự nối lại; frontend giữ cảnh báo dữ liệu cũ.

REST đầu tiên giúp phát hiện lỗi đăng nhập và tải dữ liệu ngay. Snapshot
SSE mới có ưu tiên hơn response REST phát đi trước đó. Reconnect luôn lấy
full snapshot, nên Last-Event-ID không dùng để phát lại lịch sử. Trình
duyệt không hỗ trợ EventSource dùng polling tuần tự mỗi giây. Khi rời màn
hình, đóng EventSource, abort fetch và huỷ timer.

API này dùng các bảng và chỉ mục đã có. Hình thức giao diện giữ nguyên;
thay đổi là cách nhận dữ liệu và đồng hồ. Luồng tính tiền T-80 vẫn thuộc
phạm vi riêng.

## Kiểm chứng

39 ca backend tập trung ban đầu đạt. Sau khi khai báo OpenAPI đúng media
type SSE, 20 ca T-48/phân quyền/Compose chạy bổ sung trên Windows đạt:
HTTP SSE thật nhận số đo mới khoảng 537 ms, generator khoảng 530 ms.

Hồi quy đầy đủ Linux/Python 3.12.15, SQLAlchemy 2.1.3, PostgreSQL 16:
866 passed, 1 skipped (Compose CLI không có trong image), 2 deselected.
Test Compose chạy riêng trên Windows đạt. Hai gate latency chạy riêng
đạt: MeterValues 20 trụ tối đa 81 ms; WebSocket thật qua ba chu kỳ tối đa
106,5 ms, dưới ngưỡng 200 ms. Tổng 869 ca backend đạt qua các lần chạy.

Frontend đầy đủ: 205 ca đạt trong 35 file, gồm 5 ca mới cho SSE. Ruff
lint/format, mypy 94 source, ESLint, TypeScript/build và diff check
đạt. Build còn cảnh báo chunk trên 500 kB; backend còn cảnh báo deprecation
có sẵn. Database thử rỗng upgrade đến b150015a2026 đạt, không migration
mới. CI, Jira và nghiệm thu staging xác nhận riêng.

## Kiểm thử thủ công

1. Đăng nhập tài xế, mở phiên hiện tại. Trong Network thấy request events
   kiểu event-stream; dữ liệu đầu tiên là phiên của tài khoản đang dùng.
2. Cho simulator gửi MeterValues, đối chiếu kWh và latest_meter_at trong
   màn hình trong 2 giây. Thời gian tiếp tục tăng giữa hai bản tin.
3. Ngắt rồi bật lại mạng: thấy cảnh báo dữ liệu cũ, sau khi nối lại thấy
   snapshot mới nhất. Thử StopTransaction khi mất mạng rồi nối lại:
   màn hình trở về trạng thái không có phiên.
4. Mở tài xế khác: không thấy số đo/phiên của tài xế đầu tiên. Gọi API chi
   tiết mã phiên đó trả 403.
5. Thu hồi phiên đăng nhập hoặc role driver khi stream đang mở: stream
   kết thúc bằng access-denied, frontend xoá dữ liệu và yêu cầu đăng nhập.
