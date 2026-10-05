# Nhóm 5 — điều khiển OCPP

> Phân quyền hiện hành cập nhật 05/10/2026: [nền phân quyền endpoint](ENDPOINT_AUTHORIZATION_DELIVERY.md) thay thế quy tắc admin/operator tự nhận global scope và quyền điều khiển trong các mô tả lịch sử bên dưới. Chủ trạm dùng owned; vận hành/kế toán đọc qua namespace riêng; admin đơn thuần không gửi Reset/Stop/đóng tay.

Phạm vi: S-16 Reset, S-23 RemoteStopTransaction, S-27 nhật ký điều khiển.
Nhánh triển khai: `feature/ocpp-remote-control`. Migration: `f52c813d7a09`.
Đây là bằng chứng kiểm thử cục bộ; không thay trạng thái Jira, CI remote hoặc nghiệm thu thiết bị thật.

## Đối chiếu AC

| Story | Hành vi | Kiểm chứng |
| --- | --- | --- |
| S-16 | Operator/admin chọn Soft/Hard và xác nhận; trụ trả Accepted thì hiện kết quả | API + giao diện; test phản hồi trong 5 giây |
| S-16 | Offline/bản tin Boot chưa được chấp nhận/trụ lưu trữ: không gửi; phản hồi ngay | Test không có frame gửi và dưới 1 giây |
| S-16 | Chờ tối đa 30 giây, bao gồm thời gian gửi; hủy future, không nhận kết quả muộn | Test timeout, send bị treo, phản hồi muộn, mất socket |
| S-23 | Accepted chỉ là nhận lệnh; không tự đóng phiên | Test trạng thái phiên vẫn mở; giao diện giải thích |
| S-23 | StopTransaction thật với reason Remote mới chốt phiên và điện năng theo luồng bình thường | Test qua transport: 1000→3500 Wh chốt 2,5 kWh |
| S-23 | Rejected/offline giữ nguyên phiên | Test API/service và thông báo giao diện |
| S-23 | Sau 120 giây từ Accepted chưa có StopTransaction thì yêu cầu kiểm tra | Tác vụ mỗi giây; test biên 119/120 giây và không ghi sự kiện trùng |
| S-27 | Lưu người, hành động, trụ, phiên, thời gian, kết quả; một hàng hiển thị mỗi yêu cầu | Bảng yêu cầu và kết quả bất biến, liên kết UUID; email/mã trụ lưu tại thời điểm yêu cầu |
| S-27 | Admin lọc theo mã trụ/email người thực hiện và khoảng thời gian | API phân trang và form nhật ký; test lọc |
| S-27 | Sửa/xóa qua API trả 405; dữ liệu chỉ thêm/đọc | Không có route sửa/xóa; trigger PostgreSQL chặn UPDATE/DELETE/TRUNCATE trên cả hai bảng |

Reset không tự đóng phiên. Các StopTransaction hợp lệ khác (Local, EVDisconnected, …) vẫn đi qua luồng kết thúc bình thường. Hiện nhóm phiên sạc mới chốt điện năng, chưa có tính tiền; điều khiển không bổ sung hoặc giả lập thanh toán.

## API và quyền

- `POST /api/v1/ocpp/charge-points/{uuid}/reset`: operator/admin; `{ "request_id": "UUID", "type": "Soft" }` (hoặc Hard).
- `POST /api/v1/ocpp/sessions/{id}/stop`: operator/admin; `{ "request_id": "UUID" }`.
- `GET /api/v1/ocpp/commands/{uuid}`: operator xem yêu cầu của mình; admin xem mọi yêu cầu.
- `GET /api/v1/ocpp/control-audit`: admin; `charge_point_code`, `actor_email`, `from_at`, `to_at`, `page`, `page_size` (tối đa 100).

Thời gian lọc phải có múi giờ. Từ thời điểm phải trước đến thời điểm. Tên tài khoản/mã trụ trong nhật ký là ảnh chụp tại lúc gửi, không đổi theo chỉnh sửa sau này.
Kết quả: Pending, Accepted, Rejected, Offline, Timeout, Disconnected, ProtocolError.
Trụ không được tìm thấy hoặc trạm lưu trữ trả 404; phiên đã kết thúc trả 409.
Quyền lấy từ phiên đăng nhập, không lấy từ body. Chủ trạm/tài xế/kế toán không thấy nút điều khiển; nhật ký chỉ hiện cho admin.

## Tính bền vững

Lưu ý định yêu cầu trước khi gửi frame, không giữ khóa DB trong lúc chờ socket.
Mã request_id được dùng làm OCPP messageId; gửi lại cùng người/mục tiêu/payload trả kết quả đã có, không gửi lần hai. Dùng lại mã cho nội dung khác trả 409.
Phản hồi khớp socket/messageId, không tự nhận phản hồi muộn hoặc socket bị thay.
Yêu cầu thiếu kết quả sau khi tiến trình khởi động lại được ghi Timeout; không tự gửi lại lệnh có thể đã thực thi trên trụ.
Accepted nhưng thiếu tin kết thúc được đánh dấu `remote_stop_not_confirmed`, vẫn giữ phiên mở và ghi sự kiện để kiểm tra.
Chỉ có thao tác INSERT/SELECT trên nhật ký trong ứng dụng; migration cài trigger chặn UPDATE/DELETE/TRUNCATE kể cả khi tài khoản DB sở hữu bảng. Quản trị cơ sở dữ liệu vẫn có thể thay DDL; đây không phải lưu trữ chống can thiệp của DBA.
Registry socket vẫn nằm trong một tiến trình: chạy một worker; nhiều worker cần registry/định tuyến lệnh dùng chung trước khi triển khai.

## Test thủ công

1. Nâng DB: `python -m alembic upgrade head`; chạy backend/frontend như hướng dẫn hiện có.
2. Khai báo trụ và đầu nối số 1. Tạo thẻ demo hoạt động cho tài xế ở màn hình Phiên sạc → Thẻ.
3. Chạy `python scripts/ocpp_control_simulator.py --url ws://127.0.0.1:8001 --code MA-TRU --id-tag MA-THE`. Điều chỉnh URL theo cổng backend thực tế.
4. Operator/admin → Kết nối trụ → Khởi động lại → Soft → Xác nhận. Thấy trụ chấp nhận. Simulator chỉ trả phản hồi Reset, không mô phỏng khởi động phần cứng.
5. Phiên sạc → phiên đang mở → Dừng từ xa → Xác nhận. Nhận Accepted rồi StopTransaction thật của simulator; phiên kết thúc, reason Remote, điện năng 2,5 kWh.
6. Chạy lại với `--outcome Rejected`: lệnh bị từ chối và phiên giữ nguyên. Với `--outcome Timeout`: chờ 30 giây, thấy hết hạn.
7. Với `--omit-stop`: Accepted nhưng phiên vẫn mở; sau hơn 2 phút thấy yêu cầu kiểm tra. Không tự đóng phiên.
8. Tắt simulator rồi gửi lệnh: thấy Offline ngay. Thử lại cùng mã qua API không gửi lệnh trùng.
9. Admin mở Nhật ký điều khiển trong Kết nối trụ, lọc mã trụ/email/từ–đến; đối chiếu kết quả. Operator không thấy mục nhật ký.
10. Chủ trạm/kế toán: không thấy nút điều khiển; gọi API điều khiển trả 403. PATCH/DELETE/PUT command trả 405.

Khi nối lại vào một phiên demo đang mở, dùng `--transaction-id ID` thay cho `--id-tag` để không tạo phiên mới. Hai tùy chọn không dùng chung.

## Kết quả kiểm chứng bản cuối

- Ruff lint và format: đạt (115 file Python); mypy: đạt (47 file nguồn).
- Backend: 291 test đạt trên Windows và Linux/Python 3.12, gồm các gate như CI.
- Frontend: ESLint, TypeScript/build đạt; 146 test đạt trong 27 file test.
- Migration: hạ/nâng trên DB kiểm thử riêng và `alembic check` đạt, không có schema drift.
- UI/API/WebSocket thật với trụ ảo: Reset Accepted; remote stop Accepted giữ phiên mở; thiếu StopTransaction hơn 2 phút được yêu cầu kiểm tra; nhận tin kết thúc thật chốt 2,5 kWh và xóa cảnh báo hiện tại.
- Desktop/mobile: rà soát xác nhận và nhật ký; đã sửa nút phân trang, mobile 390px không tràn ngang. Reviewer chấm lỗi phân trang đã được xử lý; không phải nghiệm thu toàn bộ thiết kế sản phẩm.

Chưa commit/push hoặc chạy CI remote. Reset ở simulator chỉ phản hồi, chưa nghiệm thu khởi động lại thiết bị vật lý.

Không dùng trụ thật cho luồng demo. Kiểm thử thiết bị vật lý và hiệu năng trong hạ tầng triển khai được nghiệm thu riêng.
