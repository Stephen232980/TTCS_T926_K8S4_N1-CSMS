# Kế hoạch chức năng Sprint 2–3

Quyết định ngày 02/10/2026: triển khai theo chức năng, không giao tuần tự từng story. Backlog gốc vẫn giữ vai trò đối chiếu AC/NFR; Jira ghi tiến độ, Git/PR chứng minh code. Chức năng hoàn thành phải có giao diện dùng API thật, dữ liệu lưu thật và luồng demo. Không đánh dấu story Done khi thiếu bằng chứng AC/NFR.

| Nhóm | Story | Đầu ra |
| --- | --- | --- |
| Nền tảng OCPP | S-06, S-07, S-08, S-13, S-14 | Kết nối, đọc/ghi frame, BootNotification, thay socket, chống trùng bền vững; giao diện quan sát kết nối/khởi động thật |
| Giám sát | S-09, S-10, S-11, S-12 | Nhịp tim, đầu nối, lỗi, màn hình cập nhật, ngoại tuyến |
| Phiên sạc | S-15, S-17, S-18, S-19, S-20 | Xác thực, bắt đầu/kết thúc, số đo, kiểm tra số đo |
| Phục hồi | S-21, S-25 | Nối lại, tin muộn, phiên bất thường và đóng tay |
| Điều khiển | S-16, S-23, S-27 | Reset/dừng từ xa và nhật ký người thực hiện |
| Tài xế | S-22, S-24 | Theo dõi phiên thật và bắt đầu sạc từ ứng dụng |
| Kiểm thử tổng thể | S-26 | Trụ ảo nhiều kết nối, mất mạng và CI |

Phát triển DB/API/frontend của từng nhóm rồi kiểm thử tích hợp nhóm đó; kiểm tra chạy/migration/contract trong quá trình viết. Simulator tối thiểu có từ nhóm đầu, hoàn thiện S-26 cuối đợt. S-06 đã merge ở PR #35, commit 3e01d59; các story khác chưa được xác nhận Done.

## Điều chỉnh theo mentor

Người dùng xác nhận: bỏ ô nhập kinh độ/vĩ độ; chủ trạm chọn điểm trên bản đồ, dữ liệu vị trí vẫn lưu trong DB. Không đổi kiểu hoặc bỏ cột latitude/longitude; không cần migration.

Làm sớm phần bản đồ vị trí của S-47: tài xế xem trạm active, không archived, tìm tên/địa chỉ, bấm marker hoặc danh sách, mở vị trí ngoài; xử lý loading/empty/error/retry và màn hình nhỏ. Đây chưa phải toàn bộ S-47: chưa thêm giá, đầu nối rảnh, sắp khoảng cách hoặc đặt chỗ.

| Yêu cầu | Backend | Frontend | Kiểm chứng |
| --- | --- | --- | --- |
| Bỏ nhập tọa độ | Giữ contract tạo/sửa và ràng buộc vị trí | Chọn điểm, chọn tâm bằng bàn phím; bỏ tọa độ thô khỏi danh sách/chi tiết | Test form gửi tọa độ điểm đã chọn; thiếu vị trí bị chặn |
| Bản đồ tài xế | GET /api/v1/driver/stations, driver-only; lọc active/non-archived ở SQL; schema không có owner_id | Leaflet, điểm trạm từ API, tìm kiếm và phân trang | Test API lọc/phân quyền; test tải/tìm/retry; QA desktop/mobile |
| API quản lý giữ phạm vi | Không cấp driver quyền API quản lý | Không hiện tạo/sửa cho driver | Test driver gọi /api/v1/stations trả 403 |

Nguồn tile mặc định: OpenStreetMap, có attribution; VITE_MAP_TILE_URL và VITE_MAP_ATTRIBUTION cho đổi nhà cung cấp. Không tải hàng loạt tile. Vị trí người dùng chỉ được yêu cầu khi bấm định vị; không gửi vị trí lên API CSMS.

## Nhóm giám sát S-09–S-12

Nhóm 2 bổ sung Heartbeat, trạng thái/lỗi đầu nối, offline theo lần liên lạc cuối
và màn hình SSE tự nối lại. Xem [phạm vi, API và kiểm chứng](OCPP_MONITORING_DELIVERY.md).
Cần nâng migration a721093e4f62 trước khi chạy. Bằng chứng hiện là kiểm thử
cục bộ; trạng thái Jira/CI và nghiệm thu được kiểm tra riêng.

## Nhóm 3: phiên sạc OCPP

S-15, S-17, S-18, S-19, S-20 bổ sung xác thực thẻ, phiên sạc, số đo và kiểm tra dữ liệu; có màn hình quản lý phiên/thẻ/chờ đối chiếu dùng API thật. Nâng migration d830a62f194b trước khi chạy. Xem [Coverage Matrix, API, kiểm chứng và demo thủ công](OCPP_CHARGING_DELIVERY.md). Đối chiếu/xử lý pending, đóng tay và điều khiển từ xa thuộc các nhóm tiếp theo. Bằng chứng local không thay thế Jira/CI.


## Nhóm 4: phục hồi phiên sạc

S-21 và S-25 bổ sung giữ phiên khi nối lại, nhận tin/số đo muộn theo transactionId, đánh dấu bất thường khi offline quá ngưỡng (mặc định 6 giờ), đóng tay có lý do và lịch sử. Giao diện có bộ lọc bất thường, xác nhận đóng tay và quyền đọc cho kế toán. Nâng migration e41b9027c6a8 trước khi chạy. Xem [AC, API, cấu hình và kiểm thử thủ công](OCPP_RECOVERY_DELIVERY.md). Đóng tay hồ sơ không gửi lệnh dừng tới trụ; pending không khớp vẫn không tự gán phiên. Bằng chứng local không thay Jira/CI.
