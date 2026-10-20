# S-55 — Kỳ đối soát tháng được chốt và mở lại theo revision

## Database và model

- `period_closes` là trạng thái hiện tại của một tháng dương lịch, duy nhất theo
  `period_start`. `status` và `revision` chỉ được chuyển qua các bước
  `closed → open → closed`; trigger từ chối xóa kỳ hoặc thay đổi định danh.
- `period_snapshots` lưu payload JSONB bất biến cho mỗi lần chốt: khoảng ngày
  local, múi giờ, cutoff, S-53 run/hash/tổng hợp và toàn bộ kết quả ngày/trạm/
  hợp đồng từ S-54. `snapshot_hash` là SHA-256 của JSON chuẩn hóa.
- `period_revisions` là sự kiện append-only khi mở lại, gồm revision mới, lý do,
  actor và snapshot trước đó. Dữ liệu snapshot cũ không bị cập nhật/xóa.
- Migration `o170031a2026` tiếp nối migration S-54 `n170030a2026`. Downgrade bị
  từ chối nếu đã có lịch sử kỳ; cần kế hoạch phục hồi tường minh thay vì xóa
  chứng cứ tài chính.

## Nghiệp vụ

`month_date_range(period_start)` chỉ chấp nhận ngày đầu tháng và trả ngày cuối
tháng lịch. `close_period(...)` yêu cầu tháng đã kết thúc theo
`Asia/Ho_Chi_Minh`, S-53 run `completed` cho toàn tháng/toàn hệ thống, cutoff sau
ranh giới tháng, không có mismatch/thiếu dữ liệu/cảnh báo critical hoặc warning.
Sau đó hàm gọi trực tiếp `calculate_partner_revenue_share` của S-54 trên cùng
khoảng ngày và chụp kết quả đã settlement (điện + idle, theo hợp đồng hiệu lực).
Kết quả S-54 không có hợp đồng vẫn được giữ rõ trong `unallocated_vnd`.

`reopen_period(...)` yêu cầu kỳ đang `closed` và lý do không rỗng. Hàm thêm một
`PeriodRevision` rồi chỉ cập nhật trạng thái/version hiện tại của `PeriodClose`;
không sửa invoice, invoice lines, ledger, hợp đồng hoặc snapshot cũ. Lần chốt
tiếp theo cần một S-53 run mới và tạo snapshot revision mới.

Các hàm service chỉ flush trong transaction của caller; caller commit khi thành
công. Advisory transaction lock theo tháng tuần tự hóa close/reopen cùng kỳ.
S-55 không thay đổi luồng append-only hiện có của hóa đơn, ledger hay audit.
