# T-63 — Ghi nhận thời điểm chiếm trụ

## Phạm vi

Nhánh `feature/S-28-t63-idle-since`, dựa trên `develop` sau PR #100.

- Thêm `charging_sessions.idle_since` và `connectors.last_status_notification_at`, đều nullable và có múi giờ.
- `SuspendedEV` có timestamp: ghi timestamp gốc cho phiên đang mở nếu `idle_since` chưa có. Những bản tin SuspendedEV tiếp theo không dịch chuyển mốc bắt đầu.
- `Charging` có timestamp mới hơn: xóa `idle_since`. Chuỗi SuspendedEV → Charging → SuspendedEV chỉ giữ khoảng chiếm trụ cuối.
- SuspendedEVSE, Finishing và các trạng thái khác không bắt đầu khoảng chiếm trụ. Finishing giữ mốc hiện có để phần tính phí sử dụng khi phiên kết thúc.
- Bỏ qua toàn bộ thay đổi trạng thái và ghi lỗi từ bản tin có timestamp nhỏ hơn hoặc bằng timestamp đã áp dụng cho cổng. Áp dụng bằng điều kiện trên UPDATE để không dùng quyết định từ dữ liệu đọc cũ.
- Không sửa phiên đã đóng, không ghi mốc trước thời điểm bắt đầu phiên, không sửa phiên của cổng khác hoặc từ connectorId=0.
- Timestamp thiếu: giữ hành vi cập nhật trạng thái hiển thị, nhưng không thay đổi idle_since hay mốc timestamp đã biết. Không lấy giờ máy chủ thay thế cho thời điểm tính phí. Trạm cần gửi timestamp để xác định đúng khoảng chiếm trụ.
- Giữ `status_updated_at` theo giờ máy chủ phục vụ giám sát; không dùng trường này để sắp thứ tự bản tin.

## Migration

Revision `c160016a2026` nối sau `b150015a2026`; không suy diễn hoặc backfill thời điểm chiếm trụ cho dữ liệu cũ. Downgrade xóa hai cột mới, vì vậy dữ liệu trong hai cột này không được giữ khi hạ cấp.

## Kiểm chứng local

- 20 ca T-63: chuỗi trạng thái, bản tin đến muộn/trùng với ID mới, bảo toàn mốc đầu, thiếu timestamp, phiên đóng, không có phiên, cổng khác, timestamp trước phiên, múi giờ +05:30 và microsecond.
- 117 ca đạt trong lần chạy kết hợp T-63 (18 ca ban đầu), OCPP monitoring/foundation, charging sessions/recovery và T-64. Hai ca bổ sung T-63 đã chạy đạt sau đó.
- PostgreSQL 16 riêng: upgrade toàn bộ chuỗi migration → downgrade về revision trước T-63 → upgrade lại; `alembic check` không phát hiện khác biệt schema.
- Ruff lint/format và mypy toàn bộ source đạt.

## Giới hạn

Đây là phần ghi nhận mốc thời gian. T-64 cung cấp hàm tính phí thuần; việc nối vào luồng hóa đơn/quyết toán vẫn thuộc task tương ứng. Chưa kiểm chứng với trụ thật hoặc staging. Database demo và cấu hình cổng local không thay đổi.
