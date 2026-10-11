# API quản trị — Nhật ký thao tác và Sức khỏe hệ thống

Nhóm tiếp theo sau API Tài khoản & vai trò (merge main `203fa97`). Thiết kế
đã chốt: tài khoản mẫu 1, nhật ký mẫu 3, sức khỏe mẫu 2. Thay đổi này chỉ là
backend; giữ nguyên thiết kế và chưa triển khai frontend. S-63 được làm sớm
phục vụ demo Sprint 2–3, không khẳng định các story Later đã nghiệm thu đầy đủ.

## Nhật ký thao tác

Giữ API S-27 `GET /api/v1/ocpp/control-audit`, quyền admin, bộ lọc trụ,
người thực hiện, khoảng thời gian và phân trang. Payload/actor/trụ/thời gian/
kết quả vẫn theo `OCPP_CONTROL_DELIVERY.md`. Accepted là trụ chấp nhận lệnh,
không phải đã hoàn thành hành động vật lý. Không thay đổi API gửi lệnh.

Thêm `GET /api/v1/admin/account-audit`, chỉ admin, đọc dữ liệu
`account_audits` được nhóm tài khoản lưu cùng giao dịch. Bộ lọc:

- `page` >= 1, mặc định 1; `page_size` 1..100, mặc định 20.
- `actor_email`: khớp chính xác sau strip/lowercase, tối đa 320 ký tự.
- `target_id`: UUID tài khoản được thao tác.
- `action`: `account_created` hoặc `account_updated`.
- `from_at`, `to_at`: ISO8601 có timezone, quy về thời gian UTC; inclusive.
  Khoảng thời gian đảo ngược trả 422.

Response `items/page/page_size/total/total_pages`, sắp xếp created_at DESC,
id ASC. Mỗi item có `id`, `actor_id`, `actor_email`, `target_id`, `action`,
`created_at`, `before`, `after`. before=null khi tạo; state chỉ gồm email,
roles, status. Email người thực hiện lấy từ User hiện tại; email đối tượng
trong state là bản ghi lúc thao tác. Không trả mật khẩu, hash hoặc token.
Không có endpoint ghi/sửa/xóa nhật ký. Không gộp nhật ký tài khoản vào bảng
điều khiển OCPP và không giả các thao tác tài khoản thành lệnh tới trụ.

Frontend có thể dùng hai nguồn trong màn nhật ký đã chốt, phân biệt loại thao
tác và chỉ hiện trường liên quan; chưa làm UI hay quyết định thêm tab chính.

## Sức khỏe hệ thống

| API | Công dụng |
| --- | --- |
| GET `/api/v1/admin/system-health` | Snapshot gần nhất, freshness và thời gian cập nhật |
| GET `/api/v1/admin/system-health/history` | Lịch sử 24 giờ; có khoảng trống thật |

Chỉ `admin`. API mới dùng error contract như nhóm tài khoản; Cache-Control
no-store, 401/403/422. Không gửi lệnh hoặc ghi dữ liệu qua các GET này.

### Bốn chỉ số và định nghĩa cho phạm vi demo

1. `online_charge_points`: trụ chưa archive, trạm chưa archive/blocked,
   ChargePoint.status=online, đã có Boot hợp lệ, last_seen không ở tương lai
   và còn trong hai chu kỳ Heartbeat. Tính từ DB, không suy từ icon UI hoặc
   số socket riêng của trình duyệt. `registered_charge_points` là tổng trụ
   chưa archive thuộc trạm chưa archive, bao gồm trụ offline/blocked.
2. `running_sessions`: phiên chưa kết thúc, chưa bị đánh dấu abnormal, đã bắt
   đầu; đầu nối chưa archive, status=charging và raw OCPP status=Charging,
   trụ online theo quy tắc trên. Phiên đang mở nhưng offline hoặc SuspendedEV
   không được tính là đang truyền điện. Đây là chỉ số theo trạng thái báo cáo,
   không chứng minh dòng điện tức thời luôn dương.
3. `error_messages_5m`: số lượt trao đổi OCPP có lỗi trong cửa sổ 5 phút đã
   đóng, căn mốc 30 giây. Một lượt có CALLERROR nhận/gửi hoặc StatusNotification
   errorCode khác NoError được tính một lần, kể cả lỗi đầu nối 0. Tin replay
   lỗi thực sự nhận lại là một lượt mới. Không đếm số đầu nối đang lỗi; không
   đếm login/HTTP error hoặc Rejected trong CALLRESULT là lỗi giao thức.
4. `response_latency_ms`: trung bình có trọng số theo số CALL OCPP hợp lệ đã
   phản hồi, từ lúc backend nhận vào handler tới khi gửi xong phản hồi
   (bao gồm xử lý DB và hàng đợi gửi). Đây không phải RTT mạng tới trụ hoặc
   thời gian trụ thực thi lệnh. Không có mẫu phản hồi thì null, không phải 0.

Các định nghĩa này là quyết định triển khai demo cần đối chiếu khi refine
S-63; không có ngưỡng tự suy diễn "hệ thống ổn" hoặc cảnh báo S-46.

### Snapshot và dữ liệu chưa đầy đủ

Response có `generated_at`, `refresh_after_seconds=30`,
`stale_after_seconds=90`, `status` current/stale/no_data và `snapshot`.
Đây là trạng thái độ mới dữ liệu, không phải đánh giá tốt/xấu của hệ thống.
Snapshot null khi chưa thu được bản ghi; khi stale giữ dữ liệu cùng thời điểm
gần nhất để UI đánh dấu rõ, không giả cập nhật thành công.

Snapshot gồm collected_at, window_start/window_end và metrics:
online_charge_points, registered_charge_points, running_sessions,
error_messages_5m, error_messages_observed_5m, response_latency_ms,
response_count_5m, window_complete. Cửa sổ lỗi/độ trễ kết thúc ở mốc 30 giây
gần nhất trước collected_at; khoảng [window_start, window_end).

Chưa đủ 10 bucket hoàn chỉnh trong 5 phút, error_messages_5m=null và
window_complete=false. observed là số lỗi đã ghi nhận, không phải tổng đủ
cửa sổ. Độ trễ có thể có mẫu thật nhưng chưa đủ thời gian quan sát; frontend
phải hiển thị tình trạng chưa đầy đủ. Không có CALL trong cửa sổ đầy đủ thì
latency=null và response_count=0. Không có tin lỗi trong cửa sổ đầy đủ mới
hiển thị lỗi=0.

### Lịch sử

`resolution_seconds` nhận 30, 60, 300, 900, 1800 hoặc 3600 (mặc định 3600).
Response gồm from_at/to_at (UTC), resolution_seconds,
aggregation=latest_observation, available_since (bản ghi sớm nhất còn lưu)
và points. Điểm có bucket_start, measured_at, metrics; missing observation
thì measured_at/metrics=null. Mặc định 25 bucket theo giờ, gồm bucket hiện
tại chưa đầy đủ, tối đa 2881 bucket cho độ phân giải 30 giây.

Mỗi bucket chọn snapshot cuối, không cộng các giá trị rolling-5m thành tổng
giờ, không nội suy hoặc carry-forward qua khoảng mất dữ liệu. Dùng measured_at
để biết thời điểm thực đo. Lịch sử chỉ bắt đầu từ khi collector chạy; không
seed dữ liệu minh họa hoặc tạo quá khứ giả trước khi triển khai.

## Thu thập và vận hành

- Lifecycle FastAPI tự thu snapshot mỗi 30 giây; GET không tạo snapshot theo
  lượt truy cập. Frontend sau này poll theo refresh_after_seconds.
- OCPP hot path chỉ tăng bộ đếm trong bộ nhớ, không ghi DB bổ sung trên mỗi
  tin. Đợt collector lưu bucket tổng hợp theo process và sample vào PostgreSQL.
  Không lưu payload, thẻ tài xế hoặc nội dung tin trong telemetry.
- Upsert theo timestamp/process và giá trị tuyệt đối; retry giao dịch lỗi
  không cộng đúp. Chỉ acknowledge dirty counter sau commit, giữ cập nhật đến
  trong lúc flush. Advisory lock bảo vệ sampler đồng thời.
- Retention 25 giờ cho sample/telemetry, đủ cửa sổ 24 giờ; bộ đệm cũng bị giới
  hạn theo thời gian. Nếu process chết đột ngột có thể mất tối đa khoảng dữ
  liệu chưa flush, không phải cơ chế audit bảo đảm exactly-once. Sau restart
  không giả phần chưa quan sát thành đầy đủ.
- Phạm vi demo là một backend process như kiến trúc OCPP registry hiện tại.
  Chưa cam kết đầy đủ toàn mạng nhiều worker/replica hoặc tích hợp Prometheus.
  Telemetry có worker_id để tránh ghi đè, nhưng cần thiết kế registry/coverage
  phân tán trước khi coi dữ liệu multi-replica là tổng chính xác.
- Collector lỗi DB ghi log, vòng sau thử lại; API sẽ trở thành stale nếu vẫn
  đọc được DB. Nếu DB không đọc được, không trả bản ghi giả thành current.

Migration `c630005a2026`, sau `b610003a2026`, thêm
`system_health_samples`/`ocpp_telemetry_buckets`. Chạy `alembic upgrade head`
và khởi động lại backend mới. Khi mới chạy, có thể xem snapshot ngay nhưng
cửa sổ 5 phút cần tích lũy; biểu đồ 24 giờ đầy dần theo dữ liệu thực tế.

## Kiểm chứng

### Hồi quy khi chạy demo OCPP

Phép đếm phiên đang sạc dùng trạng thái `Charging` đúng như
`StatusNotification` lưu ở monitoring. Trước đây bộ lọc `charging` không
khớp bản tin thật, nên trụ trực tuyến và phiên có số đo vẫn bị đếm là 0.
Fixture kiểm thử đã dùng trạng thái chuẩn OCPP; có kiểm thử đường ghi
`report_status` từ Available → Charging → SuspendedEV → Charging,
kiểm tra số phiên lần lượt 0 → 1 → 0 → 1. Không thay đổi tiêu chí loại
phiên đã đóng, bất thường, trụ ngoại tuyến, trạm bị khóa hoặc thiết bị archive.

13 test mới đạt qua PostgreSQL schema riêng và HTTP: số liệu thật, phiên
paused/offline không đếm như running, lọc trụ archive/blocked, trọng số độ trễ,
window warm-up, stale, lịch sử null, quyền admin, lọc/read-only audit, rollback
và retry không nhân đôi, bộ đệm giữ cập nhật đồng thời và giới hạn retention,
instrumentation OCPP không thêm I/O DB vào hot path. Mypy toàn src, Ruff và
Alembic check đạt.

Full regression trên PostgreSQL database riêng: **385/385 đạt**, bao gồm bài
20 trụ/phản hồi MeterValues <200 ms trong lượt chạy này. Kết quả này không
phải sửa/cam kết hiệu năng mọi máy (lượt nhóm tài khoản trước từng đo 206 ms).
Migration từ DB trống, downgrade về `a4d901ce8207` và upgrade lại đều đạt;
database/schema kiểm thử riêng đã được xóa sau khi kiểm chứng. Dữ liệu demo
giữ nguyên. Migration mới đã áp dụng cho DB phát triển local; cần restart
backend để collector chạy. Chưa commit/push, chưa kiểm chứng CI remote.
