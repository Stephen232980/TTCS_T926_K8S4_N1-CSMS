# G4 — S-66 hoạt động trạm, S-47 tìm trạm và đầu nối rảnh

G4 mở rộng khu vực owner và bản đồ driver hiện có. Không bổ sung đặt/hủy chỗ G5; cấu hình SMTP G3 giữ mặc định hiện có và thực hiện sau.

## Owner bật/tạm ngừng

`PATCH /api/v1/owner/stations/{station_id}/operation`

```json
{"status":"suspended","expected_version":1,"reason":"Bảo trì định kỳ"}
```

Chỉ `station_owner` thuộc đúng trạm được gọi. `status` nhận `active` hoặc `suspended`; reason sau trim bắt buộc khi suspend, tối đa 500 ký tự. Owner không tự mở trạm `blocked` của admin. Trạm archived trả 404; cross-owner 403.

Bật trạm từ inactive/suspended cần tên/địa chỉ/tọa độ hợp lệ, ít nhất một đầu nối chưa archive, biểu giá hiệu lực theo ngày tại trạm với các khung giờ phủ đủ 0..1440 và kiểm tra lại admission power nếu đang bật chia tải. Suspend chỉ từ active. Các trường đầu nối tùy chọn giữ contract hiện có; thiếu thông số được hiển thị là chưa khai báo.

Response là StationResponse hiện có, thêm `status_version` (bắt đầu 1). Station row lock serialize đổi trạng thái và biên admission. `expected_version` chống ghi đè ý định cũ; cập nhật cấu hình trạm cũng tăng version. Retry cùng trạng thái, cùng version hoặc ngay phiên bản kế tiếp là no-op, không ghi audit trùng. Ý định khác với version cũ trả 409. Chuyển trạng thái và audit before/after/actor/reason cùng transaction.

Các mã 409: `station_admin_blocked`, `station_version_conflict`, `station_transition_invalid`, `station_configuration_incomplete`, `station_connector_required`, `station_tariff_required`, `power_unavailable`; body/lý do không hợp lệ 422, chưa đăng nhập 401.

Trạm suspended biến mất khỏi discovery. REST RemoteStart, OCPP Authorize và StartTransaction kiểm trạng thái DB tại biên admission, kể cả socket đã boot trước đó. StartTransaction đến muộn bị Blocked/transactionId 0 và giữ nguyên phiên đang mở; yêu cầu driver tương ứng lưu `station_unavailable` để UI phục hồi đúng trạng thái. Một admission đã được chấp nhận trước suspend có thể đã gửi lệnh; StartTransaction mới vẫn kiểm lại DB. Không gửi RemoteStop/Reset hàng loạt, không sửa liveness/Available giả.

MeterValues, StopTransaction, bằng chứng rút súng, invoice và wallet settlement của phiên hiện hữu tiếp tục bình thường. Resume có hiệu lực trên cùng socket, không cần reconnect. DB là nguồn trạng thái; `connection.station_status` là snapshot cũ và không quyết định admission.

## Driver tìm trạm

Mở rộng `GET /api/v1/driver/stations`, giữ `search`, `page>=1`, `page_size=1..100`; chỉ driver, chỉ trạm active chưa archived. Các trường bổ sung:

| Trường | Ý nghĩa |
| --- | --- |
| `available_connectors`, `total_connectors` | Đầu nối rảnh / tổng khai báo chưa archive trên trụ chưa archive |
| `connectors` | id, connector_type, current_type, max_power_kw, available; không có thông tin chủ trạm/tài xế/thẻ |
| `energy_rate_vnd_per_kwh` | Đơn giá khung giờ đang hiệu lực tại múi giờ trạm, null nếu chưa có giá |
| `idle_rate_vnd_per_minute`, `grace_minutes` | Phí chiếm chỗ và thời gian miễn của biểu giá đó |
| `generated_at`, `refresh_after_seconds` | Thời điểm DB tạo projection; chu kỳ UI 15 giây |
| `search_too_broad` | Hơn 500 trạm phù hợp: items rỗng, yêu cầu thu hẹp tìm kiếm |

Rảnh chỉ khi trụ online, đã boot, last_seen không ở tương lai và trong 2×heartbeat; không lỗi cấp trụ; connector Available; không phiên còn mở hoặc phiên lifecycle v1 chưa giải phóng cáp; không yêu cầu start Pending/Accepted còn lease. Reserved/Preparing/Finishing/Faulted/unknown/offline không đếm rảnh. Query tổng hợp theo các trạm trong trang, không gọi DB riêng cho từng trạm. Giá lấy phiên bản mới nhất có hiệu lực và đúng khung phút địa phương; không lấy biểu giá tương lai hoặc gán giá 0 khi chưa có giá.

Driver tải đủ tối đa 5 trang trước khi sắp gần theo khoảng cách đường thẳng, tie-break tên/id. Nếu danh sách thay đổi trong lúc tải, UI giữ snapshot cũ và yêu cầu tải lại thay vì sắp một phần. Geolocation nằm trong trình duyệt; từ chối/timeout vẫn tìm tên/địa chỉ được. Không thêm nhà cung cấp bản đồ/định tuyến.

Polling khi tab visible, abort khi đổi tìm kiếm/unmount, không chồng request; thất bại giữ dữ liệu cũ kèm thông báo và khóa thao tác mở đầu nối từ snapshot lỗi. Chỉ thay giá/trạng thái không dựng lại marker hoặc reset vùng nhìn bản đồ. Trạm chưa có giá vẫn hiện thông tin, không có nút mở luồng sạc trên thẻ discovery. Backend start hiện có tiếp tục recheck điều kiện tài khoản/ví/trạm/công suất; projection không giữ chỗ hay cấp quyền sạc.

## Migration và kiểm chứng

Migration `c230023a2026` nối `b220022a2026`, thêm `stations.status_version`. Cấp quyền runtime theo quy trình staging hiện có. Upgrade → downgrade → upgrade trên PostgreSQL 16 giữ dữ liệu trạm; downgrade bỏ thông tin version mới.

Local đã kiểm: RBAC/cross-owner, blocked, reason, activate validation, version/retry đồng thời, suspend thắng race Start, giữ phiên hiện hữu, online/liveness/Reserved/Finishing/pending lease, giá qua nửa đêm, giới hạn tìm kiếm. WebSocket TCP thật chứng minh suspend → từ chối phiên mới → Meter/Stop/EVDisconnected → invoice/trừ ví → resume/Authorize trên cùng socket.

500 trạm / 50 trụ: tối đa khoảng 21–89 ms trong các lượt 5 request local (không phải số đo staging p95). Hai gate OCPP 20 trụ đạt tối đa 83 ms và 155 ms, dưới 200 ms. Desktop 1366×768 và mobile 360×800 đã kiểm bằng login/API thật với dữ liệu demo ghi nhãn local. Review UI độc lập: ship; fix map-refresh được chấp nhận riêng bằng source inspection.

Frontend 365 tests, lint và build đạt; Ruff lint/format và mypy đạt. Full backend ghi nhận 1.926 passed, một lỗi snapshot route inventory đã sửa; nhóm hồi quy cuối trên DB sạch (G4, real socket, policy, charging và power) đạt 169 passed. Hai gate latency chạy riêng đều đạt. Build còn cảnh báo chunk >500 kB hiện có.

G5 cần bổ sung predicate hold đặt chỗ bền vào projection và workflow S-51 hủy reservation chưa consumed khi suspend; hiện chưa có domain reservation trong hệ thống. CI, staging, trụ thật và acceptance/Jira là các bằng chứng riêng, không suy ra từ local tests.
