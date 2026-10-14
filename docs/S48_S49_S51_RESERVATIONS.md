# S-48 / S-49 / S-51 — G5 đặt và hủy chỗ

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
