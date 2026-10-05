# Nhóm 4 — Phục hồi phiên sạc

> Phân quyền hiện hành cập nhật 05/10/2026: [nền phân quyền endpoint](ENDPOINT_AUTHORIZATION_DELIVERY.md) thay thế quy tắc admin/operator tự nhận global scope và quyền điều khiển trong các mô tả lịch sử bên dưới. Chủ trạm dùng owned; vận hành/kế toán đọc qua namespace riêng; admin đơn thuần không gửi Reset/Stop/đóng tay.

Phạm vi S-21, S-25 trong Backlog CSMS.xlsx, nhánh `feature/S-21-phuc-hoi-phien-sac`. Phát triển trên main đã có nhóm 3. Code, giao diện và kiểm chứng dưới đây là cục bộ; Jira và CI của PR được xác nhận riêng.

## Coverage Matrix

| Story / AC | Triển khai | Kiểm chứng |
| --- | --- | --- |
| S-21: nối lại, đầu nối vẫn Charging | Boot ghi dấu phục hồi trên phiên đang mở; StatusNotification giữ nguyên transactionId, không tạo Start mới | Test giữ identity; 20 trụ WebSocket thật ngắt/nối lặp lại |
| S-21: StopTransaction muộn đúng transactionId | Khóa trụ rồi phiên, ghi công tơ/thời gian thực của tin, kWh từ hiệu công tơ | Test Stop muộn; 20 phiên mỗi phiên chốt 2,5 kWh |
| S-21: MeterValues dồn | Với transactionId cụ thể và dấu phục hồi bền vững: lưu cả khoảng trống trước số đo mới nhất, giữ timestamp của trụ; kiểm tra trùng/xung đột/giảm | Test số đo xáo trộn, gửi lặp, lấp khoảng trống và số đo sau Stop nằm trong thời gian phiên |
| S-21: 20 trụ ngắt/nối ngẫu nhiên nhiều lần | Test khởi động ASGI server riêng, 20 client TCP WebSocket; seed cố định để tái hiện, nhiều lần nối lại/Boot/Charging/Meter/Stop và replay Start/Stop | `test_twenty_chargers_random_reconnect_replay_and_buffered_stop`; không mất/nhân đôi phiên, kWh đúng |
| S-21: Available nhưng còn phiên mở | Gắn `available_with_open_session`, giữ phiên mở, không chốt kWh đoán; Charging mới xóa cảnh báo này | Test status và lịch sử phục hồi |
| S-21 NFR: khớp theo transactionId | Kiểm tra cả trụ, đầu nối và transactionId; không gán tin không khớp theo thời gian | Test ID không tồn tại; regression nhóm 3 kiểm tra ID trụ khác |
| S-25: offline quá ngưỡng | Job chạy khi khởi động rồi mỗi 60 giây; ngưỡng mặc định 6 giờ kể từ hết hai chu kỳ heartbeat, dùng đồng hồ server; không dùng timestamp Start từ trụ để suy ra mất liên lạc | Test ranh giới, cấu hình, scan lặp, heartbeat mới và Start cũ mới nhận |
| S-25: Stop muộn đóng phiên, rời danh sách bất thường | Xóa trạng thái bất thường/cảnh báo mất liên lạc, giữ các cảnh báo chất lượng số đo độc lập và lịch sử | Test Stop muộn và bộ lọc bất thường |
| S-25: đóng tay, lý do bắt buộc, số đo cuối | API operator/admin, lý do trim 1–500 ký tự, lấy mẫu Energy.Active.Import.Register tổng Outlet cuối đã lưu; không cho nhập kWh; thiếu/âm/giảm hoặc thời gian tương lai trả 409 | Test API, mẫu pha không thay công tơ tổng, reason/permission/replay, test form xác nhận |
| Tranh chấp Stop/đóng tay | Cùng thứ tự khóa trụ → phiên; một lần đóng có hiệu lực. Stop đến sau đóng tay giữ pending, không ghi đè kWh/lý do | Test hai tác vụ đồng thời và Stop sau đóng tay |
| Giao diện thật và quyền kế toán | Bộ lọc bất thường, form đóng tay, lịch sử; kế toán đọc phiên/số đo/lịch sử, không thấy thẻ/pending/đóng tay. Owner vẫn theo sở hữu, không đóng tay | Vitest, API scope, QA desktop/mobile bằng DB demo riêng |

## Migration và cấu hình

Nâng migration `e41b9027c6a8` sau `d830a62f194b` trước khi chạy:

```powershell
python -m alembic upgrade head
```

Thêm `recovery_at`, `abnormal_since`, `manual_closed_at`, `manual_close_reason`, `closed_by` và bảng `charging_session_events`. Lịch sử lưu người thực hiện, thời điểm, lý do, công tơ/kWh khi đóng tay. Cảnh báo phục hồi được giải quyết không làm mất lịch sử.

`CHARGING_ABNORMAL_OFFLINE_SECONDS=21600` (6 giờ), `CHARGING_RECOVERY_SCAN_INTERVAL_SECONDS=60`. Các giá trị phải lớn hơn 0. Khi nhận liên lạc mới, phiên chưa bị gắn bất thường sẽ không bị suy ra mất mạng chỉ từ thời gian bắt đầu. Phiên đã bất thường còn nằm trong danh sách đến khi có Stop hoặc đóng tay; Charging trở lại không tự đóng/xóa phiên.

## API

| API | Quyền / hành vi |
| --- | --- |
| GET /api/v1/charging/sessions?state=abnormal | Owner theo trạm, operator/admin/accountant; chỉ phiên còn mở và abnormal_since khác null |
| GET /api/v1/charging/sessions/{id}/samples | Bổ sung quyền đọc accountant; vẫn giới hạn owner |
| GET /api/v1/charging/sessions/{id}/events | Cùng quyền đọc phiên, tối đa 100 sự kiện mới nhất, actor là email hoặc null cho hệ thống |
| POST /api/v1/charging/sessions/{id}/close | Operator/admin; body `{ "reason": "Đã kiểm tra tại trụ" }`; 409 nếu phiên không bất thường/còn mở hoặc số đo không hợp lệ; trả id, energy_kwh, ended_at |

Response phiên bổ sung metadata phục hồi và đóng tay. Không cấp accountant quyền API quản lý trạm/thẻ/pending. Với tài khoản có nhiều vai trò, owner vẫn giới hạn sở hữu trừ khi có operator/admin.

## Kiểm thử thủ công

1. Nâng migration, khởi động lại backend và frontend. Với operator/admin mở **Phiên sạc** → chọn **Bất thường — chưa kết thúc**.
2. Trong môi trường demo riêng, để trụ mất mạng vượt ngưỡng (có thể giảm ngưỡng cho demo rồi khởi động lại backend). Phiên vẫn mở, chưa chốt kWh; xuất hiện cảnh báo và lịch sử đánh dấu bất thường.
3. Cho trụ nối lại, Boot được Accepted rồi báo Charging: mã phiên giữ nguyên. Gửi MeterValues dồn với đúng transactionId; biểu đồ/bảng giữ timestamp đã gửi, không tạo phiên khác.
4. Gửi StopTransaction đúng transactionId, meterStop hợp lệ: phiên kết thúc, kWh = (meterStop - meterStart)/1000, rời bộ lọc bất thường. Gửi lặp cùng messageId không làm nhân đôi.
5. Với một phiên demo bất thường khác có số đo tổng cuối hợp lệ, bấm **Đóng tay phiên…**. Lý do trống hoặc chưa tích xác nhận thì chưa lưu được. Hủy giữ nguyên phiên. Nhập lý do và xác nhận; sau lưu thấy kWh/lý do và lịch sử người đóng, phiên rời danh sách bất thường.
6. Đóng tay chỉ đóng hồ sơ CSMS, không gửi lệnh dừng tới trụ. Gửi Stop sau đóng tay: hồ sơ đã đóng giữ nguyên, tin xuất hiện trong Chờ đối chiếu. Thiếu số đo tổng hợp lệ thì không cho chốt điện năng đoán.
7. Với accountant: đọc phiên/số đo/lịch sử; không có nút đóng tay hoặc quản lý thẻ. Owner khác không đọc phiên/lịch sử ngoài phạm vi. Driver không vào API quản lý.

Preview riêng: http://127.0.0.1:5179/ (backend 8005), DB `csms_recovery_preview_20261002`. Dữ liệu mẫu là minh họa, không phải phiên của khách. Operator `operator.recovery@example.com`, accountant `accountant.recovery@example.com`, mật khẩu demo `DemoRecovery2026!`; chỉ dùng local. Preview là tiến trình tạm cần còn chạy. Phiên demo đã đóng qua giao diện sẽ không còn trong bộ lọc bất thường; chọn Tất cả/Đã kết thúc để đọc lịch sử.

## Kiểm chứng và giới hạn

- Backend: 262 tests đạt, gồm 20 trụ WebSocket thật và regression nhóm 1–3; DB test riêng `csms_charging_test_20261002`.
- Frontend: 138 tests / 26 files đạt; ESLint và TypeScript/Vite build đạt.
- Ruff lint/format, mypy đạt local và trên Python 3.12/Linux với dependencies cài theo CI; toàn bộ 262 backend tests cũng đạt trong container Linux. Đây chưa phải kết quả GitHub Actions của PR mới.
- Migration nâng/hạ về nền nhóm 2/nâng lại và `alembic check` đạt trên DB kiểm thử riêng.
- Pending không biết transactionId vẫn chỉ quan sát, không tự tạo/gán phiên hoặc chốt kWh theo thời gian. Đối chiếu thủ công tin không khớp chưa được AC S-21/S-25 yêu cầu.
- Đóng tay chốt từ số đo tổng cuối đã nhận, không bảo đảm gồm toàn bộ điện năng phát sinh khi offline; giao diện nêu rõ giới hạn này. Điều khiển dừng từ xa thuộc nhóm 5.
- Kịch bản 20 trụ dùng localhost, không thay kiểm thử chịu tải/độ trễ mạng của môi trường triển khai hoặc toàn bộ simulator S-26.
