# S-28: theo dõi chiếm trụ đến khi rút súng

Phạm vi: AC gốc của S-28 trong Backlog CSMS.xlsx, bổ sung vào T-63/T-64 và
luồng T-80/T-81. Quy tắc Finishing/SuspendedEV, khoảng tạm dừng, ân hạn liên
tục và chờ bằng chứng rút súng được người yêu cầu đồng ý ngày 11/10/2026.

## Quy tắc

- Finishing xác nhận giao dịch đã dừng nhưng đầu nối vẫn bị chiếm. Hóa đơn
  vẫn cần StopTransaction và số đo cuối để tính điện.
- SuspendedEV mở khoảng theo dõi, không tự chứng minh pin đầy. StopTransaction
  hoặc Finishing xác nhận kết thúc sạc. Nếu Charging trở lại trước StopTransaction,
  hủy tính phí khoảng đó, lưu nguyên lịch sử.
- SuspendedEV → Finishing giữ một khoảng liên tục, không cấp lại ân hạn.
- StopTransaction kết thúc tiền điện, không tự kết thúc phí chiếm trụ.
- Rút súng được xác nhận bằng StopTransaction.reason=EVDisconnected, hoặc
  Available trên đúng đầu nối với cấu hình đã xác minh. Không dùng connectorId=0,
  ngắt WebSocket hoặc đồng hồ máy chủ thay bằng chứng vật lý.
- Sau khi dừng sạc và xác nhận rút súng, tạo đúng một hóa đơn bất biến. Tiền
  điện chỉ đến mốc StopTransaction; phí chiếm trụ đến mốc rút súng. Phí theo
  giá từng ngày địa phương, ân hạn tại đầu khoảng, làm tròn phút lên một lần.
- Thiếu timestamp, mất liên lạc trong lúc chờ giải phóng, trạng thái lỗi hoặc
  dữ liệu mâu thuẫn được đánh dấu cần đối chiếu. Không tự đoán mốc thu tiền.
- Phiên mới trên cùng đầu nối không được dùng để suy ra thời điểm rút súng
  của phiên cũ. Phiên cũ thiếu bằng chứng được chuyển sang cần đối chiếu.

## Cấu hình tín hiệu Available

`BILLING_AVAILABLE_CONFIRMS_UNPLUG=false` là mặc định. Chỉ bật `true` trong
môi trường dùng simulator đi kèm hoặc một nhóm trụ đã kiểm chứng Available
đồng nghĩa với việc rút súng. Cấu hình được lưu trên từng phiên ngay khi
StartTransaction, thay đổi cấu hình không thay quy tắc phiên đang có.

Simulator gửi StatusNotification có timestamp nguồn; kịch bản recovery gửi
StopTransaction trước rồi Available. Kiểm thử OCPP bổ sung cả trường hợp
Available đến trước bản tin StopTransaction và bản tin trùng/cũ.

Trong Docker Compose, đặt biến trên trong tệp môi trường rồi tạo lại dịch vụ
app theo quy trình triển khai. Không bật đồng loạt cho nhóm trụ chưa kiểm chứng.
Chưa có thử nghiệm phần cứng thật trong PR này. OCPP 1.6 không có một bản tin
rút súng riêng áp dụng đồng nhất cho mọi thiết bị.

## Dữ liệu và điểm chuyển đổi

Migration d170017a2026 nối tiếp c160016a2026, bổ sung phiên bản vòng đời,
cách phát hiện rút súng, mốc rút súng và bảng charging_occupation_intervals.
Mọi phiên đã tồn tại khi nâng cấp giữ version=0 và cách tính trước đây;
phiên tạo mới dùng version=1. Điều này cũng áp dụng với phiên đang mở tại
thời điểm chuyển đổi. Không suy ngược lịch sử thiếu dữ liệu để thu thêm tiền.
Hóa đơn/ledger cũ không bị cập nhật hoặc tạo khoản thu bổ sung.

idle_since còn là mốc khoảng hiện tại để tương thích T-63/T-64; bảng khoảng
và sự kiện là bằng chứng cho chính sách mới. Khóa phiên, cache trả lời OCPP,
unique invoice/session và cơ chế chỉ ghi thêm của hóa đơn vẫn được giữ.

T-81 vẫn trả lời OCPP trước khi lập hóa đơn. Hàng đợi sau StopTransaction sẽ
trả pending khi chưa rút súng; tác vụ quét DB ngay lúc khởi động và mỗi 60 giây
phục hồi phiên đã nhận đủ bằng chứng. Không cần rút súng lần nữa để kích hoạt.
Đây là kiểm chứng lập hóa đơn; không triển khai trừ ví T-102 trong PR này.
T-102 phải dùng hóa đơn cuối đã lưu, không dùng số tiền tạm tại StopTransaction.

API/UI thêm awaiting_unplug: "Đã dừng sạc, đang chờ xác nhận rút súng".
Không hiển thị số tiền cuối hoặc các dòng hóa đơn khi chưa sẵn sàng; người dùng
có thể kiểm tra lại. Không thêm bộ tính tiền tạm riêng trong giao diện.

## Kiểm thử và đáp án

- [Đáp án vòng đời bổ sung](s32/S28_LIFECYCLE_ANSWERS.md), giữ nguyên bộ T-77 đã xác nhận.
- tests/test_s28_occupation_lifecycle.py: OCPP → lịch sử → hóa đơn/API.
- tests/test_t81_closure.py: phục hồi DB chờ rút súng, sau đó tạo một hóa đơn.
- tests/test_s28_lifecycle_migration.py: PostgreSQL upgrade → downgrade → upgrade,
  giữ nguyên hóa đơn và quy tắc phiên cũ, mặc định phiên mới là version 1.
- Kiểm thử T-63/T-64/T-78/T-80/T-81/T-82 và hai cổng độ trễ OCPP được chạy lại.

Chưa coi kiểm thử tự động/simulator là bằng chứng nghiệm thu trên trụ thật
hoặc xác nhận Jira Done. Phiên cần đối chiếu giữ nguyên bằng chứng; quy trình
quản trị điều chỉnh dữ liệu cần được thực hiện riêng, không tự bỏ cờ lỗi.
