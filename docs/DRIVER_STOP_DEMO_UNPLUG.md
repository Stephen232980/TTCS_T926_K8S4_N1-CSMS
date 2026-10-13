# Tài xế dừng sạc và mô phỏng rút súng

Mở rộng được trưởng nhóm chấp thuận, phối hợp điều khiển OCPP, S-28 (chiếm
trụ đến rút súng), S-37 (hóa đơn/trừ ví) và giao diện tài xế. Giữ AC gốc S-28.
Checkbox của người dùng không là bằng chứng billing. Không có migration mới.

## Luồng

1. Dừng sạc → xác nhận → RemoteStopTransaction. Accepted chỉ là trụ nhận lệnh.
2. StopTransaction(Remote) dừng cấp điện; simulator báo Finishing có timestamp.
3. Giao diện giữ phiên Chờ rút súng. Checkbox Tôi đã rút súng chỉ ghi nhận
   hướng dẫn trên trình duyệt, không gửi API/chốt tiền.
4. Nút nhỏ Mô phỏng rút súng gửi DataTransfer riêng. Simulator báo Available
   có timestamp; backend kết thúc chiếm trụ, worker chốt hóa đơn/trừ ví.
5. Rút trực tiếp khi còn sạc: StopTransaction(EVDisconnected) và Available.
   Không gửi StopTransaction lần hai với lý do khác cho phiên đã dừng.

## API

| Method/path dưới /api/v1/driver | Quyền / phạm vi | Body |
|---|---|---|
| POST /charging/sessions/{session_id}/stop | driver.session.stop / own | request_id UUID |
| POST /charging/sessions/{session_id}/demo-unplug | driver.session.demo_unplug / own | request_id UUID |
| GET /charging/commands/{command_id} | driver.session.command_read / own | không có |

POST từ chối trường thừa; 200 trả id/status: Pending, Accepted, Rejected,
Offline, Timeout, Disconnected hoặc ProtocolError. Giữ cùng key khi mất
response; replay không gửi socket lần hai. Không tự đổi key để che timeout.
401 chưa đăng nhập; 403 phiên/yêu cầu của người khác; 404 không tồn tại/demo
tắt/trụ ngoài phạm vi; 409 key khác thao tác, phiên kết thúc/đã giải phóng;
422 body không hợp lệ.

GET /charging/current và SSE thêm awaiting_unplug vào snapshot. Session thêm
connector_released_at, awaiting_unplug và demo_unplug_available. Nút demo dựa
trên flag backend. Chặn bắt đầu mới khi tài xế/đầu nối còn phiên chưa giải phóng.

Request/result dùng hai bảng control append-only hiện có; audit ghi actor,
permission/roles. Demo API không update ended_at/release, tạo invoice hoặc
ghi debit trực tiếp. DataTransfer: vendorId=CSMS-DEMO, messageId=Unplug,
data JSON chứa transactionId/connectorId lấy từ DB, không nhận từ client.
Chỉ DEMO-STG-* và phiên capture release_detection=available được phép.
Simulator giữ Finishing qua nối lại và kiểm tra đúng phiên trên đầu nối.

## Bật staging sau merge/deploy

Runtime backend staging cần:

```dotenv
BILLING_AVAILABLE_CONFIRMS_UNPLUG=true
DEMO_DRIVER_UNPLUG_ENABLED=true
```

Triển khai/khởi động lại backend sau đổi cấu hình. Chỉ phiên mới lấy chế độ
available; không ép chốt phiên cũ. Repo mặc định cả hai false. Chỉ bật Available
cho fleet đã kiểm chứng tín hiệu này đúng lúc giải phóng. Sản phẩm thật tắt
DEMO_DRIVER_UNPLUG_ENABLED.

Image backend mới chứa scripts/staging_demo.py. Trên máy cá nhân:

```powershell
& C:\Users\LENOVO\CSMS\scripts\stop-csms-staging-demo.ps1
& C:\Users\LENOVO\CSMS\scripts\start-csms-staging-demo.ps1
& C:\Users\LENOVO\CSMS\scripts\status-csms-staging-demo.ps1
```

Launcher dùng SSH key đã cấp, giữ file tài khoản demo riêng trong .local và
trên server (không commit). Startup dùng image backend hiện hành, hai trạm
Thảo Điền/Bình Thạnh, 20 trụ/80 đầu nối; không nạp bù hoặc xóa lịch sử.
Dừng bình thường giải phóng các đầu nối demo còn chiếm; giữ hóa đơn/sổ cái.
Nếu image đổi, dừng rồi chạy lại. Không dùng nguồn simulator cài tay cũ.

## Snapshot giao diện và coverage

Kế thừa commit giao diện local đến f905d2a, giữ lịch sử đóng góp; không lấy
operator/owner đang sửa dở. Sửa OwnerWorkspace và App.test bổ sung chỉ để
lint và cô lập hash giữa test; giữ hành vi điều hướng.

| Điều kiện | Bằng chứng |
|---|---|
| Chủ phiên, replay, Accepted chưa phải kết thúc | HTTP/service và control regression |
| Demo tắt/trụ thường | Backend 404; UI ẩn nút |
| Checkbox không chốt | Component test không gọi API |
| Dừng rồi rút / rút trực tiếp | Socket local với simulator thật, timestamp đầy đủ |
| Chờ rút chưa debit; điện/chiếm trụ đúng | PostgreSQL: 4.400đ, một debit qua nhiều lần closure |
| Mobile/desktop | Browser fixture 360px/1280px, không tràn/pageerror |

Browser dùng frontend local/API fixtures. Chưa đổi cấu hình hoặc deploy PR,
chưa nghiệm thu mới trên staging trong lượt này.
