# S-57 — nghiệm thu theo AC gốc

## Phạm vi

Nguồn phạm vi: Backlog CSMS.xlsx, sheet Backlog CSMS, dòng 59, L59/N59.
Theo xác nhận của chủ dự án trong phiên triển khai, chỉ lấy AC gốc làm điều kiện hoàn thành:
sau khi duyệt không tra lại tài xế đã sạc ở đâu/lúc nào qua tài khoản gốc; phiên và hóa đơn
được gỡ định danh thay vì xóa; doanh thu tổng hợp/sổ cái nguyên vẹn; ví dương phải xử lý hoàn tiền trước.
Policy phạm vi dữ liệu `CSMS-PRIVACY-2026-01` do chủ dự án ủy quyền lựa chọn.

Cleanup telemetry/log, cơ chế backup/tombstone và dịch vụ hoàn tiền ngân hàng không thuộc
phạm vi triển khai lần này, không thêm làm AC hoặc điều kiện merge. Cleanup kỹ thuật
ban đầu của thành viên vẫn bị chặn; không xóa pending OCPP chỉ theo tuổi.

## Hành vi

1. Driver nhập lại mật khẩu và gửi yêu cầu; nhận HTTP 202 + receipt, xem được yêu cầu của mình.
   Gửi request không đổi dữ liệu. Row lock và unique index chặn nhiều request active cùng lúc.
2. Admin duyệt/từ chối có lý do và policy version. Duyệt tạo job trong cùng transaction/audit;
   worker chạy nền, không cần xác nhận hồ sơ backup/log/kỳ kế toán bổ sung.
3. Ngay trước từng bước, DB khóa user/wallet và kiểm tra lại số dư, phiên/cáp/settlement,
   start/booking/topup đang mở và legal hold. Không ghi số dư về 0, không tự tạo hoàn tiền.
   Ví dương hoặc âm giữ nguyên tài khoản và tiền, job chuyển needs_review với mã lý do.
4. Checkpoint 1 thu hồi phiên và thẻ, đóng băng tài khoản. DB trigger chặn tạo hoạt động mới
   trên driver đã freeze; checkpoint được commit riêng để phục hồi sau worker restart.
5. Checkpoint 2 thay driver/actor link bằng subject tài chính ngẫu nhiên, xử lý email, password,
   roles, virtual tag, session/card, account audit, control/audit JSON và tag tail của phiên.
   Hóa đơn, session, ledger, tiền, kWh, rate, timestamp và các tham chiếu tài chính giữ nguyên.
6. Checkpoint 3 xóa cầu nối tạm `original_user_id -> subject_id` trong schema private,
   ghi audit hoàn tất và báo completed. Receipt/audit công khai không chứa subject thay thế.
   Giữ nguyên user ID cũ cho receipt nhưng không còn FK từ ID đó sang lịch sử vận hành/tài chính.
7. Lỗi rollback bước đang chạy, giữ checkpoint; admin xem mã lỗi và thử lại sau khi giải quyết
   nghĩa vụ. Chạy lại job completed không tạo thêm bút toán hoặc sửa số tiền.

Không gọi cách đổi email nhưng giữ nguyên driver_id là đã hoàn thành ẩn danh.
Subject còn lại phục vụ bảo toàn liên kết chứng từ; không tuyên bố xóa toàn bộ dữ liệu hoặc
ẩn danh trước mọi nguồn dữ liệu bên ngoài hệ thống. DBA/WAL/backup thuộc phạm vi vận hành riêng.

## Dữ liệu giữ lại và migration

Policy không tự xóa hóa đơn/ledger; nhóm chứng từ tài chính giữ tối thiểu 10 năm và việc
hủy chứng từ sau thời hạn phải được xem xét riêng. Đây là lựa chọn bảo toàn của hệ thống,
không phải một engine xác định pháp luật cho mọi loại dữ liệu.
Tham chiếu: https://vanban.chinhphu.vn/default.aspx?docid=183198&pageid=27160.

Migration `l170028a2026` nối sau `k170027a2026`, tạo policy/job và schema cầu nối tạm.
Guard UPDATE các bảng bất biến chỉ cho phép cột định danh nằm trong allowlist, đúng job
đặc quyền đang processing. Thay đổi tiền/rate/time, DELETE và TRUNCATE vẫn bị chặn.
Không có cờ session của app để tự bỏ qua trigger. Schema private không cấp quyền PUBLIC.

Với deployment dùng migration owner làm runtime DB user, worker dùng kết nối hiện có.
Nếu deployment tách app role khỏi owner: DBA cấp USAGE schema privacy_private và quyền
thành viên `csms_privacy_executor` cho đúng runtime role. Không cấp SELECT cầu nối tạm.
Worker có thể tắt bằng `PRIVACY_WORKER_ENABLED=false`; mặc định bật, chu kỳ 10 giây.
Downgrade chỉ hỗ trợ trước khi job đã chạy: không thể dùng rollback schema để phục hồi PII.

## Ma trận AC gốc / bằng chứng

| AC | Bằng chứng triển khai/kiểm thử | Phạm vi kết luận |
| --- | --- | --- |
| Chỉ thực thi sau duyệt | Pending không mutation; approval tạo job; worker thực tế xử lý job từ approval | PostgreSQL committed state + worker integration |
| Không truy lịch sử qua tài xế cũ | Email/hash/tag bị xử lý; FK driver cũ không còn ở invoice/session/wallet/card/booking/start; cầu nối tạm bị xóa khi completed | PostgreSQL trực tiếp, app role không đọc schema private |
| Phiên/hóa đơn ẩn danh thay vì xóa | IDs và bản ghi tài chính vẫn có; chỉ thay liên kết định danh, tag tail | Committed DB trước/sau |
| Doanh thu/sổ cái nguyên | Tổng invoice, ledger và kWh không đổi; get_revenue_report thực tế trước/sau giống nhau | DB + báo cáo theo owner |
| Ví dương phải xử lý trước | +1.000.000đ bị chặn trước freeze, email/status/balance giữ nguyên; âm -5.000đ cũng bị chặn | Không triển khai hoàn tiền ngân hàng |

Các test bổ sung kiểm tra hold sau freeze, chạy lặp, role/trigger, lỗi/rollback của intake,
request đồng thời, cáp/settlement/booking và migration head. Local/CI không chứng minh deployment
staging hoặc thay đổi trạng thái Jira. Lịch sử commit gốc DIOVN được giữ nguyên.

## Chạy xác minh

Chỉ chạy trên PostgreSQL dùng riêng đã `alembic upgrade head`:

```text
pytest tests/test_privacy_execution.py tests/test_privacy_postgres.py tests/test_privacy_service.py tests/test_privacy_router.py tests/test_privacy_worker.py tests/test_privacy_schemas.py tests/test_endpoint_policy_inventory.py tests/test_charge_points_migration.py
ruff check .
ruff format --check .
mypy src
```

Frontend: lint, toàn bộ test và build. Tests thông thường tắt scheduler để tránh xử lý fixture
của test khác; test worker integration bật và gọi chính loop production.


## Xác nhận hoàn tiền bên ngoài trước khi thử lại (19/10/2026)

Admin dùng ô xác nhận ngay trong hồ sơ bị chặn bởi `refund_required`, không có
màn hình hoàn tiền riêng. Ô xác nhận nêu số tiền hiện tại; ghi chú là tùy chọn.
Đây là ghi nhận việc người vận hành đã hoàn tiền bên ngoài, không chuyển tiền.

API execute nhận `external_refund_confirmed=true` và `expected_balance_vnd`.
Máy chủ khóa hồ sơ/user/job/wallet, kiểm tra số dư dương đúng số admin đã thấy,
đối chiếu sổ cái rồi ghi adjustment âm toàn bộ số dư qua lệnh ví hiện có.
WalletAudit, ledger, audit xác nhận và enqueue được commit cùng giao dịch.
Nếu lỗi ghi nhật ký hoặc điều kiện chặn khác, giao dịch không trừ tiền.
Số dư âm tiếp tục yêu cầu xử lý nợ. Số dư thay đổi yêu cầu tải lại/xác nhận lại.

Gửi trùng đồng thời không tạo bút toán thứ hai. Job queued/processing/completed
trả lại trạng thái hiện có; worker vẫn kiểm tra đầy đủ trước từng checkpoint.
Chứng từ không chứa liên kết trực tiếp từ request ID đến wallet audit sau ẩn danh.
Không có migration hoặc thay đổi quyền DB; không gọi execute trên hồ sơ thật khi deploy.
