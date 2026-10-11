# S-10 / T-20 — nhóm trạng thái đầu nối dùng chung

Phạm vi đã được người dùng chốt ngày 08/10/2026: giữ trạng thái OCPP chi
tiết, bổ sung sáu nhóm hiển thị/báo cáo thay cho yêu cầu bốn nhóm trong
bảng task cũ. StatusNotification không hợp lệ bị từ chối theo giao thức,
ghi log chẩn đoán an toàn và không ghi đè quan sát hợp lệ.

## Triển khai

`src/modules/stations/connector_status.py` là nguồn ánh xạ chung:

| OCPP | Nhóm | Hiển thị |
| --- | --- | --- |
| Available | available | Rảnh |
| Preparing, Charging, SuspendedEV, SuspendedEVSE, Finishing | occupied | Đang sử dụng |
| Reserved | reserved | Đặt chỗ |
| Unavailable | unavailable | Không khả dụng |
| Faulted | faulted | Lỗi |
| Không nhận diện hoặc thiếu quan sát | unknown | Chưa rõ |

Response đầu nối của API quản lý trạm/trụ, snapshot/SSE OCPP và danh sách
đầu nối tài xế có thêm `status_group`. Các model response tính trường
này khi serialize, không lưu bản sao trong database. Snapshot ngoại tuyến
giữ status/group unknown; API cấu hình mô tả quan sát được lưu.
Nhóm tổng hợp không phải quyền bắt đầu sạc. Các kiểm tra trạm, liveness,
đầu nối, phiên và yêu cầu đang chờ vẫn chạy bằng logic hiện hành.

Log `ocpp_invalid_status_notification` chỉ chứa UUID trụ nội bộ. Không
ghi trạng thái tuỳ ý, info hay payload; replay dùng cache lỗi có sẵn và
không ghi log lần nữa. Không thêm migration, bảng hay cột; không sửa giao
diện, thuật toán tính phí hoặc mở rộng T-63/T-40/T-48.

## Kiểm chứng trước tối ưu

- 25 ca mới: đủ chín trạng thái, giá trị không nhận diện, serialize hai
  model response, offline, lỗi giao thức, log không lộ dữ liệu và replay.
- Test API tài xế hiện có được bổ sung khẳng định cả status và status_group.
- 80 ca tập trung đạt. Ruff toàn repo, format 261 file, mypy 93 file đạt.
- PostgreSQL 16 riêng: database rỗng upgrade đến head b150015a2026 đạt.
- MeterValues 20 trụ đạt, tối đa 103 ms.

Kiểm tra socket thật 20 trụ chưa đạt ngưỡng 200 ms trong lượt này: trên
nhánh T-20 tối đa 221,6 ms và 223,3 ms; database mới vẫn có 226,7 ms.
Đối chứng nhánh T-26 sạch (6724f60, chưa có T-20) cùng database cũng lỗi
211,3 ms. Chưa xác định nguyên nhân; không suy diễn đây là hồi quy do T-20,
không tăng ngưỡng hay bỏ gate. Phần điều tra và tối ưu tiếp theo được ghi dưới đây. CI và staging cần
bằng chứng riêng.

Hồi quy chức năng backend đầy đủ: 836 passed, 2 deselected, 4 cảnh báo
deprecation có sẵn, 205,20 giây. Hai ca deselected là gate latency chạy
riêng: MeterValues đạt; WebSocket thật chưa đạt như mô tả ở trên. Không
coi kết quả này là toàn bộ gate đạt. Kết quả trước tối ưu được giữ để đối chiếu.


## Điều tra và tối ưu trước commit

Đã đo tại dispatch và SQL trên WebSocket thật, không log tham số SQL.
Lượt có instrumentation đạt nhưng vẫn chỉ ra thời gian chờ các lượt SQL
chiếm phần lớn dispatch: MeterValues max dispatch 136,1 ms, max tổng thời
gian await SQL 129,8 ms; thời gian đến SQL đầu tiên tối đa 1,8 ms. Đây là
thời gian ở phía ứng dụng (gồm network/scheduling), không phải phép đo
thời gian thực thi thuần trong PostgreSQL. Số liệu không đủ khẳng định
nguyên nhân mọi dao động của máy Windows/Docker.

Điểm thừa xác định được: mỗi CALL đọc clock_timestamp() riêng rồi UPDATE
last_seen_at. Đổi thành UPDATE last_seen_at=clock_timestamp() RETURNING
last_seen_at, sau khi đã lấy khoá dòng. Giá trị trả về là chính mốc thời
gian vừa lưu và dùng kiểm tra liên lạc quá hạn. Giảm một round trip mỗi
CALL, kể cả replay, giữ giao dịch và bất biến updated_at. Tham số now
kiểm thử vẫn được hỗ trợ. Trụ archived không cập nhật. Job ngoại tuyến
vẫn chỉ đọc clock một lần/lượt; không thay ngưỡng hoặc pool/timeout.

Test chống hồi quy khẳng định nhánh trụ đã khoá chỉ dùng một câu UPDATE
và đọc lại thời gian đã lưu. Tối ưu này thuộc phần T-26 dùng chung trên
đường xử lý OCPP; được bổ sung theo yêu cầu điều tra hiệu năng trước commit.

Sau tối ưu, ba lượt socket thật độc lập (không instrumentation) đều đạt:
| Lượt | Chu kỳ 1 | Chu kỳ 2 | Chu kỳ 3 |
| --- | --- | --- | --- |
| 1 | 114,8 ms | 120,5 ms | 173,1 ms |
| 2 | 110,0 ms | 118,2 ms | 111,1 ms |
| 3 | 125,1 ms | 122,3 ms | 117,5 ms |

Ngưỡng 200 ms, payload, số trụ, cadence, số chu kỳ và yêu cầu durable
commit trước phản hồi giữ nguyên. Gate MeterValues cũng đạt sau tối ưu.
Ruff toàn repo, format 262 file, mypy 93 file và diff check đạt.
Hồi quy sau tối ưu trên database PostgreSQL 16 mới: 837 passed,
2 deselected, 4 cảnh báo deprecation có sẵn, 182,79 giây. Hai ca deselected
đã chạy riêng và đạt như trên: tổng 839 ca backend đạt. Kết quả này thay
thế trạng thái gate chưa đạt ở mục kiểm chứng trước tối ưu.
CI/staging cần được xác nhận riêng. Container database thử đã dừng, không thay đổi app/database
ứng dụng hiện hành.