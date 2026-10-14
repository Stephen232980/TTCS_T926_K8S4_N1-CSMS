# Rà soát giao diện kế toán — 13/10/2026

Phạm vi: mã local trên `fix/-sua-giao-dien`, sau PR #143 và commit vận hành `1d2dc10`. Kiểm tra read-only trên `127.0.0.1:5186`, tài khoản kế toán local, desktop 1366×844 và mobile 390×844. Không kiểm thử staging, không tạo hóa đơn điện tử/kỳ đối soát, không sửa giao diện.

## Kết luận về tính nhất quán

Chưa đạt về cách trình bày khả năng sản phẩm: menu hứa hẹn doanh thu, xuất hóa đơn và đối soát nhưng phần phiên chỉ có thông tin kỹ thuật, hai màn hình còn lại là placeholder với nút được bật nhưng không có handler. Đây không phải kết luận rằng backend hoàn toàn thiếu các nghiệp vụ này; cần đối chiếu phạm vi sprint và hợp đồng API trước khi triển khai chức năng.

Detector Impeccable scope layout/type trên accountant và ChargingSessionsPage trả `[]`. Các vấn đề bên dưới được xác nhận từ mã, nội dung và tương tác trình duyệt; detector không phát hiện không đồng nghĩa UI đã hoàn thiện.

## Điểm sức khỏe tham khảo

| Chiều đánh giá | Điểm /4 | Bằng chứng / giới hạn |
|---|---:|---|
| Accessibility | 3 | Có landmark, heading, label và aria-expanded cho vùng chi tiết. Một số control nhỏ trên mobile; chưa đo đủ tương phản hoặc kiểm toán WCAG đầy đủ. |
| Performance | 2 | Danh sách polling 1 giây; mở biểu đồ có thêm polling số đo. Chưa đo tải khi nhiều người dùng, không kết luận đang chậm. |
| Responsive | 3 | Không tràn ngang ở hai viewport đã thử; phần sidebar mobile chiếm nhiều diện tích. |
| Theming | 3 | Giữ hệ màu teal/Segoe UI, token cơ bản; CSS accountant chứa nhiều selector của các màn hình không được render. |
| Implementation integrity | 2 | Nút không hoạt động, placeholder bị trình bày như kết quả dữ liệu rỗng và tên menu chưa khớp chức năng. |
| Tổng | 13/20 | Cần hoàn thiện tính trung thực của trạng thái và luồng tra cứu trước khi chốt UI. |

Điểm là đánh giá giới hạn trong phạm vi trên, không phải chứng nhận accessibility hoặc nghiệm thu nghiệp vụ kế toán.

## Phát hiện

| ID / mức | Nơi / bằng chứng | Ảnh hưởng | Hướng xử lý |
|---|---|---|---|
| ACC-01 / P1 | AccountantWorkspace: hai button `Xuất hoá đơn mới`, `Tạo kỳ đối soát` không có onClick. Bấm trên cả hai viewport không thay đổi nội dung. Empty state cố định `Chưa có hoá đơn nào`, `Không có dữ liệu đối soát`. | Người dùng tưởng có thể thao tác hoặc hệ thống không có dữ liệu, trong khi frontend chưa tải dữ liệu. | Nếu ngoài sprint hiện tại: hiển thị “Chức năng chưa được triển khai”, bỏ nút giả hoặc vô hiệu kèm giải thích. Không suy ra hóa đơn điện tử là cùng nghiệp vụ với hóa đơn phí sạc đã có. `clarify/onboard`. |
| ACC-02 / P1 | Menu `Phiên sạc & Doanh thu`; ChargingSessionsPage chỉ tải `/accounting/charging/sessions` và số đo/sự kiện, không có số tiền, tổng doanh thu, invoice ID hay trạng thái quyết toán. | Kế toán không thể đối chiếu đã thu/chưa thu và dễ hiểu “Đã kết thúc” là đã thanh toán. | Đổi tên thành “Phiên sạc” trong phạm vi hiện có; bổ sung hướng dẫn trạng thái chỉ phản ánh sạc. Chỉ thêm doanh thu/quyết toán khi có hợp đồng API/phạm vi sprint được xác nhận. `clarify/shape`. |
| ACC-03 / P2 | Desktop: main rộng 1146px nhưng workspace khoảng 836px và còn padding trong; viewport đầu hiển thị khoảng 2 phiên đầy đủ. | Phải cuộn nhiều để so sánh 20 dòng/trang; khoảng trắng giữa hai bên lớn. | Dùng hàng/bảng danh sách gọn trong khung kế toán, ưu tiên mã phiên, trạm/trụ, thời gian, kWh, trạng thái. Chi tiết kỹ thuật mở khi cần. `layout/distill`. |
| ACC-04 / P2 | Chỉ có select trạng thái; local có 69 phiên, 20 phiên/trang. Không có tìm mã phiên/trạm, khoảng ngày. | Khó tìm giao dịch theo thông tin tài xế/chủ trạm cung cấp. | Xác nhận API hỗ trợ tìm kiếm/khoảng thời gian trước. Nếu chỉ lọc trên trang thì ghi rõ phạm vi, không trình bày như tìm toàn hệ thống. `shape/clarify`. |
| ACC-05 / P2 | Lịch sử và biểu đồ cùng mở inline bên trong một dòng; biến selected/historyId/page/state chỉ ở component. Chuyển tab làm remount (`key={area}`); URL không có mã phiên hay bộ lọc. | Mở chi tiết đẩy danh sách dài hơn; reload/chuyển tab mất ngữ cảnh, khó chia sẻ hoặc quay lại đúng phiên. | Có chi tiết rõ ràng và quay về danh sách giữ trang/lọc/vị trí; URL lưu mã phiên. Dùng mẫu đã áp dụng cho vận hành, không cấp quyền điều khiển cho kế toán. `harden/layout`. |
| ACC-06 / P2 | Ảnh mobile hóa đơn: sidebar/brand/nav/email chiếm khoảng 340px trên viewport cao 844px, có khoảng trống lớn trước footer. | Nội dung nghiệp vụ bị đẩy xuống dưới. | Thu gọn tài khoản, bỏ khoảng giãn dọc không cần thiết và ưu tiên nội dung; vẫn giữ đăng xuất dễ tìm. `adapt/layout`. |
| ACC-07 / P2 | ChargingSessionsPage: reviews không có mapping `invoice_missing_tariff`, fallback ra mã raw; mọi review reason đều dùng badge đỏ “Cần xem xét”, kể cả `manual_closure` hoặc ghi chú thiếu timestamp khi phiên đang mở. | Mã kỹ thuật khó hiểu, cảnh báo nhiều và không nói rõ hành động của kế toán; dễ lẫn việc cần vận hành với ghi chú lịch sử. | Dùng nhãn và mức độ cảnh báo chung đã có; diễn giải ảnh hưởng tài chính, chỉ hướng liên hệ bộ phận có quyền. Giữ nguyên review/audit nguồn. `clarify/harden`. |
| ACC-08 / P2 | Bảng số đo trong ChargingSessionsPage dùng raw `sample.unit` và `sample.location`; Percent/Hertz vẫn có thể hiển thị nguyên văn. MeterChart đã dùng nhãn Việt hóa chung. | Hai vùng hiển thị không thống nhất. | Dùng meterUnitLabel/meterLocationLabel đã có, giữ nguyên số đo nguồn Wh/W và giá trị phục vụ đối chiếu. `clarify`. |
| ACC-09 / P3 | Mobile: đăng xuất 32px; làm mới/phân trang 36px; select 38px. | Dễ bấm nhầm trên cảm ứng. | Nâng vùng chạm khoảng 44px, không nhất thiết tăng chữ. Đây là cải tiến usability, chưa kết luận vi phạm WCAG AA chỉ từ chiều cao. `adapt`. |

Tổng: 9 mục, P0=0, P1=2, P2=6, P3=1. P1 ở đây là sự khó hiểu/khả năng thao tác sai kỳ vọng, không phải xác nhận lỗi sổ cái hoặc backend thu tiền.

## Rủi ro kỹ thuật cần theo dõi

- ChargingSessionsPage polling danh sách mỗi giây khi tab hiển thị; biểu đồ tải thêm mẫu. Có guard tránh request chồng, AbortController và ngừng khi document.hidden. Cân nhắc SSE hoặc chu kỳ dài hơn khi làm màn hình tra cứu kế toán; chưa có benchmark để coi đây là sự cố hiệu năng.
- CSS accountant có nhiều phần sao chép từ giao diện quản trị không được dùng trong workspace hiện tại. Dọn riêng nếu cần, không đổi chức năng ngoài phạm vi.
- Sai khác `1,467 kWh` trên biểu đồ tích lũy và `0,467 kWh` năng lượng phiên là hai đại lượng khác nhau (công tơ và chênh lệch). Không “sửa” số liệu cho bằng nhau; nên giải thích nhãn khi cần.

## Phần đang ổn

- Không lỗi JavaScript hoặc document overflow tại hai viewport kiểm tra; các control chính không bị cắt ngang.
- Kế toán chỉ đọc: canManage/canClose=false, không có nút dừng trụ hoặc đóng hồ sơ.
- Lịch sử, số đo và biểu đồ dùng API accounting, có trạng thái tải/lỗi và thời điểm cập nhật.
- Biểu đồ và bảng kỹ thuật không tải trước khi người dùng chọn; thông tin kỹ thuật đã có vùng thu gọn.

## Thứ tự đề xuất

1. Sửa ngay nhãn menu, placeholder/nút chưa hoạt động, cảnh báo và nhãn số đo (ACC-01/02/07/08).
2. Làm gọn danh sách, điều hướng chi tiết và mobile (ACC-03/05/06/09).
3. Đối chiếu sprint/API cho tìm kiếm toàn phạm vi, doanh thu, hóa đơn điện tử và đối soát; không xây nút giả trong khi chờ (ACC-04 và phần nghiệp vụ của ACC-01/02).

Bằng chứng: `.local/accountant-audit-qa.cjs`, ảnh `.local/accountant-audit/1366-*.png` và `390-*.png`. Chưa sửa hoặc commit mã giao diện kế toán.
