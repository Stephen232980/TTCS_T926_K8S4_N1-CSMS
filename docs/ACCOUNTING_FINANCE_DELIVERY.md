# Tra cứu tài chính cho kế toán

Nhánh `feature/ke-toan-tra-cuu-thanh-toan`, phát triển từ `develop` tại `fc427cc` sau PR #144. Chỉ đọc, không migration, không thay quy tắc lập hóa đơn/quyết toán hoặc lịch sử sổ cái.

## Chức năng

- **Phiên sạc & thanh toán:** tìm mã phiên/hóa đơn, trạm, trụ, email tài xế; lọc trạm, trạng thái tài chính và ngày bắt đầu phiên theo Asia/Ho_Chi_Minh. Tìm kiếm, phân trang và tổng hợp chạy trên toàn bộ kết quả lọc.
- **Hóa đơn phí sạc:** các hóa đơn nội bộ đã lưu, dòng tiền điện/phí chiếm trụ, quy tắc làm tròn, mã và thời điểm lập. Không phát hành hóa đơn điện tử.
- **Cần đối chiếu:** phiên có dữ liệu cần kiểm tra hoặc đã kết thúc nhưng còn chờ rút súng/lập hóa đơn/quyết toán. Chờ có thể là xử lý tự động, không đồng nghĩa lỗi.
- **Đối chiếu khoản trừ ví:** số tiền sổ cái, mã giao dịch, thời điểm và tham chiếu phiên. Hóa đơn 0 đồng không cần debit; legacy_exempt không được tính là tiền đã thu.
- **Kỹ thuật:** mở số đo/lịch sử theo nhu cầu qua API accounting hiện có; giữ nguyên giá trị nguồn, Việt hóa đơn vị/vị trí.

Giữ hệ màu teal và Segoe UI. Desktop dùng bảng rộng; mobile chuyển hàng thành khối, bộ lọc/tài khoản thu gọn. URL giữ bộ lọc/trang/mã phiên; quay lại sau reload/Back giữ cuộn. Cập nhật khi mở trang, đổi bộ lọc hoặc bấm Làm mới, không polling một giây.

## API chỉ đọc

Cookie session, chỉ user đang hoạt động có role `accountant`, permission `accounting.finance.read`, scope `all`. Admin đơn vai trò không tự có quyền. Không có endpoint ghi tương ứng.

| GET dưới `/api/v1/accounting/finance` | Kết quả |
|---|---|
| `/sessions` | Phiên và hóa đơn/quyết toán/sổ cái, phân trang và summary |
| `/invoices` | Cùng cấu trúc, chỉ phiên có hóa đơn đã lưu |
| `/stations` | Trạm có phiên để chọn bộ lọc, gồm lịch sử |
| `/sessions/{session_id}` | Chi tiết phiên, hóa đơn, dòng phí và debit |

Query danh sách: `page` >=1, `page_size` 1–100 (mặc định 20), `q` <=160 ký tự, `station_id` UUID, `date_from`/`date_to` ISO YYYY-MM-DD, `status`, `attention` boolean, `age` (all/under_hour/under_day/under_week/over_week). Khoảng ngày gồm trọn hai ngày theo **bắt đầu phiên** ở sessions/reconciliation, **ngày lập hóa đơn** ở invoices, đều giờ Việt Nam. Ngày đảo thứ tự/trạng thái không hợp lệ trả 422. Ký tự `%`/`_` trong tìm kiếm được escape.

Response: `items`, `total`, `page`, `total_pages`, `summary`. Summary tổng hợp toàn bộ kết quả sau lọc, không chỉ trang hiện tại. Tiền nguyên VND là chuỗi, frontend định dạng bằng BigInt.

Summary: `sessions`, `invoices`, `invoice_total_vnd`, `debited_total_vnd`, `awaiting_settlement`. Tổng hóa đơn không đồng nghĩa tiền đã thu. Tổng debit chỉ gồm charging_debit đúng tài xế/ví, tham chiếu charging_session, số tiền âm khớp tổng hóa đơn và đúng trạm; không cộng nạp tiền, miễn quyết toán hoặc giao dịch không khớp.

| Trạng thái | Ý nghĩa |
|---|---|
| `in_progress` | Phiên đang mở |
| `awaiting_unplug` | Đã dừng, chờ trụ xác nhận giải phóng |
| `needs_review` | Review nguồn hoặc hóa đơn/quyết toán/sổ cái không khớp |
| `pending_invoice` | Đã kết thúc, chưa có hóa đơn, không còn chờ rút súng |
| `pending_settlement` | Có hóa đơn, chưa hoàn tất quyết toán |
| `settled` | Marker quyết toán và debit khớp; hoặc hóa đơn 0 đồng không có debit |
| `legacy_exempt` | Dữ liệu cũ được miễn theo chính sách chuyển đổi |

API không tự sửa nguồn. Khi phát hiện không khớp, response bổ sung lý do trình bày `settlement_ledger_mismatch`, không ghi review vào DB. Marker debited thiếu ledger khớp không được báo đã thanh toán. Review lịch sử vẫn xem được kể cả khi đã quyết toán.

## Kiểm chứng

- 57 kiểm thử backend liên quan qua: 27 ca mới, inventory/phân quyền, hóa đơn tài xế và T-102. DB kiểm thử riêng cổng 5436; không test ghi/xóa trên DB demo hoặc staging.
- 344 kiểm thử frontend qua, gồm 12 ca kế toán; toàn frontend lint/build qua. Ruff và mypy toàn src qua, inventory cập nhật.
- Trình duyệt local 1366×844 và 390×844: ba mục dùng dữ liệu thật, mở dòng phí/debit/số đo; trang 2 → chi tiết → reload → quay lại và Back giữ ngữ cảnh; lọc rỗng rõ nghĩa. Không lỗi JS, không tràn document, không gửi request ghi vào accounting.
- Tại thời điểm kiểm tra local có 5 hóa đơn, tổng và debit khớp 7.402đ; đây là kết quả kiểm chứng, không phải dữ liệu cố định.
- Khôi phục cuộn dùng `behavior: instant` để tránh scroll-behavior smooth toàn cục làm vị trí trượt.
- Đánh giá giao diện và ghi nhận thiết kế thực hiện inline theo impeccable, không phải đánh giá độc lập. Detector layout/type trả `[]`; chưa có chứng nhận WCAG đầy đủ. Build còn cảnh báo chunk nền >500kB đã có trước.

## Thử local và phạm vi

Backend đã cập nhật ở `http://127.0.0.1:8003`, frontend `http://127.0.0.1:5186/#accountant-sessions`. Dùng kế toán local hiện có `demo.accountant.20261005@example.com`. Không thay cutoff, dữ liệu tiền hoặc cấu hình staging.

Ngoài phạm vi: phát hành/in PDF hóa đơn điện tử, kỳ đối soát đối tác, chia doanh thu, điều chỉnh sổ cái, nạp/trừ tiền thủ công, xuất báo cáo toàn hệ thống. Không dùng API tài xế để thay quyền kế toán; không sửa snapshot lịch sử để làm số liệu khớp.

## Tách chức năng và biểu đồ — cập nhật

- Sessions: biểu đồ cột hóa đơn/trừ ví theo ngày bắt đầu phiên, tự nhóm tháng khi khoảng dữ liệu vượt 62 ngày; bảng số liệu mở được. Phân bổ theo trạm có thể bấm để lọc. Đây là tập phiên theo ngày bắt đầu, không phải báo cáo dòng tiền theo ngày ghi sổ.
- Invoices: sổ chứng từ ưu tiên mã hóa đơn, người thanh toán, ngày lập, thành tiền và bằng chứng sổ cái. Sắp chứng từ mới lập trước. Biểu đồ cơ cấu tiền điện/phí chiếm trụ từ các dòng phí đã lưu; nhóm trạng thái để lọc chứng từ.
- Reconciliation: hồ sơ có lý do, hướng dẫn, tổng hóa đơn, khoản trừ khớp và nút sao chép thông tin để chuyển vận hành. Không gửi thông báo hoặc đánh dấu xử lý. Ưu tiên needs_review, rồi thời gian chờ lâu nhất. Biểu đồ tuổi chờ tính từ ended_at, fallback started_at, theo thời điểm tải.
- GET `/api/v1/accounting/finance/insights/{area}`: accountant-only, cùng bộ lọc, không phân trang. Trả grain/generated_at/timeline/stations/statuses/aging/fees. Area reconciliation tự áp attention. Tổng hợp toàn bộ bộ lọc; VND luôn chuỗi nguyên. Không ghi chứng từ, sổ cái hoặc ví.
- Xác minh cập nhật: 346 test frontend đạt (14 ca kế toán); 44 test accountant/inventory backend đạt trên DB riêng 5436; lint/build/Ruff/mypy router đạt. Kiểm tra desktop 1366×960/mobile 390×960, lọc từ biểu đồ và quay lại chi tiết giữ tuổi chờ; không lỗi JS/tràn ngang. Khôi phục cuộn chờ cả biểu đồ tải xong.
- Review thực hiện inline theo impeccable; không phải đánh giá độc lập. Không thêm ảnh raster hoặc thư viện biểu đồ.
