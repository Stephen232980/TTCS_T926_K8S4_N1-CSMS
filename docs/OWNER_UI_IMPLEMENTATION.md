# Giao diện chủ trạm — triển khai trên frontend

Ngày kiểm chứng: 04/10/2026. Nhánh `feature/owner-interface`, xuất phát từ main `e8be79b` sau khi merge API ảnh/thông số trụ. Người dùng đã cho phép triển khai giao diện; các bản mẫu cũ vẫn giữ nguyên trong thư mục `impeccable` ngoài Git.

## Phạm vi

App chuyển vai trò chủ trạm sang workspace riêng; các vai trò khác giữ luồng hiện có. Phong cách A đã chốt: sidebar xanh đậm, nền sáng, khối trụ mô phỏng, đầu nối dùng màu và ký hiệu, nội dung chi tiết xuất hiện khi chọn đầu nối. Khung desktop cố định theo chiều cao màn hình; danh sách và vùng chi tiết cuộn nội bộ, phân trang/bộ lọc vẫn ở vị trí cố định. Mobile chuyển sang menu và bố cục một cột.

| Màn hình/luồng | Dữ liệu và thao tác |
|---|---|
| Trạm của tôi | Tìm tên/địa chỉ, lọc trạng thái, phân trang, ảnh đại diện; ưu tiên trạm bị khóa/tạm ngừng trên trang hiện tại |
| Tạo/sửa trạm | Hai bước thông tin/vị trí và ảnh/kiểm tra; tọa độ có thể chọn trên bản đồ; lưu ảnh qua API, tải lại ảnh lỗi không tạo trạm trùng |
| Chi tiết trạm | Các khối trụ/đầu nối, trạng thái OCPP và kết nối, chọn đầu nối xem số đo phiên đang mở; công suất danh định tách khỏi công suất đo |
| Thêm/sửa trụ | Ba bước thông tin trụ, cấu hình đầu nối và kiểm tra; tên trụ, loại đầu nối, AC/DC, kW/V/A; hãng/model/firmware chỉ đọc từ OCPP |
| Phiên sạc | Phân trang/lọc trạng thái, nhóm theo tên trạm trong kết quả trang hiện tại; xem chi tiết, số đo, biểu đồ và lịch sử phục hồi |
| Thẻ tài xế | Nhóm theo email tài xế, cấp thẻ qua hai bước với mã giả lập tự nhập, khóa/mở khóa thẻ |
| Chờ đối chiếu | Xem bản tin chờ đối chiếu, tìm theo mã trụ; không có thao tác xử lý thủ công |

Chủ trạm không có nút điều khiển từ xa hoặc đóng tay phiên. Quyền dữ liệu do backend xác thực theo session và phạm vi sở hữu. API 401 đưa người dùng về đăng nhập.

## Những chức năng chưa có backend

Biểu giá (S-28–S-34), báo cáo doanh thu (S-52), cấu hình/phân bổ công suất (S-42–S-45), hoạt động/tạm ngừng trạm (S-66) chưa được triển khai trong nhánh này. Sidebar giữ các mục đã chốt nhưng trang giải thích chưa khả dụng, không đưa số tiền giả hay nút lưu không hoạt động. Trạng thái trạm hiện tại chỉ xem; không có công tắc thay trạng thái.

API phiên chưa có lọc theo station ID và nhóm/pagination cấp trạm. Nhóm hiện tại theo `station_name` trong trang kết quả; trạm trùng tên có thể vào cùng nhóm và một trạm có thể xuất hiện ở nhiều trang. Không tuyên bố đây là phân trang theo trạm. Chờ đối chiếu/thẻ dùng phạm vi danh sách API hiện có.

Số đo hiển thị dấu — khi thiếu dữ liệu, có thời điểm nhận số đo. Công suất tổng chỉ dùng số đo không có pha, không tự cộng hoặc chọn tùy tiện một pha. Biểu đồ giữ lựa chọn nguồn số đo theo pha/vị trí. Số đo thuộc trang được tải; API chưa có endpoint snapshot mới nhất cho từng chuỗi. Giám sát, phiên và số đo được tải lại mỗi 5 giây khi trang đang hiển thị.

## Chạy và kiểm chứng

Frontend: `cd frontend`, `npm ci`, `npm run dev`. Vite mặc định proxy `/api` về `http://localhost:8001`; dùng `CSMS_DEV_API_TARGET` để trỏ môi trường khác. Có thể đặt `VITE_API_BASE_URL` cho backend riêng với chính sách cookie/CORS phù hợp.

Backend phải có dependency Pillow và migration `a4d901ce8207` như [API delivery](OWNER_UI_API_DELIVERY.md). Không chỉ chạy frontend mới với container backend cũ chưa có migration/API mới.

Lượt kiểm tra của nhánh dùng Vite `http://127.0.0.1:5173` và backend thử riêng `http://127.0.0.1:8014`, database `csms_owner_api_20261004`. Không thay container/backend hoặc database CSMS đang chạy. Các trạm thử có nhãn Demo; ảnh đại diện thử là ảnh AI minh họa từ bản mẫu, không phải ảnh một trạm thật.

- 157 bài kiểm thử frontend đạt, gồm quyền theo vai trò, luồng giữ trạm khi tải ảnh lỗi, sửa metadata trụ đã khóa mã, cấp thẻ sau bước kiểm tra.
- Build production và ESLint đạt. Build có cảnh báo bundle vượt 500 kB, chưa tối ưu chia bundle ở phạm vi này.
- Trình duyệt xác nhận lưu/tải lại ảnh qua API, cấp thẻ, xem phiên/số đo/biểu đồ; sáu trụ giả lập gửi OCPP vào backend thử riêng. Số đo thử được nhận qua MeterValues, không chèn số giả vào frontend.
- Khung 1366×768, 1440×810 và mobile 390×844 đã được chụp để kiểm tra. Ảnh trong `impeccable/review/owner-implementation`, ngoài Git. Mechanical detector trả danh sách rỗng.

Review độc lập yêu cầu sửa hai điểm: làm mới dữ liệu phiên được chọn và thể hiện kết nối bằng ký hiệu cùng thời gian liên lạc cuối. Đã bổ sung kiểm thử phiên kết thúc rồi rời bộ lọc đang mở, và ba ký hiệu kết nối khác nhau. Chi tiết phiên được làm mới từ danh sách; khi phiên rời trang/bộ lọc hiện tại, frontend tìm lại trong các trang phạm vi được phép xem. API chi tiết phiên theo ID sẽ giúp giảm lượt gọi khi dữ liệu lớn. Kiểm chứng cục bộ không thay cho CI, staging hoặc thiết bị thật. Chưa commit/push giao diện.


Review Impeccable cuối: disposition ship, cả hai điểm sửa được chấm resolved; vòng chấm cuối chỉ đánh giá hai điểm này. Trình duyệt giữ chi tiết phiên #247 trong bộ lọc đang mở khi trụ giả lập gửi StopTransaction: giờ kết thúc và điện năng chốt 3,2 kWh tự cập nhật. Ký hiệu ngoại tuyến và thời gian liên lạc cuối được xác nhận ở desktop/mobile trên dữ liệu thử riêng. Tài liệu hệ thống thiết kế được ghi tại DESIGN.md và sidecar .impeccable/design.json.

## Sửa lỗi sau kiểm thử của người dùng (04/10)
Ảnh: tăng giới hạn đồng bộ lên 20 MiB, giữ trần 16 triệu điểm ảnh; lấy khung hình đầu của WebP/PNG động để lưu ảnh đại diện tĩnh. Frontend nhận dạng nội dung JPEG/PNG/WebP để gửi MIME đúng khi đuôi tệp khác định dạng thật. Đã kiểm tra WebP động qua PUT/GET backend trả 200 và chuẩn hóa thành JPEG; chưa có tệp WebP gốc người dùng để tái hiện chính xác lỗi ban đầu.
Đầu nối: danh sách các chuẩn phổ biến và mục Khác để giữ khả năng mở rộng/metadata cũ. Không tự suy ra công suất hoặc thay thông số điện theo tên đầu nối.
Thẻ: lỗi 422 email tài xế chưa tồn tại được báo đúng nghiệp vụ, không còn nội dung ảnh. Email tài xế thử có sẵn: driver-ui-test@example.com. Không tạo tài khoản mới trong luồng cấp thẻ.
Phiên: đang mở hiển thị điện đã cấp từ latest meter trừ meter start; điện năng chốt chỉ dùng khi kết thúc. Các số đo tổng mới nhất lấy trang đầu, độc lập trang mẫu cũ được xem. Biểu đồ/bảng đặt cạnh nhau trên desktop, xếp dọc ở màn hình nhỏ. Giả lập kiểm thử ban đầu chỉ gửi một gói số đo; helper local đã chuyển sang MeterValues định kỳ 10 giây. Giữ nguyên phiên248; không giả lập số đo trong frontend.
12 kiểm thử API ảnh/metadata đạt trên database thử riêng. Kiểm thử frontend bổ sung cho MIME, lỗi theo ngữ cảnh và live measurements. Backend ảnh và tests/doc API thay đổi riêng biệt với frontend để có thể commit riêng sau này.

Kết quả cuối sau sửa: 164 kiểm thử frontend, 12 kiểm thử API ảnh/metadata, build, ESLint và Ruff đạt. Review cuối disposition ship: điểm cần sửa về vùng cuộn mobile được chấm resolved; chi tiết phiên mobile cuộn chung, desktop giữ khung cố định. Backend test8014 đã khởi động lại để áp dụng giới hạn mới. Chưa commit/push.

Kiểm chứng bổ sung: chọn WebP động qua file chooser ở giao diện sửa trạm Demo8 rồi bấm Lưu thay đổi; giao diện nhận trạng thái Đã lưu thông tin trạm. Ảnh được đọc lại qua API sau chuẩn hóa. Fixture ảnh thử do kiểm thử tạo, không phải tệp WebP gốc của người dùng.


## Rà soát luồng và mật độ giao diện (04/10/2026)

| Luồng đã có backend | Kết quả rà soát |
|---|---|
| GET/POST/PATCH trạm, PUT/GET/DELETE ảnh | API thật, có cookie xác thực; thông tin và ảnh lưu riêng, thử lại ảnh không tạo trùng trạm; ảnh lỗi tải có nút tải lại |
| GET/POST trụ, kiểm tra mã, PATCH tên/thông số | API thật; khóa mã sau giao dịch, số đầu nối khi sửa giữ theo khả năng API; loại đầu nối có danh sách và mục khác |
| GET /ocpp/connections | Đọc đầy đủ các trang; mất dữ liệu giám sát hiển thị chưa rõ, không dùng trạng thái lưu cũ để khẳng định đang sạc |
| GET phiên mở và số đo của đầu nối | Ghép theo mã trụ + số đầu nối; sửa lỗi dùng trang số đo cuối (cũ nhất), nay lấy trang 1 (mới nhất) |
| Xem phiên từ đầu nối | Mở đúng ID phiên từ kết quả backend, kể cả phiên không thuộc trang danh sách đầu tiên |
| Phiên, samples, events | Lọc/phân trang thực, cập nhật 5 giây; số đo mới nhất tách khỏi trang lịch sử; sự kiện phục hồi đọc API, không tạo sự kiện giả |
| Cấp/khóa/mở khóa thẻ | POST/PATCH thật; tách lỗi thao tác khỏi lỗi tải danh sách, nút cấp lại thực sự POST; thẻ đã hết hạn hiển thị đúng |
| Bản tin chờ | GET thật; tìm kiếm không có kết quả có thông báo; API chỉ trả tối đa 100 bản tin/thẻ mới nhất, UI ghi rõ khi chạm giới hạn |

Giả lập thử trước đây gửi Charging cho nhiều đầu nối dù chỉ một đầu nối có StartTransaction. Kịch bản thử trong thư mục Git-ignored `.local` đã sửa: chỉ OWNER-UI-1-1/2 có giao dịch 248 và Charging; đầu nối khác gửi Available/Faulted tương ứng. Frontend không suy diễn hoặc thay đổi trạng thái trụ báo về. Nếu trụ báo Charging nhưng backend chưa có phiên mở, panel thông báo chờ đồng bộ và không tạo số đo giả. Trụ ngoại tuyến kèm chú thích số đo là lần nhận cuối; lỗi thiết bị lịch sử ghi rõ thời điểm, không trình bày như lỗi hiện tại.

Desktop: tab và nút phân trang 34px; thu gọn thông tin phụ, biểu đồ chiếm 60% vùng nội dung, bảng cuộn độc lập. SVG dùng kích thước vùng thực để giữ chữ dễ đọc khi thay đổi chiều cao; biểu đồ, chọn điểm và chú thích nằm trong màn hình 1366×768 và 1920×1080. Mobile giữ đích chạm 44px và cuộn vùng nội dung. Ảnh kiểm chứng trong `impeccable/review/owner-implementation`: density-session-1366.jpg, density-session-1920-full.jpg, density-session-mobile.jpg, sync-connector-1366.jpg, density-older-power.jpg.

Kiểm thử: 170 frontend tests đạt; 65/66 backend tests đạt trên database kiểm thử sạch riêng `csms_owner_flows_20261004_1907`, gồm charging sessions/recovery/monitoring và 12 owner API extensions. Bài NFR 20 trụ phản hồi dưới 200ms chưa đạt: đo 210ms, chạy riêng lại cũng 210ms. Đây là giới hạn kiểm chứng hiệu năng đang mở, không phải thiếu endpoint giao diện. Không sửa ngưỡng kiểm thử để lấy kết quả đạt. Không thay database/container CSMS chính.


Lượt rà soát cuối đã sửa hai lỗi bổ sung: lịch sử phục hồi được gắn với ID phiên và có trạng thái tải, không dùng sự kiện của phiên trước; panel số đo dành chỗ riêng cho lỗi tải lại. ResizeObserver đồng bộ kích thước SVG trong cùng lượt vẽ để tránh biểu đồ co nhỏ khi vùng nội dung thay đổi. Kiểm chứng bằng việc tạm dừng backend thử rồi chạy lại: biểu đồ cache, trục, giá trị, thanh chọn điểm, chú thích và nút tải lại đều nhìn được ở 1366×768; thông báo nói rõ đang giữ dữ liệu lần tải thành công trước. Hai sửa lỗi được reviewer chấm resolved; verdict này chỉ bao phủ danh sách sửa lỗi, không chứng nhận hiệu năng backend. Build/lint đạt; bundle 525 kB còn cảnh báo lớn hơn 500 kB.

Ảnh cuối: `density-session-1366-final.jpg`, `density-session-1920-final.jpg`, `density-api-failure-1366-final.jpg`, `history-session-a-fixed.jpg`, `history-session-b-fixed.jpg` dưới thư mục bằng chứng nói trên. Ảnh lỗi API cũ `density-api-failure-1366.jpg` có tọa độ SVG chưa cập nhật khi chụp, đã được thay bằng bản `-final`; không dùng ảnh cũ làm bằng chứng hoàn tất.
