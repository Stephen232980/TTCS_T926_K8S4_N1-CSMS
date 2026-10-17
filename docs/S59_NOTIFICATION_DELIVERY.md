# S-59 — thông báo phiên sạc theo AC gốc

Nguồn: Backlog CSMS.xlsx, sheet Backlog CSMS, K67:N67. Khi phiên kết thúc,
bị dừng từ xa hoặc thực sự bắt đầu tính phí chiếm trụ, tài xế nhận thông báo
trong ứng dụng và email kèm kWh đã quan sát và tiền tạm tính.
Browser Notification là bổ sung tùy quyền trình duyệt, không phải điều kiện AC.

## Luồng và dữ liệu

- StopTransaction hợp lệ ghi notification `stop` trong cùng transaction cập nhật phiên.
  RemoteStop Accepted chưa phát thông báo đã dừng; dữ liệu meter/tariff chưa đủ thì
  hiển thị đang đối chiếu, không thay số thiếu bằng 0. Tiền trước hóa đơn ghi rõ chưa chốt.
- Worker kiểm tra occupation interval đã confirmed; dùng chính `_daily_tariffs` và
  `_idle_lines` của billing với ân hạn, biểu giá theo ngày địa phương, làm tròn phút.
  Chỉ khi đã có một đoạn phí dương mới phát `idle`, với thời điểm bắt đầu đoạn đó.
  Rút súng trước/đúng ân hạn hoặc pause rồi sạc lại không có thông báo idle.
  Nếu worker khởi động muộn, interval đã đóng vẫn được kiểm tra theo thời gian thực tế.
- `lap_hoa_don` ghi `invoice` khi có snapshot hóa đơn trong cùng transaction.
  Lỗi settlement rollback cả invoice và notification mới. Không suy hóa đơn sẵn sàng
  từ phiên biến mất khỏi `/charging/current`; tổng tiền lấy từ invoice đã lưu.
- `driver_notifications` vừa là inbox vừa là email intent. Unique
  `(driver_id,event_type,event_id)` chống trùng ở DB. Stop/invoice dùng session ID;
  idle dùng occupation interval ID. Không dùng Set React thay DB constraint.
- Worker SMTP claim intent với lease/token, commit rồi mới gọi transport SMTP dùng chung.
  Retry giữ nguyên Message-ID; khi restart nhận lại lease hết hạn. Không tuyên bố SMTP
  giao tới hộp thư hoặc exactly-once; crash sau SMTP acceptance có thể phải gửi lại.
- Scanner và SMTP chạy trong hai loop độc lập: SMTP chậm không giữ transaction hay chặn
  phát hiện idle. Loop scan/email nghỉ 1 giây, UI đọc inbox mỗi 2 giây khi đang đăng nhập.
  Đây là nhịp xử lý danh định, không phải chứng nhận tải lớn/SMTP bên ngoài.

## Giao diện, API và quyền

Toast/CSS/Browser Notification của thành viên được giữ và kết nối với dữ liệu backend.
`DriverNotificationCenter` tồn tại ở workspace, kể cả khi đang mở Ví. Inbox được khôi phục
khi reload/login; chỉ sự kiện mới/chưa đọc tạo toast. Toast tự đóng theo deadline 8 giây,
không bị reset bởi callback mới hoặc polling. Đóng toast không đánh dấu inbox đã đọc.
Browser Notification chỉ gửi khi đã được người dùng cấp quyền; không triển khai Web Push.

- `GET /api/v1/driver/notifications?limit=50&before=<id>`: inbox của driver hiện tại,
  mới nhất trước, tối đa 100 mỗi trang; trả items và next_cursor.
- `POST /api/v1/driver/notifications/{id}/read`: đánh dấu đã đọc, idempotent.
  ID của tài khoản khác trả 404; role khác driver bị 403. Không nhận driver_id từ client.
- Worker bật mặc định qua `DRIVER_NOTIFICATIONS_ENABLED=true`.
- `DRIVER_NOTIFICATION_RETENTION_DAYS=90`, cho phép 1–90. API ẩn item hết hạn;
  scanner xóa bản ghi hết hạn. Replay sự kiện cũ hơn thời hạn không tái tạo inbox.
- S-57 freeze user xóa inbox/email intent cùng transaction trước khi unlink định danh,
  tránh giữ liên kết tài xế–trạm–thời điểm trong nội dung notification. Không xóa dữ liệu
  tài chính hoặc thay logic billing. SMTP đang được máy chủ ngoài chấp nhận không thể thu hồi.
- SMTP dùng cấu hình SMTP_* hiện có theo `docs/SHARED_SMTP.md`; disabled giữ pending.
  Không gửi email thật trong tests. Không ghi địa chỉ/nội dung nhạy cảm vào log lỗi.

## Ma trận AC / kiểm thử

| Điều kiện | Bằng chứng |
| --- | --- |
| Dừng phiên có in-app/email intent, kWh/tiền tạm tính | StopTransaction thực tế, committed PostgreSQL, stop intent pending + nội dung |
| Ba mốc stop / idle / invoice khác nhau | Test committed DB và invoice service, replay 5 lần không thêm item |
| Rút súng trước/đúng ân hạn không báo idle | Test interval 0/3/5 phút, ân hạn 5 phút |
| Email retry/restart | SMTP mock lỗi rồi phục hồi, lease hết hạn, Message-ID ổn định; loop production gửi intent đã commit |
| Không báo invoice sớm | Invoice pending không tạo thông báo; ready lấy tổng tiền snapshot |
| Bền vững / đúng quyền | Đọc inbox bằng session DB mới, own/other driver/operator, read receipt persisted |
| Không mất thông báo ở khu vực khác | Center đặt ngoài nhánh session/wallet, frontend remount recovery + workspace tests |
| Timer và chống lặp hiển thị | Poll/re-render theo từng giây, deadline 8 giây; dismiss không POST read |
| Thiếu số liệu / retention / S-57 | Unknown không thành 0; expiry và freeze purge tests |

Chạy trên database PostgreSQL dùng riêng, đã `alembic upgrade head`:

```text
pytest tests/test_s59_notifications.py tests/test_t80_invoicing.py tests/test_t81_closure.py tests/test_t102_closure_settlement.py tests/test_s28_occupation_lifecycle.py tests/test_privacy_execution.py tests/test_endpoint_policy_inventory.py tests/test_charge_points_migration.py
ruff check .
ruff format --check .
mypy src
npm test --prefix frontend -- --maxWorkers=2
npm run lint --prefix frontend
npm run build --prefix frontend
```

Migration `m170029a2026` sau `l170028a2026`; downgrade gỡ riêng inbox/intent/trigger của S-59.
Kiểm thử local/CI không thay thế nghiệm thu gửi email thật, staging hoặc cập nhật Jira.
Lịch sử commit gốc `9e6a307` của thành viên được giữ nguyên qua merge commit.
