# S-48 / S-49 / S-51 — G5 đặt và hủy chỗ

## Cập nhật S-48: giao diện và simulator demo

Ở màn đầu nối của tài xế, nút Quay lại bản đồ và danh sách đứng trước mục
Đặt chỗ của bạn. Mục này khi đóng cao 44px. Dưới nút Bắt đầu sạc là nút
Đặt trước đầu nối có chiều rộng bằng nút bắt đầu sạc; khi bấm mở popup chọn giờ/phí,
có nút Xác nhận đặt chỗ và Hủy. Popup giữ focus, hỗ trợ Escape, trả focus về nút
khi đóng; hủy trước khi gửi không tạo booking. Nếu kết quả gửi trước đó chưa rõ,
đóng popup vẫn giữ UUID để thử lại an toàn. Chưa xác minh capability
thì nút này tự gửi yêu cầu kiểm tra. Nếu sau 20 giây chưa có kết quả, UI báo
chưa nhận phản hồi và cho thử lại; không báo đã đặt thành công hoặc tự bỏ hold.
Retry capability có thể kiểm lại kết quả unsupported/lỗi trên cùng boot,
nhưng không chiếm lease của một probe đang chạy.

Thông báo popup chỉ gồm ba gạch đầu dòng: Phí không đến (giá trị từ policy hoặc
snapshot đã gửi), Không thu phí đặt trước, Có hiệu lực trong 15 phút. Checkbox
ghi Tôi đồng ý. Giữ kiểm tra đồng ý phí, ngày đến và idempotency hiện có.

`scripts/ocpp_control_simulator.py` hỗ trợ Core,SmartCharging,Reservation:
ReserveNow giữ đúng đầu nối/thẻ/hạn; CancelReservation và hết hạn phát
StatusNotification tương ứng; RemoteStart chỉ dùng đúng thẻ giữ chỗ và
StartTransaction gửi reservationId để backend consume. State giữ chỗ được lưu
cùng file profile để phục hồi khi restart; file chứa thẻ riêng, cần giữ trong
thư mục riêng của tài khoản chạy simulator, không đưa vào Git hay log.

Sau khi cập nhật code, phải restart các tiến trình simulator demo đang kết nối
để chúng dùng bản mới, rồi kiểm tra lại hỗ trợ ở giao diện. Chỉ triển khai backend/
frontend không tự cập nhật script đã được nạp vào tiến trình simulator cũ.
Không bật capability Reservation giả trên trụ không hỗ trợ.

`tests/test_s48_demo_reservations.py` chạy chính script simulator qua TCP tới
CSMS và kiểm API probe → đặt → hủy → đặt lại → RemoteStart → reservation consumed.
Đây là bằng chứng local; vẫn cần nghiệm thu trên staging sau triển khai và restart
simulator. Các kiểm thử unique/recovery/fee hiện có của G5/G6 được giữ nguyên.

G5 bổ sung giữ ngay một đầu nối cụ thể. Driver chọn đến ngay hoặc trong hai giờ tới; hạn giữ là giờ đến + 15 phút. Mỗi driver và mỗi đầu nối chỉ có một hold chưa được giải phóng. Không thu phí đặt trước; phí no-show S-50 thuộc G6.

## API và quyền

Tất cả endpoint dưới `/api/v1/driver/reservations` yêu cầu driver đã đăng nhập. Backend lấy chủ thể từ session, không nhận driver_id/idTag/reservationId từ trình duyệt.

| Method | Path | Body / kết quả |
|---|---|---|
| POST | `/capabilities` | `{connector_id}`; 202 supported/unsupported/unverified |
| POST | base | `{request_id: UUID, connector_id: UUID, arrival_at: aware datetime hoặc null}`; 202 intent |
| GET | base | `?page=1`; tối đa 20 mục, own scope, generated_at |
| GET | `/{id}` | own scope; 404 thiếu, 403 sai chủ |
| POST | `/{id}/cancel` | `{request_id: UUID}`; 202 intent hủy |

202 là đã ghi nhận intent, không phải trụ đã xác nhận. Response công khai không có card_id, idTag, ocpp_id hoặc driver_id. `can_cancel` tính bằng giờ DB và trạng thái; UI polling 5 giây khi tab hiện, giữ dữ liệu cũ có cảnh báo khi mất mạng.

Các lỗi chính: connector_reserved, driver_already_reserved, reservation_capability_unverified, reservation_unsupported, station_or_charger_unavailable, connector_unavailable, wallet_low/missing/locked, tariff_unavailable, power_unavailable, reservation_arrival_out_of_range, reservation_request_conflict, reservation_expired/consumed/not_cancellable. Body cấm trường ngoài schema; timestamp phải có timezone. Retry phải giữ nguyên UUID và body; UUID thuộc actor/payload, không tạo thêm hold/outbox/audit.

## OCPP và trạng thái

- Driver yêu cầu kiểm tra hỗ trợ; worker gửi GetConfiguration(SupportedFeatureProfiles) trên socket đã Boot Accepted. Chỉ profile Reservation xác minh cùng boot mới cho đặt. Boot mới làm proof cũ không còn hợp lệ. Không tự gửi probes tới mọi trụ cũ.
- Intent cùng transaction với hold, command và audit. Worker claim lease trước I/O, commit rồi gửi ReserveNow(connectorId, expiryDate, idTag riêng của driver, reservationId positive 32-bit). Không giữ khóa DB khi đợi mạng.
- ReserveNow chỉ gửi một lần. Accepted chuyển active; Occupied/Rejected/Unavailable/Faulted chuyển rejected. Timeout/disconnect/CALLERROR/payload sai hoặc crash sau claim chuyển uncertain, giữ khóa chống đặt trùng và không gửi ReserveNow mù lần hai.
- pending/uncertain/active/cancel_pending/expiry_release_pending đều giữ partial unique keys. Raw Reserved/Available chỉ đổi bởi StatusNotification của trụ, không bởi API intent hoặc ACK.
- Authorize, RemoteStart và StartTransaction kiểm tra hold và eligibility. StartTransaction cần đúng point/connector/private tag/reservationId; source timestamp phải nằm trong thời hạn, không tương lai quá 30 giây; cho chậm mạng tối đa 30 giây. Ví và công suất kiểm tra lại khi start. Consume và session trong một transaction; replay cùng message không tạo phiên mới. Một cancel/start race chỉ có một phía thắng.
- Driver hủy active/uncertain trước expires_at theo giờ DB: ghi cancel_requested_at và no_show_exempt ngay; ACK muộn không làm mất miễn trừ. CancelReservation Accepted mới giải phóng. Rejected/timeout vẫn cancel_pending, retry với message UUID mới cùng reservationId; backoff 15..240 giây.
- Trạm suspended làm các hold chưa dùng chuyển workflow hủy và miễn no-show; phiên đã dùng giữ workflow billing hiện có.
- Hết hạn chuyển expiry_release_pending và yêu cầu CancelReservation. Không ACK chỉ giải phóng sau expires_at+30 giây, trụ live, raw Available có source timestamp >= expiry (và không quá tương lai 30 giây), status_updated_at >= expiry, không có phiên mở/chưa rút súng. Heartbeat/Available cũ không đủ bằng chứng.
- Reserve chưa từng gửi có thể suppress và giải phóng trực tiếp. Capability lease 60 giây, command lease 60 + 2 × timeout giây, worker tick 2 giây, probe chưa rõ retry 30 giây. RESERVATION_COMMAND_TIMEOUT_SECONDS mặc định 5, range (0,30].

Quy tắc payload/status dựa trên [ReserveNow schema](https://raw.githubusercontent.com/mobilityhouse/ocpp/master/ocpp/v16/schemas/ReserveNow.json), [ReserveNow response](https://raw.githubusercontent.com/mobilityhouse/ocpp/master/ocpp/v16/schemas/ReserveNowResponse.json), [CancelReservation response](https://raw.githubusercontent.com/mobilityhouse/ocpp/master/ocpp/v16/schemas/CancelReservationResponse.json).

## DB, triển khai và giới hạn

Migration d240024a2026 nối c230023a2026, bốn bảng reservations/reservation_commands/reservation_events/reservation_capabilities; hai partial unique indexes; sequence không cycle, max 2147483647. Migration dùng DDL cố định, không import model thay đổi theo thời gian. Dùng runtime DB role/grants hiện có (bao gồm quyền sequence).

Triển khai kế thừa một OCPP gateway process của hệ thống. DB locks/outbox chịu được nhiều HTTP process cạnh tranh, nhưng socket registry vẫn trong process; chưa phải broker gateway phân tán. Mất socket/crash giữ hold để tránh đặt chồng. Trụ demo cần profile Reservation và phải phát đúng reservationId trong StartTransaction; cần commissioning thiết bị thật trước demo tại trụ vật lý.

## Bằng chứng kiểm thử

`tests/test_g5_reservations.py`: PostgreSQL thật, migration downgrade/upgrade giữ dữ liệu nền, 20 yêu cầu từ hai process chỉ một hold/outbox, toàn bộ ReserveNow enums, timeout/disconnect/restart, miễn trừ hủy trước hạn, ví kiểm tra lại, consume/replay, suspended, expiry nguồn mới và WebSocket TCP thật GetConfiguration → ReserveNow → CancelReservation → ReserveNow → StartTransaction → StopTransaction(EVDisconnected) → ClosureRunner.worker tự chốt hóa đơn và trừ ví đúng một lần.

`frontend/src/features/reservations/reservations.test.tsx`: capability pending, retry UUID/body sau timeout và remount, ngày lưu lỗi, Cancel pending không báo đã hủy. CI/CD, SMTP và hardware/staging không được coi là đã xác minh bởi các kiểm thử local này.

## Cập nhật S-49: đầu nối thay thế khi đặt trùng

`POST /api/v1/driver/reservations` trả 409 với `detail` dạng
`{reason: "connector_reserved", alternatives: [{connector_id, charge_point_code,
connector_number}], generated_at}` khi đầu nối đã bị giữ chỗ. Các lỗi khác giữ
nguyên hợp đồng. Danh sách tối đa 3, sắp theo mã trụ/số đầu nối/id, chỉ cùng trạm,
cùng loại đầu nối và AC/DC, trạm hoạt động, trụ trực tuyến có heartbeat hợp lệ,
đầu nối Available, chưa lưu trữ, không phiên sạc/chờ rút súng/start intent/hold,
và đã xác minh Reservation trên boot hiện tại. Không có ứng viên thì trả `[]`.

Đây là gợi ý tại thời điểm đọc, không phải giữ chỗ. Tài xế bấm gợi ý để đổi
lựa chọn; popup đóng, focus về bộ chọn đầu nối. Lần đặt tiếp theo kiểm tra lại
trạng thái, tải phí và yêu cầu đồng ý/xác nhận lại với UUID mới. Không tự đặt
chỗ hoặc chuyển yêu cầu chưa rõ kết quả sang đầu nối khác. UI vẫn đọc được
lỗi `connector_reserved` dạng chuỗi từ backend cũ và bỏ qua gợi ý sai cấu trúc.

### Coverage Matrix cho phần bổ sung

| Điều kiện | Bằng chứng |
|---|---|
| Một người thắng khi đặt đồng thời; người thua 409 | `test_g5_reservations.py` (20 yêu cầu, hai process); khóa/unique index không đổi |
| 409 có tối đa 3 gợi ý cùng trạm, thứ tự ổn định, không thêm hold/outbox | `test_s49_alternatives.py` |
| Loại sai chuẩn/AC-DC, lỗi, offline, heartbeat cũ, archive, capability cũ/không hỗ trợ, hold | `test_s49_alternatives.py`; các phiên/start intent dùng chung predicate với discovery đã có kiểm thử G4 |
| Không có gợi ý; payload cũ/sai cấu trúc | API test S-49 và `reservations.test.tsx` |
| Chọn gợi ý không tự gửi; UUID/đồng ý phí mới | `reservations.test.tsx`, `DriverCharging.test.tsx` |
| Giao diện 1366px/360px, tên trụ dài, không tràn ngang, chọn và xác nhận lại | Kiểm tra trình duyệt local với dữ liệu mô phỏng; không thay thế nghiệm thu staging |

Không có migration. Triển khai backend trước hoặc cùng frontend; frontend cũ
đọc được `detail.reason`, frontend mới chấp nhận lỗi dạng chuỗi cũ. Sau khi
merge/deploy cần nghiệm thu hai tài xế tranh một đầu nối và bấm gợi ý trên staging
trước khi chuyển S-49 sang Done.
