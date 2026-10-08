# T-57 phần B — nối nhật ký nghiệp vụ

Nguồn phạm vi: T-57 Sprint 3 / S-27 trong backlog và quyết định của người
phụ trách S-27 ngày 08/10/2026. Baseline `origin/develop` là `1163a6e`, đã
merge T-57 A và T-88. Phần B dùng nền tảng chung, không thêm migration.

## Quyết định nghiệm thu đã chốt

Giả sử vận hành viên gửi Reset hoặc RemoteStopTransaction, khi hệ thống
tạo yêu cầu điều khiển, có đúng một dòng audit_logs ghi người, hành động,
trụ hoặc phiên, thời điểm và mã yêu cầu. Kết quả trụ trả về lấy từ
ocpp_control_results theo mã yêu cầu; không ghi dòng audit thứ hai.

Yêu cầu điều khiển và audit cùng commit trước khi gửi lệnh ra trụ. Offline
cũng là một yêu cầu được ghi nhận, có kết quả Offline và không gửi frame.
Lệnh chưa có kết quả vẫn có audit; timeout và kết quả muộn tiếp tục theo
cơ chế hiện có. Reset Accepted chỉ là trụ chấp nhận lệnh. Dừng từ xa
Accepted không tự đóng phiên, vẫn chờ StopTransaction thực tế.

## Tham chiếu và giao dịch

| Luồng | action | object_type / object_id | JSON tóm tắt | Nguồn chi tiết |
| --- | --- | --- | --- | --- |
| Reset | ocpp.reset | charge_point / UUID trụ | request_id | ocpp_control_requests và ocpp_control_results |
| Dừng từ xa | ocpp.remote_stop | charging_session / mã phiên | request_id | ocpp_control_requests và ocpp_control_results |
| Đóng tay bất thường | charging.manual_close | charging_session / mã phiên | event_id | charging_session_events |

Actor, permission và actor_roles được ghi ngoài JSON. Các route hiện có
truyền evidence đã được phân quyền vào service. Không sao chép email,
mã thẻ, payload hay lý do tự do vào JSON audit. Lý do đóng tay, số đo và
chi tiết vẫn ở bản ghi sự kiện phiên như trước.

execute_command ghi audit trong giao dịch tạo ControlRequest, sau nhánh
kiểm mã yêu cầu đã tồn tại. Replay cùng mã không tạo audit hoặc gửi thêm;
cùng mã nhưng khác hành động/đích/payload trả 409. Lệnh mới có mã mới ghi
dòng mới. Giao dịch nhận kết quả chỉ ghi ControlResult.

manual_close ghi cập nhật phiên, sự kiện và audit trong cùng savepoint
của giao dịch người gọi, không commit. Lỗi sau khi flush sự kiện hoặc audit
đều rollback toàn bộ việc đóng tay. Phiên đã đóng không ghi thêm audit.

Các bản ghi nghiệp vụ cũ và API/giao diện nhật ký điều khiển tiếp tục đọc
nguồn chi tiết và join kết quả như trước. Không tạo audit bù cho lịch sử
cũ. Trang tra nhật ký chung T-58 và các thay đổi T-87 ngoài phạm vi.

## Ma trận kiểm chứng

| Yêu cầu | Kiểm chứng |
| --- | --- |
| Reset và dừng tạo đúng hai dòng | Hai lệnh, replay cả hai, join kết quả, số frame đúng hai |
| Ghi trước khi gửi | Kiểm bản ghi yêu cầu và audit tại thời điểm gọi send_command |
| Không gửi khi audit lỗi | Hai loại lệnh, lỗi trước/sau flush audit; không request/result/audit hoặc frame |
| Có dấu vết khi không phản hồi | Offline, Timeout, Rejected vẫn một audit |
| Lỗi lưu kết quả không mất hành động | Yêu cầu/audit còn; replay Pending không gửi lại; deadline ghi Timeout, không thêm audit |
| Đóng tay một audit có tham chiếu | Join event_id, actor và permission/roles; lý do chỉ ở sự kiện |
| Đóng tay rollback | Lỗi sau flush event/audit và rollback giao dịch người gọi |
| Giữ hành vi Sprint 3 | Bộ control/recovery cũ; đóng tay đồng thời StopTransaction thật |
| Giữ quyền và bất biến | Test endpoint snapshot và nền tảng T-57 A hiện có |

Test đồng thời đóng tay/dừng thật dùng database tạm có tên ngẫu nhiên,
áp dụng toàn bộ migration và hai connection riêng. Database đó được bỏ
sau test; không xoá audit hoặc tắt trigger để dọn dữ liệu.

Kiểm chứng local và CI/review được báo riêng; chưa thay trạng thái Jira
hay triển khai ứng dụng đang chạy.

## Kết quả local ngày 08/10/2026

- 14 ca kiểm thử tích hợp audit mới đạt trong bộ hồi quy, cùng các test
  control/recovery hiện có và test nền tảng dùng runtime role riêng.
- Bộ hồi quy theo cấu hình CI: 751 passed, 2 deselected (hai ca latency
  được tách sang gate riêng), 4 cảnh báo deprecation có sẵn.
- Ruff toàn repository đạt; format check 251 file đạt; mypy 88 file
  source đạt; git diff check đạt.
- Upgrade database PostgreSQL 16 rỗng tới head đạt, một head
  b150015a2026 kế thừa phần A; phần B không sửa schema/migration.
- Kiểm chứng dùng database thử riêng. Nhánh triển khai:
  feature/S-27-T-57-audit-integration. Kết quả CI và review của PR cần
  được xác nhận riêng với kết quả local ở trên.
