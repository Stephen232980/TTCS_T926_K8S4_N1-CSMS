# Rà soát giao diện vận hành — 13/10/2026

## Phạm vi và bằng chứng

Áp dụng impeccable audit, chế độ Operate, theo ngôn ngữ giao diện trong `frontend/src/features/operator/DESIGN.md`. Kiểm tra local frontend 5186/backend 8003 bằng tài khoản vận hành, ở 1366×768 và 390×844: giám sát trụ, chi tiết trụ/đầu nối, phiên sạc, danh sách cần xem xét và chi tiết phiên #170. Không sửa giao diện, không gửi lệnh trụ hoặc đóng phiên. Ảnh và script ở `.local/operator-audit` và `.local/operator-audit-qa.cjs`.

Không có lỗi JavaScript trong các lượt mở màn. Không có tràn ngang document, nhưng có control bị cắt bên trong vùng overflow ẩn. Detector layout trên operator và OwnerCharging trả `[]`; detector không phát hiện lỗi cắt control này. Chưa kiểm tra toàn bộ trường hợp lỗi mạng, chưa đo tải lớn và chưa nghiệm thu staging.

## Kết luận

Giao diện giữ được nhận diện CSMS và có dữ liệu vận hành thật, nhưng chưa đủ rõ để ưu tiên và xử lý ngoại lệ nhanh. Có **8 phát hiện: 1 P1, 6 P2, 1 P3; chưa xác nhận P0**.

Đánh giá sơ bộ: accessibility 2/4, performance 2/4, responsive 2/4, theming 3/4, implementation integrity 2/4; tổng **11/20**. Điểm performance phản ánh cấu trúc request quan sát trong mã, không phải kết quả đo hiệu năng. Điểm accessibility không phải chứng nhận WCAG; chưa thử toàn bộ bàn phím, trình đọc màn hình hoặc phóng chữ.

## Phát hiện

| Mã | Mức | Bằng chứng | Vấn đề và hướng xử lý |
|---|---|---|---|
| OPS-01 | P1 | Trình duyệt + CSS | Select “Trạm trong trang” ở màn Phiên sạc/Cần xem xét bị cắt trên mobile. Ở viewport 390px, mép phải control tới khoảng 424px. `document.scrollWidth` vẫn 390 nên kiểm tra tràn ngang document đơn thuần bỏ sót. Chuyển bộ lọc thành lưới một cột, cho input/select `min-width:0`, giới hạn chiều rộng và giữ label dễ đọc. |
| OPS-02 | P2 | Trình duyệt + `OwnerCharging.tsx`, danh sách ops | Danh sách Cần xem xét chỉ có badge chung; không hiển thị `review_reasons` trong từng thẻ. Local có 55 phiên trên 3 trang, phải mở từng phiên mới phân biệt thiếu biểu giá, số đo bất thường hoặc mất kết nối. Hiện lý do chính, trạng thái mở/đã kết thúc và ưu tiên dựa trên dữ liệu thật. |
| OPS-03 | P2 | Mã + chi tiết phiên | Ngoài `invoice_missing_tariff`, lý do kiểm tra vẫn được ghép bằng dấu phẩy, thiếu bước tiếp theo theo từng nguyên nhân. Tách lý do và hướng kiểm tra; chỉ nối thao tác mà API/quyền hiện có hỗ trợ. Không dựng nút đánh dấu đã xử lý khi chưa có nghiệp vụ backend. |
| OPS-04 | P2 | Trình duyệt, UI-DEMO-011 | Trụ ngoại tuyến vẫn hiện công suất 7,92kW, nhiệt độ 36,25°C từ lần nhận trước. Có thời điểm đo và trạng thái ngoại tuyến ở phía trên, nhưng ngay khu vực số đo chưa ghi “Số đo cuối nhận được”. Banner “Đang cập nhật trực tiếp” mô tả stream hệ thống, dễ bị hiểu là số đo trụ vẫn trực tiếp. Thêm nhãn cũ/ngoại tuyến cạnh số đo; không biến mất mạng thành số 0. |
| OPS-05 | P2 | `OperatorMonitoring.tsx:345`, `OwnerCharging.tsx:612` | Tìm kiếm và lọc trạm/trạng thái trụ chỉ trên trang hiện tại; nhóm “Cần chú ý” cũng chỉ sắp trong trang. Khi có nhiều trang, kết quả rỗng không có nghĩa toàn hệ thống không có trụ/phiên phù hợp. Có nhãn phạm vi là điểm tốt. Đề xuất lọc phía API toàn phạm vi; trước khi có API cần làm nổi phạm vi và hướng sang trang khác. |
| OPS-06 | P2 | `OperatorWorkspace.tsx:44`, trạng thái selectedId trong component | Điều hướng dùng `replaceState`; chọn trụ/phiên không đưa ID vào URL. Reload mất chi tiết, Back không tái hiện đầy đủ chuỗi giám sát → phiên → chi tiết. Đồng bộ area/ID vào URL, xử lý Back/Forward, giữ lọc và vị trí đọc. |
| OPS-07 | P2 | Trình duyệt + `OwnerCharging.tsx:661` | Phiên dài hiển thị 5754 hoặc 5996 phút, khó đọc nhanh. Bảng dùng Wh trong khi biểu đồ kWh; `Percent`, `Outlet` còn là nhãn kỹ thuật. Chuyển thời lượng sang ngày/giờ/phút; ghi rõ đơn vị gốc khi cần đối chiếu, Việt hóa tên vị trí/đơn vị và giữ nguyên giá trị nguồn. |
| OPS-08 | P3 | CSS operator mobile | Một số mục điều hướng mobile cao 36px, bố cục đầu trang/sidebar chiếm khoảng 177px ở 390×844. Nên giữ control cảm ứng khoảng 44px và giảm phần tài khoản/đăng xuất thường trực bằng mục thu gọn. Không tự quy control dưới 44px thành vi phạm WCAG 2.2 AA. |

## Rủi ro cần kiểm tra thêm

- ConnectorSession quét các trang phiên đang mở toàn hệ thống rồi tải mẫu mỗi 5 giây cho đầu nối được chọn. Với dữ liệu lớn, cần đo số request/thời gian; chưa khẳng định gây chậm ở local hiện tại.
- Chỉ có 100 mẫu gần nhất của mọi đại lượng trên mỗi trang; việc thiếu một đại lượng trong trang không chứng minh trụ chưa từng gửi. UI đã mô tả phạm vi mẫu ở chi tiết phiên; cần giữ sự giải thích này khi sửa.
- Đóng hồ sơ thủ công và dừng từ xa là hai thao tác khác nhau. Form đóng hồ sơ hiện đã giải thích không gửi lệnh dừng, có lý do và checkbox xác nhận; cần giữ nguyên.

## Điểm cần giữ

- Chọn trụ mở đầu nối 1; có thể chọn riêng đầu nối khác.
- Nhãn trạng thái đi kèm icon/chữ, số đo có thời gian nhận.
- Trên mobile, chi tiết trụ thay danh sách và có “Quay lại trụ”.
- Lệnh điều khiển có bước xác nhận; chưa coi Accepted là đã hoàn tất hành động vật lý.
- Thiếu dữ liệu hiện dấu —, không tự bù bằng số 0.

## Thứ tự đề xuất

Sửa OPS-01 trước, sau đó danh sách/chi tiết Cần xem xét (OPS-02/03/07), nhãn số đo cũ (OPS-04), điều hướng (OPS-06), cuối cùng phạm vi lọc/API và khoảng chạm (OPS-05/08).

## Kết quả sửa trên local

- Sửa bộ lọc mobile thành một cột, không còn control bị cắt ở viewport 390 px.
- Danh sách phiên hiện lý do cần xem xét và thời lượng ngày/giờ/phút; chi tiết có hướng dẫn theo nhóm lỗi, vẫn thu gọn mặc định.
- Số đo của trụ ngoại tuyến có cảnh báo dữ liệu lần cuối, không phải trực tiếp.
- URL giữ mã trụ/đầu nối và phiên; kiểm tra reload, quay về danh sách và Back thành công.
- Điều hướng mobile có vùng chạm tối thiểu 44 px; tài khoản có nút mở/đóng riêng.
- Bảng số đo dùng % và “Đầu nối”; giữ nguyên giá trị và đơn vị nguồn Wh/W.
- Bộ lọc và nhóm ưu tiên vẫn trong trang hiện tại theo API; bổ sung giải thích rõ phạm vi. Tìm kiếm toàn hệ thống cần backend hỗ trợ riêng.
- Kiểm tra desktop 1366×768/mobile 390×844 không tràn ngang, không lỗi JavaScript. Build, lint và test owner/operator qua. Không gửi lệnh điều khiển trụ khi kiểm tra.

## Hoàn thiện danh sách và số đo

- Giữ trang, bộ lọc trạng thái/trạm/từ khóa/lý do và vị trí cuộn khi mở phiên rồi quay lại; lưu ngữ cảnh vào history của tab để reload và Back vẫn khôi phục.
- Kiểm tra thực tế trang 2: desktop khôi phục scrollTop 798; mobile khôi phục cuộn shell 1497; không lỗi JavaScript.
- Phân biệt không có phiên cần xem xét với không có kết quả lọc, có hướng dẫn đổi/xóa lọc.
- Việt hóa vị trí số đo trong bảng/thông số/biểu đồ, Percent thành %, Hertz thành Hz; không đổi giá trị và đơn vị Wh/W của dữ liệu gốc.
- 27 kiểm thử operator/owner/MeterChart qua; build và lint các file sửa qua.
