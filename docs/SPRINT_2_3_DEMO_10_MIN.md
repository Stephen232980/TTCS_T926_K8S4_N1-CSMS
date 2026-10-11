# Demo Sprint 2–3 trong 10 phút

Phạm vi theo Backlog CSMS.xlsx: Sprint 2 S-06–S-16; Sprint 3 S-17–S-27. Chọn luồng chính để chứng minh chức năng qua giao diện; không tuyên bố đã demo đầy đủ mọi AC/NFR trong 10 phút.

Không trình bày tạo tài khoản, tạo/sửa trạm, tạo trụ/đầu nối, bản đồ tìm trạm, sức khỏe hệ thống hoặc kế toán. Những phần này chuẩn bị trước, không chiếm thời gian trình bày.

## Chuẩn bị

- Backend, frontend và simulator chạy sẵn; trạm active, trụ online, có đầu nối Available và một đầu nối lỗi để quan sát.
- Tài xế chưa có phiên mở/yêu cầu chờ. Chuẩn bị sẵn màn hình chọn đầu nối tại trạm; không demo thao tác tìm trên bản đồ.
- Dùng các phiên trình duyệt độc lập cho vận hành, tài xế, quản trị; đăng nhập trước để chuyển nhanh.
- Vận hành mở Giám sát trụ và chọn trụ sẽ demo. Chuẩn bị trụ online khác, không đang sạc, để gửi Reset.
- Quản trị mở Nhật ký thao tác, nguồn điều khiển OCPP; chuẩn bị mã trụ/email vận hành để lọc.
- Kiểm tra số đo đầy đủ và luồng Start/Stop trước buổi. Không dùng ID phiên cố định; ghi ID phiên mới khi bắt đầu.

## Kịch bản theo phút

| Thời gian | Vai trò / màn hình | Thao tác và nội dung nói | Story |
|---|---|---|---|
| 0:00–2:00 | Vận hành — **Giám sát trụ** | Giới thiệu trụ đã đăng ký kết nối và Boot hợp lệ; chỉ online, thời điểm liên lạc cuối, trạng thái từng đầu nối. Chọn đầu nối Faulted và chỉ mã lỗi. Gửi Reset Soft tới trụ riêng không đang sạc, xác nhận và xem kết quả. Nói rõ simulator chỉ trả lời Reset, chưa mô phỏng reboot vật lý. | S-06, S-08–S-11, S-16 |
| 2:00–3:30 | Tài xế — **Chọn đầu nối** | Vào trạm đã chuẩn bị; chỉ Available chọn được và đầu nối bận/lỗi bị chặn. Chọn đầu nối, xác nhận đã cắm súng, bấm bắt đầu một lần. Giải thích Accepted chỉ nhận yêu cầu; cần StartTransaction để có phiên thực. | S-24, S-17 |
| 3:30–4:30 | Tài xế — **Phiên hiện tại** | Chỉ đúng trạm/trụ/đầu nối, thời điểm bắt đầu, thời lượng và kWh. Chờ vài lần số đo để thấy tự cập nhật; ghi ID phiên nếu màn hình có, hoặc lấy ID từ vận hành ở bước tiếp theo. | S-22, S-19 |
| 4:30–7:30 | Vận hành — **Giám sát trụ → Phiên sạc / chi tiết phiên** | Quay lại trụ: đầu nối đã Charging mà không reload. Mở đúng phiên vừa tạo, chỉ công suất/nhiệt độ/điện áp/dòng điện, đổi đại lượng biểu đồ và xem bảng số đo. Bấm Dừng từ xa; chờ StopTransaction thực. Chỉ giờ kết thúc, kWh chốt và đầu nối trở lại Available. | S-10, S-11, S-17–S-19, S-23 |
| 7:30–8:00 | Tài xế — **Phiên hiện tại** | Quay lại xác nhận không còn phiên đang sạc. Nêu tài xế hiện chưa có nút dừng; trong demo vận hành kết thúc qua RemoteStop. | S-22, S-18 |
| 8:00–9:30 | Quản trị — **Nhật ký thao tác** | Lọc email vận hành và khoảng thời gian; mở đúng Reset và RemoteStop vừa gửi. Chỉ người thực hiện, mã trụ/phiên, thời gian và phản hồi. Không mở màn hình tài khoản hoặc sức khỏe hệ thống. | S-27 |
| 9:30–10:00 | Người trình bày — **Bằng chứng CI S-26 chuẩn bị sẵn** | Chiếu log/artifact của commit đang demo: 20/20 trụ được verifier kiểm chứng, replay/nối lại và kiểm tra dữ liệu phiên. Chỉ nói đạt nếu lượt CI đó đạt; không chạy Compose mới trong buổi. | S-26; bằng chứng kỹ thuật S-14, S-21 |

## Lời dẫn ngắn

1. “Đây là màn hình vận hành của Sprint 2: trạng thái trụ và từng đầu nối cập nhật từ OCPP, kèm liên lạc cuối và lỗi thiết bị.”
2. “Sang Sprint 3, tài xế bắt đầu trên đầu nối sẵn sàng. Hệ thống chỉ tạo phiên khi nhận StartTransaction từ trụ.”
3. “Trong phiên, số đo được lưu và cập nhật trên cả màn hình tài xế lẫn vận hành.”
4. “Vận hành gửi lệnh dừng; khi trụ gửi StopTransaction, hệ thống kết thúc phiên và chốt điện năng bằng hiệu công tơ cuối trừ đầu.”
5. “Quản trị tra được ai gửi lệnh và kết quả. Bộ kiểm chứng 20 trụ bổ sung bằng chứng cho mất mạng, nối lại và chống nhân đôi.”

## Phạm vi còn lại khi được hỏi

- S-07, S-13–S-15, S-20: chuẩn bị test/transcript về frame OCPP, thay socket, chống trùng, Authorize và số đo lỗi; không thêm màn hình ngoài luồng chính.
- S-12: nếu hỏi offline, giải thích quá hai chu kỳ heartbeat, không phải ngay khi Ctrl+C. Không chờ hơn hai phút trong lịch demo 10 phút.
- S-21: phần nối lại đơn giản/test được giải thích khi hỏi; không dừng bộ fleet giữa buổi vì cách dừng bình thường có thể đóng phiên.
- S-25: màn hình Cần xem xét và bộ lọc bất thường chỉ mở khi hỏi, dùng ca chuẩn bị riêng. Mặc định ngưỡng 6 giờ nên không tạo ca mới để chờ trong buổi.
- S-11: phạm vi chủ trạm chỉ thấy trụ của mình có thể nêu và dùng test làm bằng chứng; không dành một lượt đổi vai trò chủ trạm trong kịch bản chính.
- Các mục không trình bày vẫn thuộc Sprint 2–3; kịch bản chọn luồng chính theo giới hạn thời gian, không bỏ chúng khỏi backlog hoặc đánh dấu đã nghiệm thu.

Các NFR về 1/2 giây cập nhật, dưới 200ms phản hồi và CI dưới 5 phút cần bằng chứng đo/test tương ứng, không khẳng định chỉ từ việc xem giao diện.
