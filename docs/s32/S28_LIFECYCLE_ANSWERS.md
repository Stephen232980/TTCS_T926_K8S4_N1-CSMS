# S-28: đáp án bổ sung cho vòng đời chiếm trụ

Quy tắc được Đào Minh Tâm đồng ý trong cuộc trao đổi ngày 11/10/2026.
Đây là phụ lục cho bộ T-77/T-78 đã xác nhận; không sửa đáp án hoặc nguồn gốc
của 22 ca cũ. Các đáp án bên dưới được viết cố định, không lấy kết quả chạy
hàm tính tiền để sinh đáp án. Phụ lục do Codex soạn, chưa thay thế nghiệm thu
của người review.

Tiền điện ở các ca thông thường: 1 kWh × 3.000 đồng/kWh = 3.000 đồng.
Phí chiếm trụ: 200 đồng/phút, ân hạn 5 phút, trừ ân hạn và làm tròn lên
một lần trên khoảng liên tục. Các mốc dưới đây là giờ địa phương của trạm.

| Ca | Diễn biến | Đáp án chiếm trụ | Tổng cuối |
| --- | --- | --- | --- |
| LC-01 | SuspendedEV 10:00; StopTransaction 10:02; Finishing 10:03; rút súng 10:12 | 12 − 5 = 7 phút; 7 × 200 = 1.400 | 4.400 |
| LC-02 | Finishing đến trước bản tin StopTransaction, nhưng mốc nguồn vẫn như LC-01 | Không đổi mốc; 1.400 | 4.400 |
| LC-03 | Available đến trước bản tin StopTransaction; sau đó nhận đủ mốc LC-01 | Chưa có số đo cuối thì chờ xử lý; đủ dữ liệu thì 1.400 | 4.400 |
| LC-04 | Stop trước; sau đó Finishing hoặc SuspendedEV liên tục 4 phút 59 giây | 0 | 3.000 |
| LC-05 | Khoảng chiếm trụ đúng 5 phút | 0 | 3.000 |
| LC-06 | Khoảng chiếm trụ 5 phút 1 giây | ceil(1/60) = 1 phút; 200 | 3.200 |
| LC-07 | Khoảng chiếm trụ 6 phút | 1 phút; 200 | 3.200 |
| LC-08 | Khoảng chiếm trụ 6 phút 1 giây | ceil(61/60) = 2 phút; 400 | 3.400 |
| LC-09 | SuspendedEV hoặc Finishing rồi Charging trước khi dừng; sau đó có khoảng cuối như LC-01 | Khoảng đầu bị hủy tính phí nhưng giữ lịch sử; khoảng cuối 1.400 | 4.400 |
| LC-10 | Dừng sạc 23:30; Finishing 23:59; rút súng 00:05:20; ngày mới 500 đồng/phút | Hết ân hạn 00:04; ceil(80/60) = 2 phút; 1.000 | 4.000 |
| LC-11 | StopTransaction có reason EVDisconnected, khoảng chiếm trụ 12 phút | Có bằng chứng ngắt xe; 7 × 200 = 1.400 | 4.400 |
| LC-12 | Không có khoảng chiếm trụ; dừng sạc rồi xác nhận rút súng | 0 | 3.000 |
| LC-13 | Chỉ SuspendedEV, chưa có bằng chứng kết thúc giao dịch | Chưa xác nhận khoản phí | Không có hóa đơn cuối |
| LC-14 | Chỉ StopTransaction; chưa xác nhận rút súng | Tiếp tục chờ | Không có hóa đơn cuối |
| LC-15 | Available nhưng cấu hình chưa xác minh tín hiệu rút súng | Tiếp tục chờ | Không có hóa đơn cuối |
| LC-16 | Available trên đầu nối 0/khác/không đăng ký | Không giải phóng phiên này | Không có hóa đơn cuối |
| LC-17 | Bản tin cũ hoặc trùng mốc | Không sửa mốc; không cấp lại ân hạn | Như LC-01 sau bản tin hợp lệ |
| LC-18 | Thiếu timestamp, mất liên lạc, lỗi trụ hoặc SuspendedEVSE giữa khoảng chiếm trụ | Cần đối chiếu; không thay timestamp bằng giờ máy chủ | Không có hóa đơn cuối |
| LC-19 | Người khác bắt đầu phiên mới trước khi có bằng chứng rút súng của phiên cũ | Phiên cũ cần đối chiếu; tín hiệu mới không gán ngược | Không có hóa đơn cuối cho phiên cũ |
| LC-20 | Charging sau StopTransaction | Dữ liệu mâu thuẫn, cần đối chiếu | Không có hóa đơn cuối |

Đối chiếu tự động: `tests/test_s28_occupation_lifecycle.py`.
Phục hồi sau khởi động lại: `tests/test_t81_closure.py`.
Giữ hóa đơn cũ khi nâng/hạ/nâng migration: `tests/test_s28_lifecycle_migration.py`.
