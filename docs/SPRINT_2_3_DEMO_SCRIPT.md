# Kịch bản demo Sprint 2 và Sprint 3

Đối chiếu trực tiếp `.local/project-inputs/Backlog CSMS.xlsx`, sheet `Backlog CSMS`, ngày 06/10/2026. Sprint 2 gồm S-06–S-16; Sprint 3 gồm S-17–S-27. Cột Status trong bản Excel là Todo, nên tài liệu này mô tả cách chứng minh chức năng hiện có, không xác nhận toàn bộ story đã nghiệm thu.

Không demo vai trò kế toán theo yêu cầu. Các story S-14, S-20, S-25 vẫn được trình bày qua vận hành và bằng chứng kỹ thuật. Các chức năng chuẩn bị tài khoản, trạm/trụ và bản đồ được ghi riêng là nền hoặc phần làm sớm.

## 1. Luồng tổng thể và thời lượng

**Chủ trạm chuẩn bị trụ → tài xế chọn đầu nối và bắt đầu → vận hành giám sát, xử lý → tài xế kiểm tra kết thúc → quản trị truy vết → kỹ thuật chứng minh phục hồi và CI.**

| Phần | Vai trò | Thời lượng | Story trọng tâm |
|---|---|---|---|
| Chuẩn bị thiết bị | Chủ trạm | 4 phút | Nền S-04/S-05; S-06, S-08, S-11 |
| Tìm trạm, bắt đầu và theo dõi | Tài xế | 5 phút | S-24, S-17, S-19, S-22 |
| Giám sát và dừng phiên | Vận hành | 5 phút | S-09–S-12, S-16, S-23, S-18 |
| Theo dõi dữ liệu và phạm vi sở hữu | Chủ trạm | 2 phút | S-11, S-18, S-19 |
| Truy vết | Quản trị | 2 phút | S-27 |
| Ngoại lệ, phục hồi, bằng chứng CI | Vận hành + người trình bày kỹ thuật | 7–12 phút | S-07, S-13–S-15, S-20, S-21, S-25, S-26 |

Nếu chỉ có 15 phút, ưu tiên luồng chính đến nhật ký; chuẩn bị sẵn bằng chứng cho các ca kỹ thuật và chỉ mở khi được hỏi.

## 2. Chuẩn bị trước buổi demo

1. Docker Desktop chạy; backend trên `http://127.0.0.1:8001`, PostgreSQL và migration hiện tại sẵn sàng; frontend `http://localhost:5173`.
2. Bộ giả lập local đang chạy và đã có bản sửa đầy đủ số đo. Dùng script local đã có khi cần khởi động:

   ```powershell
   .\.local\start-csms-demo.ps1
   ```

   Script này có bước seed dữ liệu demo; chạy chuẩn bị trước buổi trình bày. Không chạy lại để sửa lỗi giữa buổi. Nếu đã chạy, không mở thêm simulator cùng mã trụ.
3. Chuẩn bị bốn phiên trình duyệt độc lập, hoặc đăng xuất/đăng nhập khi đổi vai trò: chủ trạm, tài xế, vận hành, quản trị. Mật khẩu để trong tài liệu local riêng, không chiếu lên màn hình.
4. Tài xế demo phải **không có phiên đang mở hoặc yêu cầu bắt đầu đang chờ**. Nếu đang có, nhờ vận hành dừng và xác nhận kết thúc trước buổi.
5. Chọn một **trạm đang active**, thuộc chủ trạm demo, với trụ online và ít nhất hai đầu nối Available. Ghi trước tên trạm, mã trụ, đầu nối 2/3. Không cố định ID phiên vì mỗi lần demo tạo ID mới.
6. Chuẩn bị một đầu nối Faulted để giới thiệu lỗi; bộ dữ liệu mẫu có đầu nối 4 của `UI-DEMO-005`/`UI-DEMO-015`, nhưng phải kiểm tra lại trạng thái thực trước buổi.
7. Trụ phục hồi và trụ thử Rejected/Timeout phải riêng biệt, **không do fleet đang quản lý**. Ưu tiên backend/database demo riêng không chạy fleet. Watcher có tham số Python `excluded`, nhưng CLI hiện chưa có tùy chọn loại trừ; không dùng một cờ CLI chưa hỗ trợ. Không dùng cùng mã cho hai simulator, trừ ca kiểm chứng S-13 có chủ đích.
8. Chuẩn bị trang CI của commit/PR sẽ trình bày. Chỉ nói CI đạt khi chính lượt chạy đó xanh; lưu log/artifact S-26 tương ứng.

**Các thành phần thực sự chạy:** frontend hiển thị và gọi API; backend xác thực/phân quyền, nhận WebSocket OCPP, xử lý phiên và chạy job; PostgreSQL lưu hồ sơ/số đo/nhật ký; simulator đóng vai trụ vật lý, gửi Boot/Heartbeat/Status/MeterValues và trả lời lệnh. Simulator phải chạy thì trụ mới liên lạc được; `npm run dev` chỉ khởi động frontend.

## 3. Phần A — Chủ trạm: chuẩn bị tài sản và quan sát trụ

**Lời dẫn:** “Chủ trạm khai báo thiết bị; thiết bị chỉ trở thành trực tuyến khi kết nối và gửi thông tin khởi động hợp lệ.”

| Bước | Thao tác | Kết quả cần chỉ trên màn hình | Liên hệ backlog |
|---|---|---|---|
| A1 | Đăng nhập chủ trạm, mở danh sách trạm | Chỉ thấy trạm thuộc quyền sở hữu | Nền phân quyền; S-11 |
| A2 | Mở trạm active đã chuẩn bị, giới thiệu thông tin và vị trí | Thông tin trạm, các trụ và đầu nối thật | Nền S-04/S-05 |
| A3 | Tạo trụ mới, mã `DEMO-SP23-001` nếu chưa tồn tại, cấu hình hai đầu nối theo form | Hồ sơ trụ được lưu; chưa có kết nối không được gọi là online | Nền S-05; S-06 |
| A4 | Chờ fleet phát hiện khoảng 5 giây và simulator Boot | Trụ online, đầu nối Available, có thời điểm liên lạc cuối | S-06, S-08, S-09, S-10 |
| A5 | Giữ màn hình, cho biết vận hành sẽ thấy cùng trụ nhưng phạm vi toàn mạng | Trạng thái lấy từ thiết bị, không tự đổi chỉ vì đã khai báo | S-11 |

Không cần tạo trụ mới nếu thời gian ngắn; dùng trụ đã chuẩn bị và chuyển thẳng A5. Tạo trụ với các đầu nối ngay trong form hiện có; không hứa có thao tác tăng số đầu nối của trụ đã tạo nếu form/API chưa hỗ trợ.

**Nếu được yêu cầu tạo cả trạm mới:** có thể tạo hồ sơ trạm, chọn vị trí, tạo trụ/đầu nối và cho simulator kết nối. Tuy nhiên trạm mới mặc định inactive và hiện chưa có luồng giao diện kích hoạt đầy đủ; tài xế sẽ không tìm thấy hoặc bắt đầu được ở đó. Để demo trọn luồng ngay, tạo trụ trong **trạm active đã chuẩn bị**. Không trình bày rằng tạo trạm mới là tự sạc được ngay.

Nếu không dùng fleet, mở terminal riêng và chạy:

```powershell
.\.venv\Scripts\python.exe scripts/ocpp_control_simulator.py `
  --url ws://127.0.0.1:8001 `
  --code DEMO-SP23-001 `
  --start-delay 10
```

Mã phải đúng hồ sơ đã đăng ký, database của script phải trùng backend. Không chạy lệnh này nếu fleet đã kết nối cùng mã. `--start-delay 10` giúp nhìn rõ giai đoạn chờ giữa Accepted và StartTransaction.

## 4. Phần B — Tài xế: bắt đầu và theo dõi phiên

**Lời dẫn:** “Tài xế chọn đầu nối sẵn sàng. Hệ thống gửi yêu cầu xuống trụ; phiên chỉ xuất hiện khi trụ xác nhận bắt đầu thực sự.”

| Bước | Thao tác | Kết quả mong đợi | Story |
|---|---|---|---|
| B1 | Đăng nhập tài xế, mở phiên hiện tại | Trạng thái chưa có phiên và lối tắt tìm trạm | S-22 |
| B2 | Tìm trạm active theo tên, chọn trên bản đồ/danh sách | Đúng vị trí và trạm đã chuẩn bị | Phần bản đồ làm sớm của S-47 |
| B3 | Mở đầu nối của trụ demo | Available chọn được; Charging/Faulted/Reserved không dùng để bắt đầu | S-24 |
| B4 | Chọn đầu nối 2, tích xác nhận đã cắm súng, bấm bắt đầu một lần | Yêu cầu được gửi, hiển thị chờ nếu chưa có StartTransaction | S-24 |
| B5 | Chờ trụ gửi StartTransaction | Hiện phiên thực, đúng trạm/trụ/đầu nối, thời điểm bắt đầu và ID do backend cấp | S-17, S-24 |
| B6 | Giữ màn hình 10–15 giây | kWh và thời lượng tăng; không cần reload | S-19, S-22 |
| B7 | Sang tìm trạm/đầu nối khi còn phiên | Không được bắt đầu phiên thứ hai cho cùng tài xế | S-24 |

Ghi lại ID phiên vừa tạo để vận hành tìm đúng. Xác nhận cắm súng trong demo là mô phỏng thao tác vật lý, không chứng minh cảm biến cáp thật. Luồng này dùng thẻ ảo của tài xế; để chứng minh `Authorize` thẻ vật lý của S-15, dùng ca riêng ở phần kỹ thuật.

Tùy chọn: dùng tài xế thứ hai bắt đầu ở đầu nối 3 cùng trụ. Chỉ rõ hai ID phiên và số đo riêng; khi dừng đầu nối 2, đầu nối 3 tiếp tục sạc.

## 5. Phần C — Vận hành: giám sát, Reset và dừng

**Lời dẫn:** “Vận hành nhìn toàn mạng, thấy trạng thái từng đầu nối và có quyền gửi lệnh để xử lý sự cố.”

| Bước | Thao tác | Kết quả mong đợi | Story |
|---|---|---|---|
| C1 | Đăng nhập vận hành, mở Giám sát trụ | Nhiều trạm; nhóm cần chú ý, đang sạc, sẵn sàng | S-11 |
| C2 | Chọn trụ demo, chọn đầu nối 2 | Charging, đúng phiên của tài xế; thời điểm liên lạc cuối mới | S-09, S-10, S-11 |
| C3 | Chọn đầu nối khác rồi quay lại | Phiên/số đo khớp đầu nối, không lẫn nhau | S-10, S-19 |
| C4 | Mở đầu nối Faulted đã chuẩn bị | Mã lỗi và thời điểm, trạng thái lỗi thật | S-10 |
| C5 | Chọn **trụ riêng không đang sạc**, gửi Reset Soft và xác nhận | Lệnh Accepted hoặc kết quả thực tế của trụ | S-16 |
| C6 | Mở Phiên sạc, tìm ID vừa tạo, vào chi tiết | Công suất, nhiệt độ, điện áp, dòng điện; biểu đồ/bảng số đo | S-17, S-19 |
| C7 | Đổi đại lượng trên biểu đồ, chọn điểm và xem thời gian/giá trị | Số đo theo timestamp, đơn vị rõ | S-19 |
| C8 | Bấm Dừng từ xa cho đúng ID, xác nhận | Lệnh RemoteStopTransaction; chờ StopTransaction thật | S-23 |
| C9 | Quan sát kết quả | Phiên kết thúc, giờ kết thúc, kWh chốt; đầu nối trở về Available | S-18, S-23 |

Nêu rõ: **Accepted chỉ là trụ nhận lệnh**. Simulator hiện trả lời Reset mà không mô phỏng reboot vật lý hoặc tự xóa Faulted. Kết thúc phiên do StopTransaction, không do màn hình tự đổi trạng thái sau Accepted. kWh chốt bằng `(meterStop − meterStart) / 1000`; chưa có tính tiền/thanh toán.

Quay lại màn hình tài xế: phiên không còn đang sạc và có thể bắt đầu lại. Tài xế hiện chưa có nút dừng trên giao diện; thao tác rút súng chưa được mô phỏng ở màn hình tài xế, nên vận hành dừng từ xa là cách kết thúc demo hiện tại.

## 6. Phần D — Chủ trạm: kiểm tra kết quả kinh doanh vận hành

1. Quay lại chủ trạm, mở phiên vừa kết thúc; chỉ ID, đầu nối, bắt đầu/kết thúc, điện năng và lịch sử số đo.
2. Mở giám sát trạm: đầu nối vừa dừng sẵn sàng; nếu có tài xế thứ hai, đầu nối còn lại vẫn Charging.
3. Có thể đổi sang chủ trạm thứ hai để chỉ phạm vi dữ liệu khác; không truy cập được phiên/trụ của chủ trạm thứ nhất.

Đây là quan sát vận hành theo S-11/S-18/S-19. Không diễn giải kWh thành doanh thu khi chưa triển khai giá và thanh toán.

## 7. Phần E — Quản trị: truy vết người điều khiển

**Lời dẫn:** “Sau sự cố, quản trị tra được ai gửi lệnh, gửi tới đâu và trụ trả lời thế nào.”

1. Đăng nhập quản trị, mở Nhật ký thao tác, chọn nguồn điều khiển OCPP.
2. Lọc mã trụ demo, email vận hành chính xác và khoảng thời gian buổi demo.
3. Mở bản ghi RemoteStop: người thực hiện, thời điểm, phiên, mã trụ, kết quả. Mở bản ghi Reset của trụ riêng.
4. Chỉ rõ nhật ký không có nút sửa/xóa. AC trả 405/chống sửa ở DB dùng bằng chứng test, không chỉ suy ra từ việc thiếu nút.

Story chính S-27. Tài khoản quản trị chỉ có admin không tự có quyền Reset/Stop; vận hành gửi lệnh, quản trị đọc nhật ký.

Nếu còn thời gian, giới thiệu cấp/khóa tài khoản và Sức khỏe hệ thống. Đây là hỗ trợ demo/phần làm sớm S-61/S-63, không thay bằng chứng S-26 hay khẳng định các story Later đã hoàn tất.

## 8. Phần F — Các ca kỹ thuật và ngoại lệ

Chạy bằng trụ riêng và môi trường/test database riêng đã chuẩn bị. Kiểm thử tự động là bằng chứng cho nhánh lỗi; không gọi là vừa demo giao diện nếu chỉ chiếu kết quả test. Không sửa database để tạo dữ liệu lỗi trong lúc đang trình bày luồng chính.

| Ca | Cách trình bày và kết quả cần chứng minh | Story |
|---|---|---|
| Mã trụ lạ/subprotocol sai | Cho xem test WebSocket từ chối mã không đăng ký và giao thức khác ocpp1.6. CLI simulator thông thường kiểm tra DB trước kết nối nên không dùng nó để chứng minh server từ chối mã lạ | S-06 |
| Khung tin | Chiếu transcript/test CALL, CALLRESULT, CALLERROR; frame sai trả lỗi, action chưa hỗ trợ trả NotImplemented; socket vẫn xử lý tiếp đúng | S-07 |
| Boot hợp lệ và bị chặn | Boot Accepted lưu metadata; trạm blocked Boot Rejected; tin trước Boot được chấp nhận bị SecurityError | S-08 |
| Mất liên lạc | Với trụ riêng, Ctrl+C khi đang mở phiên. Chờ quá hai chu kỳ heartbeat và lượt cập nhật: trụ offline, trạng thái đầu nối chưa rõ; phiên không tự đóng | S-09, S-12 |
| Nối lại | Chạy lại simulator cùng mã; phiên và ID giữ nguyên, số đo tiếp tục; xem Lịch sử phục hồi | S-21 |
| Cùng mã hai socket | Test thay socket cũ bằng socket mới và không gửi phản hồi của socket cũ sang socket mới. Không làm trực tiếp trên trụ của fleet | S-13 |
| Tin gửi lặp | Replay Start/Stop cùng messageId qua test hoặc S-26; cùng transactionId, không nhân đôi phiên/số đo. Kho chống trùng tồn tại trong DB sau restart | S-14, S-17 |
| Thẻ | Với thẻ thử local riêng: Authorize Accepted/Blocked/Expired/Invalid; không chiếu mã thẻ đầy đủ. Khóa thẻ trên UI chỉ là chuẩn bị, phải có phản hồi Authorize để chứng minh | S-15 |
| Số đo lỗi | Test số đo trùng bỏ qua; số đo cũ ngoài luồng phục hồi không ghi đè; giá trị lùi gắn cần xem xét. Luồng phục hồi có thể nhận số đo dồn theo timestamp nên không nói mọi số đo cũ đều bị loại | S-20, S-21 |
| Tin không khớp | Test MeterValues không có phiên/Stop sai transactionId vào Chờ đối chiếu; không tự tạo/gán phiên đoán | S-18, S-19 |
| Start bị từ chối | Simulator riêng `--outcome Rejected`: tài xế thấy từ chối, không có phiên giả | S-24 |
| Accepted thiếu Start | Simulator riêng `--omit-start`: tài xế chờ; sau 60 giây được thông báo và thử lại | S-24 |
| Stop bị từ chối | `--outcome Rejected`: vận hành thấy từ chối, phiên vẫn mở | S-23 |
| Accepted thiếu Stop | `--omit-stop`: sau 120 giây cần xem xét, không tự chốt kWh | S-23 |
| Phiên treo và đóng hồ sơ | Phiên riêng offline vượt ngưỡng bất thường → mở Cần xem xét/bộ lọc bất thường → nhập lý do, xác nhận đóng hồ sơ → kWh theo số đo tổng cuối và có lịch sử người đóng | S-25 |

Mất mạng và offline không giống đóng phiên. Mặc định heartbeat thường 60 giây nên offline cần hơn 120 giây kể từ liên lạc cuối, không phải ngay Ctrl+C. Ngưỡng phiên bất thường mặc định 6 giờ **sau mốc offline**, có job quét; không thể ngồi chờ trong buổi demo. Chuẩn bị môi trường riêng giảm ngưỡng trước buổi hoặc dùng fixture/test đã có. Đóng hồ sơ không gửi lệnh dừng trụ.

Generic simulator giữ ID/công tơ phiên mở khi chạy lại, nhưng không tự lưu toàn bộ số đo offline để gửi dồn. Nhánh MeterValues dồn và Stop muộn chứng minh bằng test/S-26, không gán cho ca Ctrl+C rồi chạy lại đơn giản.

Ví dụ cấu hình ca thiếu Start trên **trụ riêng đã đăng ký**, không nằm trong fleet:

```powershell
.\.venv\Scripts\python.exe scripts/ocpp_control_simulator.py `
  --url ws://127.0.0.1:8001 `
  --code DEMO-NEGATIVE-001 `
  --omit-start
```

Không dùng `.local/stop-csms-demo.ps1` để giả lập mất mạng: dừng bộ demo theo cách bình thường gửi StopTransaction và đóng phiên. Với fleet tự kết nối lại, phải bố trí trụ độc lập cho ca mất mạng thay vì dừng cả bộ.

## 9. Phần G — S-26: 20 trụ và CI

**Lời dẫn:** “Ngoài luồng thao tác, hệ thống được kiểm tra tự động với 20 trụ, replay và nối lại để phát hiện mất hoặc nhân đôi phiên.”

1. Mở lượt chạy CI đúng commit: quality, simulator-scenario và Build Docker image.
2. Mở log verifier, tìm `S-26 verified 20/20 online chargers and sessions.` và exit code 0.
3. Mở artifact `s26-simulator-evidence`: log Compose và báo cáo phiên; chỉ ID duy nhất, reconnect, meter stop 3500 Wh và 2,5 kWh cho mỗi phiên trong kịch bản này.
4. Nêu cơ chế required check thất bại khi quality hoặc simulator không thành công. Nếu CI hiện đỏ, trình bày đúng lỗi; không dùng lượt xanh cũ để chứng minh bản mới đạt.
5. Chỉ dùng kết quả performance test riêng để chứng minh ngưỡng dưới 200ms của S-19; nhìn biểu đồ cập nhật nhanh không đủ chứng minh NFR. Tương tự, target S-11 tải dưới 2 giây/cập nhật 1 giây và S-22 cập nhật 2 giây cần đo, không suy ra từ lời kể.

Nếu cần chạy trực tiếp, chuẩn bị môi trường Compose riêng trước buổi theo [S26_SIMULATOR_DELIVERY.md](S26_SIMULATOR_DELIVERY.md):

```powershell
docker compose --profile simulator up --build -d
docker compose --profile simulator logs -f simulator-verify
```

Lệnh trên dùng cấu hình/environment hiện tại; không chạy giữa demo trên stack đang dùng mà chưa bố trí riêng. Bộ 20 trụ local dùng demo UI và bộ S-26 có verifier là hai bộ phục vụ khác nhau; không dùng số lượng trụ online trên UI làm bằng chứng thay cho verifier.

## 10. Checklist kết thúc

- ID phiên vừa demo được giữ từ Start tới Stop; không dùng phiên lịch sử thay cho phiên vừa thao tác.
- Số đo gồm điện năng và các đại lượng bổ sung; những điểm cũ chỉ có điện năng không được điền giả.
- Đầu nối vừa dừng Available; phiên kết thúc có kWh hợp lệ; đầu nối khác không bị ảnh hưởng.
- Nhật ký khớp email vận hành, mã trụ và thời gian.
- Các ca chỉ có test được giới thiệu đúng là bằng chứng test; không tuyên bố phần cứng, chịu tải hoặc thanh toán đã được nghiệm thu.
- Dừng các phiên thử còn mở qua vận hành sau buổi; không đóng nhầm phiên khác.

Tài liệu đối chiếu: [kế hoạch chức năng](SPRINT_2_3_FUNCTION_PLAN.md), [giao diện vận hành](OPERATOR_UI_DELIVERY.md), [tài xế](DRIVER_UI_DELIVERY.md), [phục hồi](OCPP_RECOVERY_DELIVERY.md), [phân quyền hiện tại](ENDPOINT_AUTHORIZATION_DELIVERY.md), [simulator demo](SIMULATOR_DEMO_GUIDE.md). Khi tài liệu lịch sử ghi admin có quyền điều khiển, áp dụng tài liệu phân quyền hiện tại.
