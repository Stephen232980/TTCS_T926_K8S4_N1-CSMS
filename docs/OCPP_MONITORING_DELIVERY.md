# Nhóm 2 — giám sát trụ và đầu nối

> Phân quyền hiện hành cập nhật 05/10/2026: [nền phân quyền endpoint](ENDPOINT_AUTHORIZATION_DELIVERY.md) thay thế quy tắc admin/operator tự nhận global scope và quyền điều khiển trong các mô tả lịch sử bên dưới. Chủ trạm dùng owned; vận hành/kế toán đọc qua namespace riêng; admin đơn thuần không gửi Reset/Stop/đóng tay.

Phạm vi S-09, S-10, S-11, S-12 được đối chiếu từ `.local/project-inputs/Backlog CSMS.xlsx`. Mã triển khai trực tiếp trong CSMS, nhánh `feature/ocpp-monitoring-ui`. Jira được cập nhật riêng sau nghiệm thu; không suy Done từ file backlog.

## Coverage Matrix

| Story / AC và NFR | Triển khai | Bằng chứng |
| --- | --- | --- |
| S-09: Heartbeat cập nhật liên lạc, trả giờ máy chủ; mọi bản tin cũng cập nhật; không dùng giờ trụ | Transport ghi `last_seen_at` cho CALL/RESULT/ERROR, cả frame lỗi; Heartbeat trả UTC | Kiểm thử server clock, targeted update, every frame; demo WebSocket thật |
| S-09: chỉ cập nhật một cột, 50 trụ đồng thời | UPDATE riêng `last_seen_at`, không đọc/sửa/ghi ORM cả trụ; khóa hàng theo trụ | Kiểm thử giữ nguyên `updated_at`; 50 transaction đồng thời thành công |
| S-10: trạng thái và lỗi của đầu nối | StatusNotification schema OCPP, UPDATE đầu nối đã khai báo, lịch sử ConnectorError theo giờ nhận | Charging/Faulted, errorCode/vendorErrorCode/time; replay trùng không tạo lỗi lặp |
| S-10: connectorId 0 là cả trụ; đầu nối lạ bỏ qua, không tự tạo | Trụ có raw_ocpp_status/error fields riêng; log cảnh báo với đầu nối không tồn tại | Kiểm thử whole charger và unknown connector |
| S-10: không khóa bảng lâu | Khóa hàng trụ trước hàng đầu nối; job dùng SKIP LOCKED, transaction ngắn | Không dùng table lock; kiểm thử cập nhật đồng thời |
| S-11: 20 trụ, đủ đầu nối, tải dưới 2 giây; một truy vấn trạng thái | Một SELECT join station/charger/connector và lỗi mới nhất; phân trang sau nhóm kết quả | Test 20 trụ dưới 2 giây và đúng một query; owner scope/driver 403 |
| S-11: thay đổi trong 1 giây; tự nối lại và tải snapshot đầy đủ | SSE snapshot mỗi 0,5 giây, EventSource retry 1 giây; mở/reconnect lấy đầy đủ; lỗi hiển thị dữ liệu có thể cũ | Unit stream/React reconnect; đo qua Vite proxy 0,514 giây; kết nối SSE mới nhận đủ dữ liệu |
| S-12: quá hai interval thì offline, đầu nối unknown | Interval lưu theo Boot; job quét mỗi giây; API luôn suy offline từ timestamp dù job chưa chạy | Test derived without job/expire; demo im lặng quá hạn |
| S-12: Heartbeat phục hồi online, đầu nối chờ báo lại | Hết hạn thì xóa trạng thái cũ trước ghi liên lạc mới; Heartbeat không khôi phục trạng thái đầu nối | Test và demo heartbeat recovery, status tiếp theo khôi phục Charging |

## API, lưu trữ và bảo mật

`GET /api/v1/ocpp/connections?page=1&page_size=100` giữ contract cũ và bổ sung online, last_seen_at, heartbeat_interval_seconds, raw_ocpp_status, lỗi trụ và connectors. Mỗi đầu nối có trạng thái, trạng thái OCPP gốc, thời điểm cập nhật và lỗi gần nhất. Khi offline API trả unknown, không khẳng định rảnh dù DB chưa được job cập nhật. Online biểu thị thời điểm liên lạc còn hạn; connected là socket trong registry, hai thông tin có thể khác nhau sau restart.

`GET /api/v1/ocpp/connections/events` có cùng query/phạm vi và trả `text/event-stream`. Mỗi kết nối nhận full snapshot; cookie và vai trò được kiểm tra lại mỗi lần gửi. Phiên hết hạn/thu hồi quyền gửi access-denied rồi đóng. Không giữ transaction/DB connection giữa các lần gửi. Owner chỉ thấy trạm của mình; operator/admin xem toàn mạng; driver không được dùng cả hai endpoint.

Nginx tắt proxy buffering; response có X-Accel-Buffering: no, Cache-Control: no-cache. Không cần thay dependency. Thiết kế hiện dành cho một process/worker và quy mô 50 trụ. Mỗi người xem dùng một luồng SSE và truy vấn snapshot mỗi 0,5 giây; mở rộng số người xem cần cơ chế fan-out chung. Trình duyệt không hỗ trợ EventSource dùng tải lại mỗi giây, không có bảo đảm push dưới 1 giây.

Migration `a721093e4f62` sau `9c02a6b7d831`: interval, raw status và lỗi cấp trụ, index last_seen_at, ràng buộc interval > 0. Chạy `alembic upgrade head` trước khi khởi động phiên bản mới. Last_seen dùng giờ máy chủ. Timestamp trụ được kiểm tra định dạng nhưng không dùng để quyết định online/offline hoặc thời điểm nhận lỗi.

Schema tham khảo: [OCPP StatusNotification](https://raw.githubusercontent.com/mobilityhouse/ocpp/master/ocpp/v16/schemas/StatusNotification.json). Cơ chế browser: [EventSource và SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events).

## Demo và kết quả cục bộ

Khai báo đầu nối 1 và 2 cho trụ rồi chạy `python scripts/ocpp_simulator.py --code MA-TRU --monitor --hold 600`. Đầu nối 1 báo Charging, đầu nối 2 báo Faulted/GroundFailure/DEMO-E42. Simulator gửi Heartbeat theo interval được chấp nhận. Dừng simulator và chờ quá hai interval để xem offline/unknown; chạy lại để thấy phục hồi rồi trạng thái mới. Không có chức năng mở phiên sạc, Reset hay dừng sạc trong nhóm này.

Ngày 02/10/2026: 225 backend và 115 frontend tests đạt; lint/build/Ruff/mypy đạt. Có kiểm thử 50 trụ đồng thời, 20 trụ một query, SSE đầy đủ/nối lại/thu hồi quyền; demo nhận trạng thái qua WebSocket và stream qua proxy thật. Đây là bằng chứng cục bộ, chưa phải CI hay nghiệm thu staging. Dữ liệu kiểm thử/demo nằm trong DB riêng, không đổi database csms gốc. Chưa commit/push/merge.

## Rà soát sau kiểm thử thủ công ngày 02/10/2026

Trụ DEMO-OCPP-01 ngoại tuyến vì simulator `--hold 3600` đã hết thời gian và kết thúc bình thường. Không còn Heartbeat thì S-12 phải chuyển offline; đây không phải lỗi khiến mất liên lạc. Simulator bổ sung `--hold 0` để chạy đến khi chủ động dừng và thông báo khi hết thời lượng hữu hạn. Chạy demo hiện tại: `python scripts/ocpp_simulator.py --url ws://127.0.0.1:8003 --code DEMO-OCPP-01 --monitor --hold 0`.

Đối chiếu lại AC/NFR S-09–S-12 từ backlog gốc. Kiểm thử 50 trụ bổ sung StatusNotification đồng thời bên cạnh ghi liên lạc. Đo lại qua proxy: cập nhật SSE 0,528 giây; im lặng chuyển offline/unknown; Heartbeat phục hồi online với đầu nối unknown; StatusNotification và kết nối SSE mới có snapshot đầy đủ. Màn hình thực tế đã xác nhận trụ online, đầu nối 1 Charging, đầu nối 2 Faulted.

Định vị là phần bản đồ, không thuộc S-09–S-12. Trên máy người dùng, Chrome/Edge đều timeout dù đã cấp quyền; chưa xác định được nguyên nhân nguồn định vị. Đã sửa giao diện phân biệt từ chối quyền/nguồn vị trí không khả dụng/timeout; báo đang lấy vị trí, chặn yêu cầu lặp, chờ tối đa 30 giây, cho phép kết quả cache dưới một phút, giữ chọn vị trí thủ công và bỏ qua callback sau unmount. Kiểm thử lỗi/retry, chọn thủ công, thành công và unmount đạt; chưa xác nhận lấy vị trí thực tế trên máy người dùng.

Kết quả rà soát: 225 backend và 120 frontend tests đạt; lint/build/Ruff/mypy đạt, migration nâng/hạ/nâng lại đạt trên DB kiểm thử riêng. Không có sửa backend giám sát sau rà soát; bổ sung kiểm thử trạng thái đồng thời, cải thiện simulator và xử lý lỗi định vị. Chưa commit/push/merge.


## Bổ sung T-26 — thống nhất giờ database

`last_seen_at` được ghi bằng PostgreSQL `clock_timestamp()` sau khi lấy
khoá dòng trụ. Job ngoại tuyến lấy một mốc giờ database cho mỗi lượt quét,
giữ ngưỡng quá hai chu kỳ heartbeat, SKIP LOCKED và cập nhật idempotent.
Các tham số `now` chỉ phục vụ kiểm thử có mốc thời gian cố định.

Snapshot theo dõi lấy `statement_timestamp()` trong cùng truy vấn hiện có
(một truy vấn cho toàn bộ trụ), để các dòng cùng mốc thời gian. Phép kiểm
ngoại tuyến trước RemoteStart cũng đọc giờ database. Deadline lệnh, kiểm
phiên đăng nhập và timestamp lỗi/trạng thái OCPP giữ phạm vi hiện hành.

Không thêm migration, API hoặc thay đổi giao diện. Không triển khai T-20,
T-40 hay T-48. Kiểm thử phủ đồng hồ ứng dụng lệch ±7 ngày, đúng ranh giới
hai chu kỳ, đọc clock một lần mỗi lượt quét, clock trong giao dịch đã mở,
nhánh trụ đã khoá và rollback của người gọi. Luồng RemoteStart có test
khẳng định không gửi lệnh khi giờ database cho thấy liên lạc đã hết hạn.

Kiểm chứng local 08/10/2026: 104 test liên quan đạt trên PostgreSQL 16
riêng, gồm 8 ca mới và hai ca latency 20 trụ; 4 cảnh báo deprecation có sẵn.
Ruff lint, format (259 file), mypy (92 file) và diff check đạt.
Database thử rỗng upgrade đến head b150015a2026 đạt.

Hồi quy backend đầy đủ sau triển khai, trên database PostgreSQL 16 thử riêng:
811 passed, 2 deselected, 4 cảnh báo deprecation có sẵn, 185,08 giây.
Hai ca deselected đã chạy riêng trước bộ chức năng theo cấu hình CI:
- MeterValues 20 trụ: đạt, độ trễ tối đa 104 ms.
- WebSocket thật 20 trụ, ba chu kỳ: đạt, tối đa 129,9 ms.
Tổng 813 ca backend đạt; không có ca chức năng/latency bị bỏ qua.
CI của PR và nghiệm thu staging chưa được chạy trong lượt này.