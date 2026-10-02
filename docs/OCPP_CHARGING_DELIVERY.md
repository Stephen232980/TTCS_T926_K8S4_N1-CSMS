# Nhóm 3 — Phiên sạc OCPP

Phạm vi: S-15, S-17, S-18, S-19, S-20 theo Backlog CSMS.xlsx. Code nằm trên nhánh feature/S-17-phien-sac-ocpp, phát triển từ main fd69d0f. Bằng chứng dưới đây là cục bộ; không thay thế trạng thái Jira hoặc CI của PR.

## Coverage Matrix

| Story / AC | Triển khai | Kiểm chứng |
| --- | --- | --- |
| S-15: thẻ/tài xế hoạt động; khóa; hết hạn; không tồn tại; trạm ngừng hoạt động | Authorize tra cứu thẻ và vai trò/trạng thái tài xế, trạm; trả Accepted/Blocked/Expired/Invalid | test_authorize_states_and_masked_audit gồm 7 tình huống |
| S-15: audit, che mã thẻ | Lưu fingerprint SHA-256, chỉ trả/ghi log bốn ký tự cuối; API cấp/khóa/mở khóa thẻ | Test audit không lộ tag; test API và giao diện thẻ |
| S-17: phiên mới, transactionId tăng, meterStart/thời gian | Identity integer DB; một phiên mở trên đầu nối; khóa mã trụ sau giao dịch | Test identity/code lock; demo WebSocket thật |
| S-17: thẻ bị từ chối vẫn ghi phiên để xem xét | Trả transactionId và idTagInfo; lưu nguyên trạng xác thực, gắn review | Test thẻ blocked/invalid; demo blocked |
| S-17: phiên cũ chưa đóng | Đóng bất thường, không chốt kWh, đánh dấu cả phiên cũ và mới | Test replacement |
| S-17 / S-14: replay messageId | Dùng cache phản hồi bền vững trong cùng transaction DB | Test replay; demo Start gửi lại cho cùng transactionId |
| S-18: kết thúc, lý do và điện năng | (meterStop - meterStart) / 1000; không cộng samples | Test chốt 2,5 kWh, demo API/UI thật |
| S-18: công tơ cuối thấp/âm, thời gian sai | Đóng phiên, kWh null, gắn review | Test bad counters và negative counters |
| S-18: transactionId không biết; transactionData | CALLRESULT và pending; số đo kết thúc qua cùng bộ xử lý MeterValues | Test unknown/zero/foreign transaction, empty sampledValue |
| S-19: số đo đã biết; đại lượng lạ | Lưu số đo gắn phiên; bỏ qua đại lượng lạ, SignedData hoặc giá trị không hữu hạn | Test known/unknown numeric và đơn vị |
| S-19: không có phiên phù hợp | Pending, không tự tạo phiên | Test unmatched messages |
| S-19 NFR: 20 trụ, chu kỳ 10 giây, trả lời dưới 200 ms | Gộp contact và MeterValues trong một transaction; pool giữ 20 kết nối | Test 20 phản hồi đồng thời, gồm transport/commit/send; đo sau warm-up, không gồm mở socket/DB lần đầu |
| S-20: thời gian cũ/trùng; điện năng giảm | So theo timestamp trụ và từng series; cũ bỏ qua có cảnh báo, trùng cùng giá trị bỏ qua yên lặng, giá trị giảm vẫn lưu và review | Test ordering/dedup/regression, đổi Wh/kWh, xung đột cùng timestamp |
| Quyền và UI | Owner theo trạm/thẻ đã cấp; operator/admin quản lý; driver không vào màn hình quản lý | Test owner scope/403; UI desktop/mobile và Vitest |

## DB và API

Nâng migration bằng `python -m alembic upgrade head`; head mới `d830a62f194b`, sau `a721093e4f62`. Thêm charging_cards, authorization_attempts, charging_sessions, meter_samples, pending_charging_messages. Pending không chứa idTag. Phiên và mẫu có khóa ngoại, chỉ mục và unique cho phiên mở/series timestamp.

| API | Công dụng |
| --- | --- |
| GET /api/v1/charging/sessions | Phân trang (20 mặc định, tối đa 100), state=all/open/closed/review |
| GET /api/v1/charging/sessions/{id}/samples | Phân trang số đo của phiên trong phạm vi quyền |
| GET /api/v1/charging/cards | Tối đa 100 thẻ mới nhất, che mã |
| POST /api/v1/charging/cards | id_tag (1–20 ký tự), driver_email tài khoản đang hoạt động, expires_at tùy chọn |
| PATCH /api/v1/charging/cards/{id} | status=active/blocked |
| GET /api/v1/charging/pending | Tối đa 100 tin mới nhất, metadata để quan sát |

Số đo hỗ trợ Energy.Active.Import.Register (Wh/kWh), Power.Active.Import/Power.Offered (W/kW), Current.Import (A), Voltage (V), SoC (Percent), Frequency (Hertz), Temperature (Celsius/Celcius). Chuẩn hóa năng lượng về Wh, công suất W; giữ phase/location. Công tơ đầu/cuối OCPP là Wh. Không diễn giải SignedData thành số.

DATABASE_POOL_SIZE=20 là số kết nối giữ lại cho mỗi process, overflow tối đa 10. Điều chỉnh theo ngân sách kết nối PostgreSQL khi tăng worker. Bằng chứng NFR là máy local, một process, DB đã kết nối (lần đo cuối tối đa 110 ms); không cam kết độ trễ triển khai qua Internet.

## Kiểm thử thủ công

1. Chạy migration; khởi động backend/frontend theo README. Đăng nhập owner/operator/admin, mở **Phiên sạc**.
2. Trong **Thẻ tài xế**, cấp mã DEMO-CARD-2026 cho email một tài xế đang hoạt động. Sau lưu chỉ thấy …2026. Khóa/mở khóa và kiểm tra trạng thái thật sau tải lại.
3. Dùng trụ đã đăng ký và đầu nối 1. Từ repo chạy `python scripts/charging_simulator.py --url ws://127.0.0.1:8001 --code MA-TRU --duration 40` (đổi port đúng backend). Simulator dùng mã giả DEMO-CARD-2026; mã khác đặt biến CSMS_SIMULATOR_ID_TAG.
4. **Danh sách phiên** có phiên đang mở, số đo tăng mỗi 10 giây; mở chi tiết thấy số đo/time. Sau 40 giây phiên kết thúc, kWh bằng hiệu công tơ đầu/cuối. Gửi lại Start cùng messageId không sinh thêm phiên.
5. Chạy thêm `--regression`: khi một số đo giảm, phiên xuất hiện trong bộ lọc **Cần xem xét**, vẫn lưu số đo; kWh cuối tính từ endpoint.
6. **Chờ đối chiếu** có StopTransaction không biết phiên do simulator gửi. Không có phiên mới giả hoặc nút xử lý chưa được triển khai.
7. Khóa thẻ rồi chạy simulator: Authorize trả Blocked; nếu trụ vẫn gửi Start thì phiên ghi nhận bị từ chối và review. API quản lý với driver trả 403; owner khác không đọc/sửa dữ liệu ngoài phạm vi.
8. Ngắt backend: UI báo lỗi, dữ liệu cũ giữ để tham khảo; khởi động lại/bấm Làm mới khôi phục. Kiểm tra ở màn hình hẹp và mở chi tiết samples.

Preview đã chuẩn bị riêng tại http://127.0.0.1:5177/ (backend 8004), DB csms_charging_preview_20261002, không dùng dữ liệu dự án đang chạy. Tài khoản demo operator.charging@example.com / DemoCharging2026!, tài xế driver.charging@example.com; trụ DEMO-CHARGING-01. Đây là tài khoản giả chỉ cho local. Dữ liệu mẫu có phiên 2,5 kWh, trường hợp blocked/counter giảm và phiên simulator 0,25 kWh. Preview là tiến trình tạm, cần còn đang chạy để truy cập.

## Bằng chứng và giới hạn

- Backend: 250 tests passed bằng pytest CLI trực tiếp, gồm regression nhóm 1/2; DB kiểm thử riêng csms_charging_test_20261002.
- Frontend: 131 tests / 25 files passed; ESLint và TypeScript/Vite build đạt.
- Ruff lint, Ruff format --check và mypy được chạy trước bàn giao; migration nâng/hạ/nâng lại từ nền nhóm 2 thành công, alembic check không có thay đổi schema còn thiếu.
- Demo WebSocket → PostgreSQL → HTTP API → giao diện đã kiểm tra; desktop và mobile 390 px giữ bố cục hiện có.
- Pending chỉ quan sát. Nối lại/đối chiếu tin muộn/đóng tay thuộc nhóm 4; điều khiển từ xa nhóm 5; màn hình phiên tài xế nhóm 6. Trạng thái phiên mở không thay thế StatusNotification về trạng thái vật lý đầu nối. Chưa thực hiện thanh toán/giá/đặt chỗ.

## Biểu đồ số đo (cập nhật frontend)

Chi tiết phiên dùng biểu đồ đường chuỗi thời gian cho điện năng tích lũy, công suất nạp/cấp, điện áp, dòng điện, mức pin, nhiệt độ và tần số. Người dùng chọn thông số và pha/vị trí đo; không trộn các series hoặc đơn vị. Wh/kWh hiển thị kWh, W/kW hiển thị kW. Chỉ các thông số thật có dữ liệu trên trang đang xem mới xuất hiện trong danh sách chọn.

API số đo giữ nguyên, frontend yêu cầu page_size=100 thay cho 20 để biểu đồ có nhiều điểm hơn. Mỗi trang tối đa 100 bản ghi của mọi thông số, không phải 100 điểm cho từng đường. Số đo được sắp theo thời gian trụ, trục X giãn theo khoảng thời gian thực. Một điểm chỉ vẽ điểm; không có dữ liệu thì hiện trạng thái trống. Bảng gốc và thông tin thẻ/công tơ/lý do dừng nằm trong mục **Thông tin phiên và bảng số đo**. Thanh **Chọn số đo** hỗ trợ cảm ứng và bàn phím để đọc giá trị/time; đoạn điện năng giảm có nét đứt và dấu cảnh báo. Điện áp/công suất giảm không tự bị coi là lỗi.

Danh sách giữ mã phiên, trạm/đầu nối, trạng thái, điện năng chốt, thời gian và lý do xem xét khi có. Điện năng chốt tiếp tục do backend tính từ công tơ đầu/cuối; biểu đồ không thay phép tính. Không sửa backend, migration hoặc dependency frontend trong lượt đổi biểu đồ.

Tham khảo: [Grafana time series](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/time-series/) và [ChargePoint reporting](https://docs.chargepoint.com/cpdocs-sec/content/3-dc/express-250/omg/reporting.htm). Áp dụng đường cho dữ liệu biến đổi trong phiên; không dùng nến OHLC vì mẫu OCPP không phải giá mở/cao/thấp/đóng của mỗi khoảng. Biểu đồ tổng hợp tiêu thụ theo ngày/tháng là phạm vi khác.

Demo preview bổ sung phiên #6 với 90 số đo tổng hợp giả gửi qua OCPP thật (L1/L2, đủ 8 thông số và một số đo điện năng giảm), chỉ nằm trong DB preview. Mở **Xem biểu đồ phiên 6**, đổi **Thông số**, chọn **Nguồn số đo**, kéo thanh **Chọn số đo**; thử Home/End hoặc phím mũi tên. Kiểm tra thông tin chi tiết/bảng vẫn đọc được và phiên không có số đo hiển thị trống.
