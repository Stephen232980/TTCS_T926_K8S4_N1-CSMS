# T-81 / S-33 — Chốt phiên và xử lý bù

PR #115 giữ commit của thành viên, thêm merge từ develop và commit sửa backend.
Simulator chỉ gửi OCPP; bỏ dictionary, hóa đơn ngẫu nhiên và trạng thái paid giả.

## Luồng thực tế

- StopTransaction lưu phiên, meter và reply cache trong transaction OCPP.
- Sau commit và sau khi gửi CALLRESULT, transport đưa session ID vào hàng đợi có giới hạn 256. Hai worker gọi `chot_phien`; không chờ lập hóa đơn trong đường trả lời OCPP.
- `chot_phien(session_id)` mở transaction riêng và gọi `lap_hoa_don` của T-80. Hóa đơn và dòng hóa đơn commit cùng nhau; review_reasons cũng được lưu khi thiếu dữ liệu nghiệp vụ.
- FastAPI lifespan tự chạy scan ngay lúc khởi động, sau đó mỗi 60 giây. Có thể cấu hình `CHARGING_CLOSURE_SCAN_INTERVAL_SECONDS` (số nguyên dương).
- Scan đọc DB: ended_at khác NULL và settlement_completed_at bằng NULL. Bao gồm phiên đóng thủ công và phiên đã có hóa đơn; không dùng điều kiện thiếu hóa đơn.
- Phân trang theo ID, từng phiên có transaction riêng, FOR UPDATE SKIP LOCKED bỏ qua phiên đang khóa để lần sau thử lại. Khóa của T-80 và unique invoice/session ngăn tạo trùng giữa các worker/process.
- Hàng đợi đầy, mất kết nối khi gửi reply hoặc tiến trình dừng sau commit đều được scan phục hồi từ DB. Không có trạng thái hoàn tất giả. Lỗi một phiên không dừng cả batch; log chỉ chứa session ID.

## Ranh giới nghiệm thu

T-81 tạo hóa đơn, chưa trừ ví hoặc đặt settlement_completed_at/settlement_reason.
T-102 chịu trách nhiệm giao dịch settlement và xử lý hóa đơn cũ. Vì vậy trước T-102,
scan vẫn chọn lại hóa đơn đã có và trả cùng snapshot; đó là chủ ý theo refinement.
T-77/T-78 của S-32 được nghiệm thu riêng. Phí chiếm trụ tuân theo phạm vi dữ liệu
T-80 hiện có; chưa chứng minh thu phí từ Stop đến khi rút cáp.

Không thêm migration, endpoint hay dependency. Job chạy cùng application lifespan;
khi shutdown, task bị hủy và transaction đang chạy rollback để scan lần sau xử lý.

## Kiểm chứng

`tests/test_t81_closure.py` dùng PostgreSQL đã migrate, transaction đã commit và
connection độc lập: chạy đồng thời, không trùng hóa đơn/dòng, khóa bận, phân trang,
phiên có hóa đơn/đóng thủ công, review, rollback lỗi sau flush, scan phục hồi phiên
Stop khi không có queue hoặc gửi reply lỗi, Stop replay, CALLERROR và worker failure.
Test tích hợp Stop kiểm tra commit nhìn thấy trước reply; cố tình chặn billing để
chứng minh reply hoàn thành trước hóa đơn. Đây là mô phỏng mất queue/worker, không
phải bằng chứng đã kill tiến trình hoặc nghiệm thu trên staging.
