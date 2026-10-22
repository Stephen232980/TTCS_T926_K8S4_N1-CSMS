# S-60 — Đổi cấu hình trụ từ xa

## Phạm vi

Vận hành viên đọc và đổi hai khóa OCPP 1.6: `HeartbeatInterval` (30–600 giây) và `MeterValueSampleInterval` (5–300 giây). Nguồn phạm vi: Backlog CSMS, S-60; bản refine Sprint 6–8, mục S-60. Giao diện nằm trong chi tiết trụ của màn hình vận hành, mặc định thu gọn.

## Luồng xử lý

1. Đọc `GetConfiguration`, hiển thị giá trị thực và thuộc tính chỉ đọc.
2. API kiểm tra quyền operator, whitelist, số nguyên và giới hạn; trả 422 trước khi gửi OCPP nếu sai. Trụ ngoại tuyến hoặc có yêu cầu đang chờ trả 409.
3. Lưu intent UUID và audit vào PostgreSQL trước khi worker gửi lệnh. Chỉ một intent đang hoạt động trên mỗi trụ. Gửi lại cùng UUID và nội dung trả lại yêu cầu cũ; khác nội dung trả 409.
4. Worker đọc giá trị cũ, ghi audit rồi gửi `ChangeConfiguration`, hạn chờ 30 giây. Phân biệt Accepted, Rejected, NotSupported, RebootRequired, Timeout, Disconnected và ProtocolError.
5. Accepted chưa phải thành công: đọc lại khóa để xác minh giá trị đúng, có hỗ trợ và có thể ghi. Chỉ trạng thái `verified` mới cập nhật heartbeat dùng cho liveness. Heartbeat đã xác minh được giữ khi BootNotification lại, thay vì quay về mặc định. Mismatch/readonly/unknown không được báo thành công.
6. RebootRequired giữ trạng thái chờ. Người dùng xác nhận riêng mới tạo intent `Reset` loại Soft. Chặn reset khi có phiên sạc hoặc yêu cầu bắt đầu đang hoạt động; chặn phiên mới trong lúc reset đã xác nhận còn đang chờ áp dụng.
7. Worker đọc lại sau reconnect. Khi timeout hoặc tiến trình chết giữa lúc gửi, chỉ đọc lại để đối chiếu, không tự gửi lại ChangeConfiguration hay Reset. UI thử lại cùng UUID nếu mất phản hồi HTTP.

Lease và thời điểm xử lý dùng đồng hồ PostgreSQL. Không giữ khóa DB trong lúc chờ phản hồi OCPP, vì chính đường nhận CALLRESULT cũng cần ghi nhận liên lạc của trụ. Audit lưu actor, request UUID, khóa, giá trị cũ/mới/đọc lại và kết quả; không nhận khóa cấu hình tùy ý hay bí mật.

Mỗi lượt xử lý có UUID riêng; kết quả đọc cũ không được ghi đè xác nhận reset mới. Nếu Reset mất phản hồi hoặc phản hồi không hợp lệ, giữ chặn phiên mới và chỉ đọc lại. Reset cũng bị chặn khi trạng thái đầu nối báo Preparing/Charging/SuspendedEV/SuspendedEVSE/Finishing dù chưa có phiên tương ứng trong DB. Xác nhận API phải là boolean `true`; không chấp nhận số `1`.

## API

| Phương thức | Đường dẫn dưới `/api/v1` | Ý nghĩa |
|---|---|---|
| GET | `/ops/charge-points/{id}/configuration` | Đọc trụ và lịch sử 10 yêu cầu gần nhất |
| GET | Đường dẫn trên, `?refresh=false` | Chỉ đọc trạng thái bền vững, không gửi lệnh OCPP |
| POST | `/ops/charge-points/{id}/configuration` | `{request_id, key, value}` |
| POST | `/ops/charge-points/{id}/configuration/reset` | `{request_id, intent_id, confirm: true}` |

Quyền tương ứng: `ops.configuration.read/change/reset`, operator. Người không có quyền không thấy phần cấu hình. Response dùng no-store và lỗi validation được làm sạch.

Migration: `j240024a2026`, sau `i230023a2026`; bảng `ocpp_configuration_intents` có ràng buộc khóa/trạng thái và unique partial index cho intent đang hoạt động. Adapter GetConfiguration dùng chung với phần phân bổ công suất.

## Bằng chứng và giới hạn

- Kiểm thử PostgreSQL: durable intent, replay, chống gửi trùng, audit, readback, heartbeat, timeout, restart worker, quyền và reset gate.
- Kiểm thử WebSocket thật đi qua bộ nhận phản hồi OCPP và PostgreSQL, dùng handler của demo simulator; kiểm tra cả hai khóa, RebootRequired → xác nhận Reset → readback. Giá trị được giữ khi tạo lại simulator từ file cấu hình.
- Kiểm thử giao diện: thu gọn/ẩn theo quyền, giới hạn đầu vào, không báo thành công sớm, retry cùng UUID, xác nhận reset, chặn khi đang sạc và polling chỉ đọc.
- Sau rà soát: 327 kiểm tra backend chức năng đạt, gồm 28 trường hợp S-60; 20 kiểm tra bổ sung simulator/đối soát đạt (có trùng một phần với bộ trên). Frontend chạy tuần tự: 426/426 đạt. Ruff, mypy toàn bộ src, TypeScript, lint các file giao diện thay đổi và build đạt.
- Hai cổng tốc độ giữ nguyên ngưỡng 200 ms nhưng chưa đạt ổn định trên Windows. S-60 trên DB mới đo trước chức năng: MeterValues trực tiếp 248 ms, 20 socket thật 287 ms. Develop gốc trong lần đối chiếu riêng đạt, nhưng đo luân phiên cùng DB cũng có lần thất bại ở cả hai bản. Chưa xác định nguyên nhân; không kết luận toàn bộ hồi quy xanh hoặc không có hồi quy hiệu năng. Hai cổng tốc độ của CI vẫn là điều kiện merge.
- Chưa triển khai hay nghiệm thu S-60 trên staging, chưa kiểm tra trụ vật lý. Trình duyệt cục bộ bị tắt trong Work settings nên chưa xác minh giao diện bằng ảnh.

## Nghiệm thu staging sau merge

1. Chờ image mới và migration tới `j240024a2026`.
2. Simulator staging dùng script được mount riêng: cập nhật `scripts/staging_demo.py` bằng quy trình cập nhật có bảo vệ phiên/hold; không seed lại dữ liệu. Nếu script cũ, backend mới chưa đủ để demo hai khóa này.
3. Đăng nhập operator, chọn trụ online, đọc hai khóa; đổi lần lượt heartbeat 60 và chu kỳ số đo 15. Chờ Đã xác minh, đối chiếu GetConfiguration, PostgreSQL heartbeat và audit.
4. Kiểm tra giá trị ngoài phạm vi bị từ chối, readonly/unknown/Rejected không thành công, ngoại tuyến và mất phản hồi không gây gửi trùng.
5. Với thiết bị hỗ trợ RebootRequired, xác nhận không có reset tự động; reset bị chặn khi đang sạc. Khi hết phiên, xác nhận Soft Reset, reconnect và đọc lại trước khi kết luận thành công.
6. Khôi phục giá trị ban đầu qua cùng luồng và lưu bằng chứng. Chỉ cập nhật Jira Done khi nghiệm thu đạt.
