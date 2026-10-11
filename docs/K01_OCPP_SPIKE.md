# K-01 — Spike OCPP 1.6J qua WebSocket

Ngày chạy: 2026-10-01
Phạm vi: `BootNotification`, `Heartbeat`, `StatusNotification`, `Authorize`,
`StartTransaction`, `MeterValues`, `StopTransaction`, `Reset`.

## Kết luận

Spike đã nối một trụ ảo vào máy chủ WebSocket tối giản tại
`ws://127.0.0.1:9000/K01-CP-001` bằng subprotocol bắt buộc `ocpp1.6` và chạy
đủ tám action trong phạm vi. Transcript nguyên bản có 20 frame tại
[`evidence/K01_OCPP_TRANSCRIPT.jsonl`](evidence/K01_OCPP_TRANSCRIPT.jsonl).
Phiên thể hiện rõ vòng đời đầu nối `Available` → `Charging` → `Available`;
`StopTransaction.reason=EVDisconnected` là mốc rút súng trong kịch bản.

K-01 chỉ cung cấp bằng chứng và quyết định kỹ thuật. Mã thử nằm ngoài mã sản
phẩm và không được sao chép nguyên trạng vào S-06.

## Simulator đã chọn

- Thư viện: `mobilityhouse/ocpp` phiên bản `2.1.0`.
- WebSocket runtime: `websockets` phiên bản `15.0.1`.
- Lý do: hỗ trợ OCPP 1.6J, kiểm tra payload bằng JSON Schema, có mô hình
  charge point và central system bằng Python, phù hợp stack hiện tại và đủ
  nhẹ để tạo nhiều client trong S-26.
- Giới hạn: đây là protocol library có client mẫu, không phải giao diện mô
  phỏng thiết bị hoàn chỉnh. Kịch bản CI phải tự định nghĩa trạng thái và dữ
  liệu gửi đi.

## Nguồn đặc tả đã đối chiếu

- Open Charge Alliance, **OCPP 1.6 Edition 2**, bản JSON qua WebSocket; trang
  giao thức chính thức: <https://openchargealliance.org/protocols/open-charge-point-protocol/>.
- Gói đặc tả chính thức đã tải và đối chiếu ngày 2026-10-01:
  <https://openchargealliance.org/wp-content/uploads/2025/04/OCPP_1.6_documentation.zip>,
  SHA-256 `2A1D80284CA60449E85951FC55BC0538B5D45BD6F97C6D9228745ACACB52C11B`.
  Gói chứa `ocpp-1.6 edition 2.pdf`, `ocpp-j-1.6-specification.pdf`, errata
  OCPP-J và các JSON Schema. Tài liệu gốc không được chép vào repository.
- Mã nguồn simulator/library: <https://github.com/mobilityhouse/ocpp>, ghim
  bản phát hành `2.1.0`. Runtime WebSocket ghim `websockets==15.0.1`.

Các trường bắt buộc trong bảng dưới được đối chiếu với schema OCPP 1.6 JSON;
transcript được thư viện kiểm tra schema ở cả chiều gửi và nhận.

## Chuỗi phiên đã quan sát

1. Trụ mở WebSocket với đường dẫn `K01-CP-001` và subprotocol `ocpp1.6`.
2. `BootNotification` được chấp nhận, server trả thời gian UTC và heartbeat
   interval 30 giây.
3. `Heartbeat` trả thời gian UTC của server.
4. `StatusNotification` báo connector 1 ở trạng thái `Available` trước phiên.
5. `Authorize` với thẻ thử trả `Accepted`.
6. `StartTransaction` tại `meterStart=12000` Wh trả `transactionId=7001`.
7. `StatusNotification` chuyển connector 1 sang `Charging`.
8. `MeterValues` báo `12500` Wh cho transaction 7001.
9. `StopTransaction` tại `meterStop=13000` Wh, lý do `EVDisconnected`, được
   chấp nhận; đây là mốc rút súng.
10. `StatusNotification` đưa connector 1 trở lại `Available` sau phiên.
11. Server gửi `Reset` kiểu `Soft`; trụ trả `Accepted`.

Mọi CALL đều có message ID riêng và CALLRESULT dùng lại đúng ID của CALL.
`K01-DEMO-TAG` là giá trị thử cố định, không phải dữ liệu người dùng thật.

## Field matrix cần lưu

`Bắt buộc OCPP` là trường bắt buộc theo schema. `Cần lưu` là quyết định phục
vụ các Story S-06 đến S-21; không có nghĩa phải sao chép toàn bộ payload vào
một bảng duy nhất.

| Action | Hướng | Bắt buộc OCPP | Cần lưu hoặc sử dụng |
|---|---|---|---|
| `BootNotification` | CP → CSMS | `chargePointVendor`, `chargePointModel` | message ID; charge point ID từ URL; vendor, model; serial; firmware; meter type/serial; server receive time; response status và heartbeat interval |
| `Heartbeat` | CP → CSMS | không có payload bắt buộc | message ID; charge point ID; server receive time làm `last_seen_at`; response `currentTime` không cần lưu lâu dài |
| `StatusNotification` | CP → CSMS | `connectorId`, `errorCode`, `status` | message ID; charge point/connector; status; error code; vendor error code; info; device timestamp; server receive time |
| `Authorize` | CP → CSMS | `idTag` | message ID; kết quả và thời điểm; liên kết id tag; log chỉ giữ bốn ký tự cuối hoặc hash, không ghi nguyên thẻ |
| `StartTransaction` | CP → CSMS | `connectorId`, `idTag`, `meterStart`, `timestamp` | message ID; charge point/connector; id tag reference; meter start; device/server time; reservation ID; transaction ID và authorization result |
| `MeterValues` | CP → CSMS | `connectorId`, `meterValue` | message ID; transaction ID; connector; từng timestamp; sampled value, measurand, unit, context, format, location và phase khi được hỗ trợ |
| `StopTransaction` | CP → CSMS | `transactionId`, `timestamp`, `meterStop` | message ID; transaction ID; meter stop; device/server time; reason; id tag reference; `transactionData`; trạng thái đối soát |
| `Reset` | CSMS → CP | `type` | outbound message ID; actor gửi lệnh; charge point; loại reset; thời điểm gửi; deadline; response status và thời điểm nhận |

## Quyết định để mở S-06 và S-07

1. Endpoint production là `/ocpp/{charge_point_code}` và chỉ chấp nhận
   subprotocol `ocpp1.6`.
2. Danh tính trụ lấy từ path đã đối chiếu database, không lấy từ payload.
3. S-06 kiểm tra trụ đã đăng ký trước khi tạo OCPP session; trụ lạ phải bị
   đóng và log mã trụ cùng IP.
4. Transport, frame codec/router và handler nghiệp vụ là ba lớp tách biệt.
5. S-07 hỗ trợ ba frame `[2, id, action, payload]`, `[3, id, payload]` và
   `[4, id, code, description, details]`; message ID là chuỗi duy nhất.
6. `last_seen_at` dùng giờ server cho mọi inbound message. Timestamp thiết bị
   được lưu riêng khi nghiệp vụ cần đối chiếu.
7. Inbound message ID và serialized response phải được lưu để S-14 trả lại
   đúng kết quả sau retry hoặc restart.
8. Registry kết nối ban đầu có thể ở memory vì backlog giới hạn một process;
   phải cô lập sau interface để không khóa thiết kế triển khai nhiều process.
9. `idTag` là dữ liệu định danh: không ghi nguyên văn trong application log.
10. Test production phải có handshake đúng/sai subprotocol, trụ đã đăng ký,
    trụ lạ, trạm tạm ngừng và malformed frame trước khi ghép handler.

## Khả năng tái hiện

Mã thử chỉ dùng để tạo bằng chứng và đã được loại khỏi worktree theo ràng buộc
K-01. Khi cần chạy lại, dựng client/server từ ví dụ OCPP 1.6 của
`mobilityhouse/ocpp`, ghim `ocpp==2.1.0` và `websockets==15.0.1`, rồi chạy đúng
chuỗi ở trên. Kết quả đạt khi process kết thúc mã 0, transcript có 20 frame,
có đủ tám action, ba `StatusNotification` lần lượt là `Available`, `Charging`,
`Available`, và mọi CALLRESULT khớp message ID của CALL.
