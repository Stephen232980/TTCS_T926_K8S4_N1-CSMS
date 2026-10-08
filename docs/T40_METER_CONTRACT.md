# S-19 / T-40 — hợp đồng số đo chuẩn hoá cho T-80

## Phạm vi đã chốt

Giữ cách lưu số đo chuẩn hoá đang có; yêu cầu cũ giữ nguyên văn Wh/kWh
được thay bằng hợp đồng chuẩn hoá một lần khi nhận OCPP. Không tạo bảng
meter_values thứ hai: bảng triển khai tương đương là charging_meter_samples.
Bảng và chỉ mục (session_id, timestamp) đã có trong migration d830a62f194b.
Không thêm migration, cột nguồn hoặc đổi dữ liệu lịch sử.

Hàm numeric_sample và bảng đơn vị được tách khỏi service sang
src/modules/charging/meter_units.py để kiểm thử và dùng chung. Luồng nhận
MeterValues, dữ liệu phục hồi và transactionData của StopTransaction vẫn
đi qua cùng hàm; thuật toán chuyển đổi/độ chính xác hiện hành giữ nguyên.

## Hợp đồng đọc cho T-80

- Energy.Active.Import.Register là chỉ số công tơ tích luỹ, lưu bằng
  Decimal với unit=Wh, tối đa sáu chữ số thập phân Wh.
- 1 kWh ở đầu vào trở thành value=1000, unit=Wh. 1000 Wh hoặc đầu vào
  thiếu unit cho cùng kết quả. Thiếu measurand mặc định là chỉ số điện này.
- API samples trả giá trị và đơn vị đã lưu; Decimal serialize thành chuỗi.
  Không dùng đơn vị đầu vào cũ để nhân 1000 lần nữa, không dùng float.
- T-80 chọn đúng measurand và đúng chuỗi phase/location; không cộng số đo
  tổng với số đo từng pha, không trộn Power/Voltage/Current vào điện năng.
  Chuỗi tổng mặc định hiện hành là phase rỗng, location Outlet. Hỗ trợ
  phương án dùng từng pha khi thiếu chuỗi tổng là quyết định của T-80.
- Điện năng tiêu thụ là hiệu chỉ số công tơ theo thời gian, không cộng các
  chỉ số tuyệt đối. Khi cần kWh, chia phần chênh lệch Wh cho Decimal(1000).
  Hàm MeterValue của T-72 nhận energy_wh trực tiếp từ giá trị đã chuẩn hoá.
- Số đo bất thường/review, thiếu chuỗi phù hợp hoặc đơn vị lưu không đúng
  hợp đồng phải được T-80 xử lý rõ; không âm thầm biến thành 0 hay đoán đơn
  vị. Chốt cách từ chối lập hoá đơn thuộc T-80/T-102, không được triển khai
  thay trong T-40. Số đo âm hiện được giữ cho điều tra theo logic cũ.
- NaN/Infinity, giá trị không đọc được, đơn vị không hỗ trợ và SignedData
  không trở thành số đo 0. Cách bỏ qua/ghi review hiện hành giữ nguyên.
- Dữ liệu cũ hiện chưa được chứng minh khác hợp đồng. Nếu phát hiện dòng
  lịch sử có kWh, phải kiểm nguồn dữ liệu và làm backfill được duyệt riêng;
  không tự chuyển đổi trong hàm đọc rồi có nguy cơ chuyển đổi hai lần.

T-80 chưa có luồng lập hoá đơn từ số đo trên develop tại d7b46f3. PR này
cung cấp hợp đồng và bằng chứng đầu vào, không hoàn thành T-80/T-81/T-102.
T-72 hiện có lớp MeterValue và nội suy; hàm chia_doan còn là stub.

## Kiểm chứng

20 ca mới phủ chuyển đổi Decimal, số lẻ nhỏ, giá trị không dùng được,
đại lượng khác, chống chuyển đổi hai lần, từ bản tin OCPP đến database/API,
chống trùng cùng quan sát giữa Wh và kWh, đầu đọc T-72 và đóng phiên đúng
1 kWh. 53 ca tập trung đạt (một ca latency sẽ chạy gate riêng).
Hồi quy backend đầy đủ: 857 passed, 2 deselected, 4 cảnh báo deprecation
có sẵn, 185,83 giây. Hai ca deselected chạy riêng theo cấu hình CI và đạt:
MeterValues 20 trụ tối đa 93 ms; WebSocket thật qua ba chu kỳ tối đa
153,5 ms, dưới 200 ms. Tổng 859 ca backend đạt.
Ruff toàn repo, format 265 file, mypy 94 file và diff check đạt.
Database PostgreSQL 16 thử rỗng upgrade đến head b150015a2026 đạt; không
migration mới. CI và staging cần được xác nhận riêng.

### CI latency follow-up

CI measured 211.8 ms in the first socket cycle (limit: 200 ms).
Before the fix, Linux/Python 3.12.15, SQLAlchemy 2.1.3 and PostgreSQL 16
measured 80.2-86.8 ms; runner slowdown was not reproduced locally.
The CALL path used separate queries to lock the charger and update contact.
Combine them with SELECT FOR UPDATE in a CTE and UPDATE RETURNING,
saving one round trip per CALL. Evaluate the DB clock after the lock;
read the reply cache in the next statement so concurrent duplicates see
committed replies. Preserve commit-before-reply and the 200 ms gate.

After the fix: Linux functional suite: 858 passed, 1 skipped (Docker
Compose unavailable in the test image), 2 deselected latency gates.
The Compose test passed separately on Windows. Both latency gates passed:
20 chargers: max 77 ms; real sockets: three runs of three cycles each,
max 95.8 / 106.5 / 103.7 ms. Total: 861 distinct backend tests passed.
73 focused Windows tests also passed. Ruff lint/format, mypy and diff
checks passed. New coverage includes concurrent duplicates with contact
recording and rollback of contact/expired connector state.
SQLAlchemy/Starlette deprecation warnings remain; they are not the latency
assertion failure. CI after push and staging remain separate checks.
