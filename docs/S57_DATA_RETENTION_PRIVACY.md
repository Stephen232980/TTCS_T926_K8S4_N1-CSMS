# S-57: tiếp nhận yêu cầu dữ liệu cá nhân và lưu trữ an toàn

## Trạng thái bàn giao

**Not Done cho toàn bộ S-57.** PR cung cấp tiếp nhận/xem/duyệt yêu cầu bền vững,
legal hold, inventory ngưỡng lưu trữ và worker. Chưa triển khai thực thi xóa/ẩn danh,
phân tách PII, giới hạn truy cập chứng từ theo policy hoặc tombstone khi restore.
Không coi đổi email, giữ nguyên driver ID hay một receipt là hoàn thành ẩn danh.

Commit gốc của DIOVN được giữ nguyên trong lịch sử; bản sửa tiếp nối dùng lại module,
router, giao diện quản trị, policy inventory và worker của thành viên.

## Luồng hiện tại

1. Driver nhập mật khẩu hiện tại tại mục **Dữ liệu cá nhân**. API kiểm tra lại mật khẩu
   trên user được khóa `FOR UPDATE`, tính số lần sai và áp dụng thời gian khóa hiện có.
2. `POST /api/v1/driver/privacy/anonymize-request` trả **202 pending** với receipt ID.
   Không thay email, thu hồi role/session/card hoặc thay đổi tiền/lịch sử.
   Khóa user và unique partial index đảm bảo một request pending/approved cho mỗi user.
   Gửi lại trả receipt đang active, kể cả sau khởi động lại ứng dụng.
3. Driver xem tối đa 100 yêu cầu gần nhất của chính mình tại
   `GET /api/v1/driver/privacy/requests`; không nhận user ID từ client.
4. Admin xem `GET /api/v1/admin/privacy/requests`, duyệt/từ chối tại
   `POST /api/v1/admin/privacy/requests/{id}/decision` với `decision`, `reason`,
   `policy_version` bắt buộc. Không tự duyệt, không ghi đè quyết định cũ.
   Decision và audit commit trong cùng transaction; rollback khi lỗi.
5. Receipt phân biệt `status` của quyết định và `execution_status=blocked`.
   `approved` chỉ là duyệt yêu cầu, không xác nhận policy đã đủ để xóa.
   Admin không thể nhập policy_version để mở khóa executor.
6. Endpoint cũ `POST /admin/privacy/anonymize/{user_id}` trả **409**
   `privacy_execution_unavailable` trước mọi thay đổi. Không có cờ bỏ qua.

Mọi route privacy có `Cache-Control: no-store`, RBAC trong route inventory.
Mật khẩu dùng `SecretStr`, không ghi vào DB, audit, receipt hoặc local/session storage.

## Kiểm tra nghĩa vụ và giới hạn

Receipt tính lại khi đọc/duyệt: phiên chưa kết thúc/chưa quyết toán, chưa xác nhận rút cáp,
legal hold, booking đang giữ hoặc fee pending/review và số dư ví.
Số dư dương báo `refund_required`; số dư âm báo `debt_resolution_required`; số dư 0
chỉ vượt điều kiện số dư. Không ghi đè balance, không tự hoàn tiền ngân hàng.

Đây là thông tin phục vụ xem xét, **không phải authorization cho execution**.
Khi bổ sung executor phải kiểm tra lại toàn bộ gate ngay trong transaction thực thi,
phối hợp khóa với charging/reservation/wallet/legal-hold writers. Hiện executor bị chặn
vô điều kiện nên một thay đổi đồng thời không thể dẫn tới xóa nhầm.
Tranh chấp và nghĩa vụ kỳ kế toán chưa có nguồn clearance tích hợp; luôn hiển thị blocker.

## Cleanup kỹ thuật

Các ngưỡng Settings ban đầu chỉ phục vụ inventory/dry-run, không phải thời hạn pháp lý
đã phê duyệt. Các số đếm theo tuổi là ứng viên để xem xét, không có quyền xóa.
`cleanup_enabled=false`, UI ẩn khả năng thực thi bằng nút disabled và báo lý do.
Cả gọi tay và worker trả `status=blocked`, `blocked_reason=retention_policy_unavailable`,
`total_deleted=0`, ghi audit `system.retention_cleanup_blocked`.

`charging_pending_messages` luôn có eligible_count=0; không suy luận mồ côi từ tuổi.
Mọi bảng được giữ nguyên tới khi có approved data-class policy, orphan/terminal predicate,
liên hệ legal hold/hồ sơ mở, batch checkpoint và cơ chế phục hồi phù hợp.
Worker/lifecycle của thành viên vẫn hoạt động, xử lý hủy task và lỗi DB như trước.

## Inventory cần chốt trước execution

| Data class / đường liên kết | Trạng thái hiện tại | Quyết định phải được phê duyệt |
| --- | --- | --- |
| users, password, sessions, user_roles | Giữ nguyên khi gửi/duyệt | Tách subject/PII; revoke và redact có checkpoint |
| charging_cards, driver virtual tag/start request | Giữ nguyên, chưa tuyên bố đã revoke | Revoke toàn bộ tag/card/session; xử lý truy lại qua tag/hash |
| charging_sessions, meter/events, connector/charge point | FK và lịch sử còn nguyên | Không cho ID/email cũ dẫn tới trạm/thời điểm qua đường vận hành |
| reservations và fee evidence | Giữ nguyên | Chặn trạng thái mở/uncertain/phí chưa xử lý; giữ nghĩa vụ cần đối soát |
| wallets, wallet_ledger, topups, gateway refs | Giữ nguyên tiền và liên kết | Refund/debt theo quy trình có chứng từ; retain-restricted theo policy |
| invoices, tariff snapshots, totals, shares/period statements | Giữ nguyên | Giữ invariant tiền/kWh/tỷ lệ/tổng kỳ; tách nhận dạng và quyền truy cập |
| control.actor_email / JSON, account_audits, audit/IP | Chưa redaction | Inventory nested payload; privileged allowlist có audit |
| admin/accountant/owner reports, exports, file/log | Chưa giới hạn theo retention policy | Kiểm thử truy lại từng role và DB role được phép |
| backup/restore | Chưa tombstone | Lưu dấu xử lý, replay trước mở traffic; không hồi sinh PII |

Không cascade-delete chứng từ, không tắt trigger bất biến, không cấp app role quyền bypass.
Không coi stable pseudonym hoặc email đổi tên là ẩn danh không thể đảo.
Không áp dụng redaction dữ liệu cũ khi chưa có migration/allowlist/policy và kiểm thử phù hợp.

## Migration và kiểm thử

Migration `h170026a2026` sau `g210021a2026` (merge head `k170027a2026` nối với develop `j240024a2026`) tạo `privacy_requests`, các FK RESTRICT,
check constraint quyết định và unique partial index. Downgrade chỉ bỏ bảng yêu cầu;
**phải xuất/bảo toàn yêu cầu trước rollback production**. Không chạy downgrade production
như một cách hoàn tác xử lý dữ liệu. Round-trip chỉ xác minh trên DB dùng riêng.

| Nhóm comment PR | Bản sửa / bằng chứng | Khoảng trống |
| --- | --- | --- |
| 1: request/approval | Receipt + reauth + own read + decision + audit; PostgreSQL concurrent intake/rollback/restart by new session | Chưa checkpoint execution |
| 2: nghĩa vụ | Committed PostgreSQL +1.000.000 / -5.000 / 0; balance/ledger giữ nguyên; hold sau approval được đọc lại; cáp/settlement/booking/fee và pending cũ | Chưa clearance dispute/period; chưa concurrent execution vì executor bị chặn |
| 3: nối lại danh tính | Legacy execution fail-closed; UI không còn báo anonymized thành công | Chưa tách PII/migration redaction hoặc revoke sau execution |
| 4: bảo toàn và hạn chế | Không sửa dữ liệu tài chính; inventory/giới hạn hiển thị rõ | Chưa restriction reports, invariant toàn bộ invoice/kWh/period hoặc backup replay |
| 5: cleanup | Không DELETE khi policy chưa có; pending giữ nguyên; response/audit blocked | Chưa hold-aware approved batch cleanup |
| 6: CI và DB | Lint effect không setState đồng bộ; tests thực DB và frontend; migration round-trip | CI của commit mới phải được kiểm tra riêng; local không chứng minh staging |

Chạy focused tests bằng `pytest tests/test_privacy_schemas.py tests/test_privacy_service.py
 tests/test_privacy_router.py tests/test_privacy_worker.py tests/test_privacy_postgres.py
 tests/test_endpoint_policy_inventory.py tests/test_charge_points_migration.py` trên PostgreSQL
**dùng riêng** đã chạy `alembic upgrade head`. Tests PostgreSQL tạo dữ liệu đã commit để
kiểm tra từ session khác; không được trỏ vào DB dùng chung/staging.

Frontend: `npm run lint`, `npm test`, `npm run build`. Các test gửi/xem request, reload,
review bắt buộc reason/policy và UI execution blocked không thay thế nghiệm thu staging,
phân quyền truy lại toàn diện hoặc khả năng ẩn danh đã hoàn thành.
