# Nền tảng kết nối OCPP có giao diện

Nhóm chức năng đầu tiên của Sprint 2–3 ghép S-06, S-07, S-08, S-13 và S-14.
Phạm vi nghiệm thu lấy từ `.local/project-inputs/Backlog CSMS.xlsx`; trạng thái
Jira phải được kiểm tra riêng trước khi đánh dấu hoàn thành.

## Coverage Matrix

| Story / yêu cầu | Triển khai | Bằng chứng |
| --- | --- | --- |
| S-06: nhận trụ đăng ký, subprotocol `ocpp1.6`, cho phép trạm tạm ngưng kết nối | Router và service kế thừa PR #35 | `test_ocpp_connections.py` |
| S-07: CALL/CALLRESULT/CALLERROR, lỗi cấu trúc giữ socket, action chưa hỗ trợ | `frames.py`, `transport.py`, dispatcher và pending futures | `test_ocpp_foundation.py`: round trip, malformed, socket mở, timeout và correlation |
| S-08: Boot cập nhật vendor/model/firmware, UTC và interval cấu hình | Dispatcher transaction; cổng kiểm tra Boot trên mỗi kết nối | Boot được chấp nhận, trạm khóa bị từ chối, trạm tạm ngưng được nhận; simulator thật |
| S-08: Boot lặp không tạo trụ mới, trước Boot trả SecurityError | Chỉ cập nhật bản ghi trụ hiện có; cache phản hồi | Kiểm thử duplicate, boot gate và request đồng thời |
| S-13: một socket hiện hành/trụ, socket cũ không xóa socket mới | Registry thay thế và remove theo identity; phản hồi gắn socket gốc | Kiểm thử thay thế và phản hồi đang xử lý |
| S-14: cache phản hồi lưu DB, tồn tại sau đổi kết nối, nội dung khác giữ phản hồi đầu | `ocpp_message_replies`, khóa hàng trụ trong transaction, SHA-256 canonical payload | Kiểm thử hai transaction đồng thời và replay từ session/kết nối mới; simulator gửi lặp |
| S-14: dọn cache quá 7 ngày | Lifespan task chạy định kỳ, transaction riêng | Kiểm thử retention |
| Giao diện vận hành có dữ liệu thật | Tab Kết nối trụ; API phân trang và owner scope | Frontend refresh/retry tests; browser desktop và mobile; tài xế nhận 403 |

## API và vận hành

WebSocket: `/ocpp/{charge_point_code}`, subprotocol `ocpp1.6`. Frame tối đa
65.536 ký tự; payload Boot được kiểm tra schema. Action khác chưa được triển
khai trả `NotImplemented` sau khi Boot được chấp nhận.

`GET /api/v1/ocpp/connections?page=1&page_size=50`: owner chỉ thấy trụ thuộc
trạm của mình; operator/admin xem phạm vi toàn hệ thống. Tài xế không truy cập.
Trả `items`, `total`, `page`, `total_pages`; mỗi item gồm id, code, station_name,
connected, boot_accepted, connected_at, last_boot_at, vendor, model,
firmware_version. Giao diện cập nhật mỗi 5 giây khi tab đang hiển thị, có làm
mới, thử lại và thông báo dữ liệu cũ khi lỗi.

Migration mới: `9c02a6b7d831` sau `7b1d4f2a9c30`. Chạy `alembic upgrade head`
trước khi khởi động phiên bản mới. Cache có khóa `(charge_point_id,message_id)`
và FK xóa theo trụ. `OCPP_HEARTBEAT_INTERVAL_SECONDS=60` là interval phản hồi
Boot; `OCPP_REPLY_CLEANUP_INTERVAL_SECONDS=3600` là chu kỳ dọn cache. Hai giá
trị phải lớn hơn 0. Heartbeat handler được phát triển ở nhóm giám sát tiếp theo.

Registry nằm trong bộ nhớ: chạy **một process/worker**. Nhiều worker hoặc nhiều
instance cần registry/bus chia sẻ trước khi mở rộng. Mất process làm mất trạng
thái socket và pending outbound calls; cache phản hồi vẫn nằm trong PostgreSQL.
Cache được dọn định kỳ nên bản ghi quá 7 ngày có thể tồn tại đến chu kỳ kế tiếp.
Chưa dùng trạng thái kết nối để khẳng định đầu nối rảnh hay sẵn sàng sạc.

## Demo và kiểm thử

Tạo một trụ được đăng ký rồi chạy:

```powershell
python scripts/ocpp_simulator.py --url ws://127.0.0.1:8001 --code MA-TRU --hold 600
```

Simulator gửi Boot, gửi lại cùng messageId, xác nhận phản hồi y hệt và giữ
kết nối để xem tab Kết nối trụ. Chỉ dùng với môi trường kiểm thử.

Kết quả cục bộ ngày 02/10/2026: backend 207 bài đạt trên DB riêng; frontend 111
bài đạt, lint/build đạt; Ruff và mypy đạt. Migration được kiểm tra nâng cấp,
hạ về head cũ và nâng lại. Đây là bằng chứng cục bộ, chưa phải kết quả CI hay
Jira Done. Giám sát đầu nối, phiên sạc và lệnh điều khiển là các nhóm tiếp theo.

Kiểm tra runtime riêng trên cổng 8002: sau khi dừng và khởi động lại backend,
simulator gửi lại `foundation-preview` nhận đúng `currentTime` ban đầu
`2026-10-02T02:01:19.900249+00:00`, xác nhận replay qua restart process.

## Tích hợp vào thư mục CSMS

Ngày 02/10/2026, mã OCPP và bản đồ được tích hợp vào C:\Users\LENOVO\CSMS
trên nhánh feature/ocpp-map-integration. Các worktree nguồn được giữ nguyên.
Bản tích hợp: 210 kiểm thử backend, 113 frontend đạt; lint/build/Ruff/mypy đạt.
Dữ liệu kiểm thử/demo dùng database riêng, không nâng migration hoặc đổi dữ liệu
trong database csms gốc. Khi chạy backend với database gốc, cần alembic upgrade head.
Chưa commit/push/merge; Git hiện các thay đổi ngay trong thư mục CSMS.
