# S-46 / S-63 — Cảnh báo vận hành và sức khỏe hệ thống

Nền SMTP dùng chung và cách S-59 tích hợp được mô tả tại
[SHARED_SMTP.md](SHARED_SMTP.md). Có thể dùng profile `SMTP_*` mới độc lập
với công tắc/người nhận cảnh báo vận hành; profile `ALERT_SMTP_*` cũ vẫn được
hỗ trợ khi `SMTP_ENABLED` rỗng hoặc chưa khai báo.

G3 bổ sung cảnh báo trụ vào monitoring operator, danh sách trạm owner và trang sức khỏe admin. S-63 tiếp tục dùng metrics, biểu đồ 24 giờ và chu kỳ 30 giây của dashboard hiện có; danh sách cảnh báo cập nhật mỗi 10 giây khi trang đang hiển thị.

## Ngưỡng mặc định

| Quy tắc | Mặc định | Lý do |
| --- | --- | --- |
| Offline | `last_seen_at` + 2 × heartbeat đã thương lượng + 300 giây | Đồng bộ định nghĩa online hiện có và bỏ qua ngắt mạng ngắn khi demo khoảng 10 đầu nối. Trụ chưa gửi dữ liệu dùng `created_at`. |
| Lỗi liên tục | 3 bản ghi lỗi đầu nối trong 600 giây, tính theo trụ | Phát hiện lỗi lặp lại mà không báo động vì một sự cố đơn lẻ. Replay cùng OCPP message được lớp replay hiện có loại bỏ. |
| Scanner | 15 giây | Kết hợp polling UI 10 giây cho ngân sách hiển thị thông thường dưới 30 giây. |
| Phục hồi | Online liên tục 2 × heartbeat, ít nhất 2 quan sát `last_seen_at` mới, không có lỗi trong 600 giây | Tránh bật lại cảnh báo khi trụ chập chờn. Đây là quan sát hoạt động, không chỉ riêng message Heartbeat. |

Mỗi trụ chỉ có một cảnh báo `open`/`acknowledged`, được bảo vệ bằng unique index PostgreSQL. Scanner có transaction advisory lock. Cảnh báo lưu bền qua restart và không tự đóng khi trụ phục hồi. Sau khi đóng, chỉ episode đã phục hồi ổn định mới được mở lại. Trạm blocked hoặc trạm/trụ archived được loại khỏi scanner.

Operator xác nhận và đóng cảnh báo đã phục hồi; backend kiểm tra lại online/lỗi tại lúc đóng. Admin có thể đóng cưỡng bức với lý do bắt buộc, ghi audit, nhưng lỗi đang tồn tại không được rearm để tránh spam. Owner chỉ xem cảnh báo thuộc trạm mình. Không gửi SMTP trong luồng xử lý OCPP hoặc trong transaction DB.

## API

| Khu vực | Endpoint | Quyền |
| --- | --- | --- |
| Operator | `GET /api/v1/ops/alerts` | `operator`, all |
| Admin | `GET /api/v1/admin/alerts` | `admin`, all |
| Owner | `GET /api/v1/owner/alerts` | `station_owner`, owned |
| Operator/Admin | `POST /api/v1/{ops\|admin}/alerts/{id}/acknowledge` | Xác nhận xử lý |
| Operator/Admin | `POST /api/v1/{ops\|admin}/alerts/{id}/close` | JSON `{ "force": false, "reason": "" }`; force chỉ admin |
| Operator/Admin | `POST /api/v1/{ops\|admin}/alerts/{id}/retry-email` | Retry email thất bại, giữ nguyên outbox identity |

GET nhận `status=active|open|acknowledged|closed|all`, `page>=1`; trang 50 phần tử và tự clamp khi số trang giảm. Response có thời điểm tạo, thông tin trạm/trụ và trạng thái email, không trả người nhận email hoặc thông tin tài xế. Mutation có audit; acknowledge/close lặp lại cùng kết quả không tạo thêm thao tác. Mã lỗi: 404 resource không tồn tại, 403 sai quyền, 409 `alert_not_recovered`/`alert_already_closed`/`alert_email_not_configured`, 422 `alert_close_reason_required` hoặc body không hợp lệ.

## Cấu hình email và vận hành

Mặc định `ALERT_SMTP_ENABLED=false`, `ALERT_EMAIL_RECIPIENTS=[]`: cảnh báo UI vẫn hoạt động, hiển thị email chưa cấu hình. Thiết lập backend qua `.env` (Compose đã forward các biến) hoặc env-file của script staging:

```dotenv
ALERT_OFFLINE_GRACE_SECONDS=300
ALERT_ERROR_WINDOW_SECONDS=600
ALERT_ERROR_THRESHOLD=3
ALERT_SCAN_INTERVAL_SECONDS=15
ALERT_SMTP_ENABLED=true
ALERT_SMTP_HOST=smtp.example.com
ALERT_SMTP_PORT=587
ALERT_SMTP_SECURITY=starttls
ALERT_SMTP_FROM=csms@example.com
ALERT_EMAIL_RECIPIENTS=["ops@example.com"]
ALERT_SMTP_USERNAME=replace-on-server
ALERT_SMTP_PASSWORD=replace-on-server
ALERT_SMTP_TIMEOUT_SECONDS=5
ALERT_EMAIL_MAX_ATTEMPTS=6
```

Không commit thông tin đăng nhập thực. Username/password phải có cùng nhau; khi bật SMTP phải có host, sender và người nhận. `plain` chỉ dành cho SMTP local test. Danh sách người nhận lấy từ cấu hình server, không nhận từ API client. Email chỉ chứa trụ, trạm, loại sự cố, thời điểm và trạng thái.

Outbox unique theo alert/người nhận, claim bằng `SKIP LOCKED` với lease token; lease hết hạn được nhận lại sau restart. Lỗi SMTP lưu mã đã lọc, backoff từ 30 giây, tối đa 6 lần mặc định; UI cho phép retry các email failed, không gửi lại email sent. Giao nhận là at-least-once: crash sau SMTP chấp nhận trước DB commit có thể gửi lại; Message-ID ổn định hỗ trợ đối chiếu, không bảo đảm SMTP exactly-once.

Migration `b220022a2026` nối head `a210021a2026`, thêm incident, checkpoint và email outbox. Chạy migration và cấp quyền runtime theo quy trình staging hiện có trước khởi động app. Downgrade xóa dữ liệu cảnh báo/outbox; cần bảo toàn lịch sử trước rollback thực tế.

## Kiểm chứng local

PostgreSQL 16: kiểm tra threshold, replay, scanner đồng thời, RBAC/owned scope, audit, recovery, force close, lease/retry, SMTP local thực, pagination và migration upgrade → downgrade → upgrade. Scanner 50 trụ offline khoảng 92 ms; các gate OCPP MeterValues và 20 socket đạt khoảng 73 ms và 102 ms, dưới 200 ms.

Giao diện được kiểm tra bằng login và API thật local ở desktop và 360×800 cho ba vai trò. Review độc lập xác nhận đã sửa ba vấn đề: Content-Type khi đóng, pagination sau khi danh sách giảm, và focus/reveal form lý do trên mobile. Lỗi tải dữ liệu giữ cảnh báo gần nhất và thông báo dữ liệu có thể cũ.

Các bằng chứng trên là local. PR/CI, SMTP nhà cung cấp thật, staging và trụ vật lý là các bước xác nhận riêng; tài liệu này không xác nhận Jira Done hoặc đã deploy.
