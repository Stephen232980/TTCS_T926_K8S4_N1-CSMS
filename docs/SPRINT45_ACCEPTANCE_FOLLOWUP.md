# Sprint 4–5 — bổ sung các điểm rà soát

Phạm vi: F01–F06 trong báo cáo rà soát 12/10/2026, tiếp nối các PR đã merge.
Không thay đổi schema, công thức tính tiền, settlement hay dữ liệu lịch sử.

| Phát hiện | Triển khai | Kiểm chứng |
|---|---|---|
| F01 S-40 thiếu chi tiết nạp | API detail own-wallet, gateway join theo mã cổng+tài xế, nút Xem lần nạp | gateway/manual/legacy detail, quyền, UI click/đóng |
| F02 selector tài xế/ví | trả 403 cho balance/list/detail | hai selector × hai route; không selector vẫn own-wallet |
| F03 phân trang | mặc định API/UI 50 | 120 dòng + chèn mới: 50/50/20, không trùng/sót |
| F04 menu Biểu giá | dùng danh sách trạm và panel thật, cuộn tới panel khi chọn | menu -> chọn trạm -> panel/form, desktop/360px |
| F05 copy ví/return | bỏ ngưỡng giả 50.000đ; lỗi không hiện chờ IPN | wallet copy, terminal 404, timer cleanup, UI |
| F06 BIGINT | chuỗi decimal trên API ví, BigInt định dạng UI | 9007199254740993, số dư/nợ/ledger/detail, 360px |

F07 MeterValues: theo dõi bằng test hiện có, giữ nguyên ngưỡng 200ms; không
đổi thuật toán, nới test hoặc sửa CI để làm xanh. Cảnh báo chunk lớn hiện có
không phải thiếu chức năng của các story, không đổi bundle ngoài phạm vi.

Định dạng response tiền của API ví chuyển sang chuỗi; đã ghi trong API_CONTRACT.
Kiểm thử browser local dùng API fixtures được ghi rõ, không thay bằng chứng
staging. Sau merge/deploy, đọc lại ví/lần nạp/biểu giá và quyền trên staging;
không tạo lần nạp mới hoặc thanh toán lại chỉ để đọc UI.
