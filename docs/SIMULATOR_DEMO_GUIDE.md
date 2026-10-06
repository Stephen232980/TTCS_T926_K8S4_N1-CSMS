# Giả lập trụ theo đầu nối đã khai báo

## Tự động kết nối toàn bộ trụ và trụ mới

Bộ demo local khởi chạy qua `.local/start-csms-demo.ps1` giữ các trụ mẫu,
đồng thời quét database mỗi 5 giây để kết nối các trụ khác và trụ vừa tạo.
Trụ phải có đầu nối chưa archive; trụ/trạm archive và trạm blocked được bỏ
qua. Tạo trụ xong không cần chạy thêm simulator riêng. Khi dừng qua
`.local/stop-csms-demo.ps1`, các phiên trên trụ tự phát hiện cũng được gửi
StopTransaction và kết thúc đúng qua OCPP.

Nếu không dùng bộ demo local, chạy một bộ giả lập tự động độc lập:

```powershell
.\.venv\Scripts\python.exe scripts/ocpp_fleet_simulator.py `
  --url ws://127.0.0.1:8001
```

Chọn một trong hai bộ chạy, không chạy đồng thời cho cùng các mã trụ.
Ctrl+C với bộ tự động yêu cầu kết thúc các phiên trước khi đóng kết nối.
Một trụ gặp lỗi được thử kết nối lại ở lần quét tiếp theo, không làm dừng
các trụ khác. Cấu hình DATABASE_URL phải cùng database với backend local.

Trạm inactive vẫn có thể kết nối báo trạng thái, nhưng tài xế chỉ sạc khi
trạm active. Bộ tự động không đổi trạng thái trạm hay tự tạo phiên sạc.
Trụ được phát hiện lúc tạo; nếu thêm đầu nối sau khi đã kết nối, cần khởi
động lại simulator của trụ để đọc lại cấu hình đầu nối.

Đã kiểm chứng tạo một trụ mới trong khi bộ demo đang chạy: tự phát hiện,
Boot và bốn đầu nối online; hai tài xế bắt đầu đồng thời trên đầu nối 2/3,
nhận số đo riêng và dừng một phiên không ảnh hưởng phiên còn lại. Kiểm thử
watcher xác nhận không tạo task trùng, bỏ qua trụ do bộ demo đã quản lý,
phát hiện trụ mới, dừng trụ bị loại khỏi danh mục và dừng toàn bộ.

## Kết nối một trụ riêng

Chạy tại thư mục gốc dự án:

```powershell
.\.venv\Scripts\python.exe scripts/ocpp_control_simulator.py `
  --url ws://127.0.0.1:8001 `
  --code ICTU-CP-001 `
  --start-delay 10
```

Không cần nhập số lượng đầu nối. Script đọc các đầu nối chưa archive của
trụ từ database trong `DATABASE_URL` của `.env`. Database này phải là database
của backend được chỉ định trong `--url`. Trụ chưa đăng ký hoặc không có đầu
nối sẽ bị từ chối trước khi kết nối; không tự tạo hồ sơ.

Mỗi đầu nối sẵn sàng nhận RemoteStartTransaction có phiên, công tơ và trạng
thái riêng. Nhiều tài xế có thể dùng các đầu nối khác nhau cùng lúc; backend
vẫn kiểm tra quyền, trạng thái trạm và phiên/yêu cầu đang mở của mỗi tài xế.
Trạm phải active để tài xế thấy và bắt đầu sạc. Đầu nối Faulted, Reserved,
Unavailable giữ nguyên trạng thái và không nhận yêu cầu bắt đầu.

Khi khởi chạy lại, script đọc các phiên còn mở và số đo tổng cuối đã lưu,
tiếp tục transactionId/công tơ thay vì báo Available và tạo phiên thay thế.
Chỉ chạy một simulator cho mỗi mã trụ. Không dùng lệnh này để thay thế trụ
thuộc đội giả lập đang chạy bằng một process khác.

RemoteStopTransaction kết thúc đúng phiên được chọn, gửi StopTransaction
và trả đúng đầu nối về Available; đầu nối khác tiếp tục sạc. Ctrl+C ngắt
simulator, không kết thúc phiên: muốn kết thúc phiên, dùng Dừng từ xa ở khu
vực Vận hành trước khi ngắt. Reset chỉ phản hồi kết quả, không khởi động lại
phần cứng hay xóa lỗi thiết bị.

`--id-tag` vẫn cho phép bắt đầu bằng thẻ đã đăng ký, mặc định ở đầu nối 1;
dùng `--connector 2` để chọn đầu nối khác. Không truyền `--id-tag` khi muốn
tài xế chủ động bắt đầu qua ứng dụng. Các cờ `--outcome Rejected/Timeout`,
`--omit-start`, `--omit-stop` vẫn dùng cho tình huống lỗi có chủ ý.

## Kiểm chứng ngày 06/10/2026

- Kiểm thử WebSocket thật xác nhận bắt đầu đồng thời đầu nối 2/3, định tuyến
  số đo theo transactionId, dừng riêng, bắt đầu lại; từ chối đầu nối lỗi,
  chưa khai báo và yêu cầu trùng trong khoảng chờ StartTransaction.
- Kiểm chứng với backend/API/database demo thật trên trụ kiểm thử riêng:
  hai tài xế bắt đầu đầu nối 2/3, nhận phiên khác nhau và số đo tăng;
  dừng một phiên không ảnh hưởng phiên còn lại. Các phiên thử đã dừng qua OCPP.
- Đã đọc cấu hình thực ICTU-CP-001 gồm bốn đầu nối. Trạm của trụ này chưa
  xuất hiện trong danh mục active của tài xế ở thời điểm kiểm tra, nên không
  chuyển trạng thái trạm để chạy kiểm chứng trên dữ liệu của người dùng.

Phạm vi liên quan S-24, S-17–S-19. Đây là nâng cấp script demo, không thay
kịch bản Compose/CI S-26 hoặc đánh dấu toàn bộ story đã nghiệm thu.
