# S-56 — Nhật ký ví

Nguồn: Backlog CSMS.xlsx, Backlog CSMS dòng 58; bản refine Sprint 6–8,
S-56/AC-1..6/NFR-1..2. Phạm vi giữ nguyên hai bảng `audit_logs` và
`wallet_audits`; không tạo kho nhật ký thứ ba và không thêm job purge.

## Hành vi

- Admin → **Nhật ký ví** (`#admin-wallet-audit`). Danh sách ngắn: thời gian,
  thao tác, số tiền. Mở dòng để xem actor, driver, ví, trước/sau, lý do và chứng từ.
- `GET /api/v1/admin/wallet-audit`: chỉ admin; lọc `driver_id`, `wallet_id`,
  `action`, `from_at`, `to_at`; mặc định 50 dòng, tối đa 50, mới nhất trước,
  phân trang ổn định bằng timestamp và UUID. Mốc thời gian phải có timezone;
  màn hình dùng giờ Việt Nam.
- Các thao tác: nạp tay, điều chỉnh, sửa số dư cache, mở khóa và quyết định phí
  đặt chỗ. Dòng phí do hệ thống chạy ghi actor null, giao diện hiển thị Hệ thống.
- Projection liên kết wallet_audits/ledger/reservation để trả chứng từ có thật,
  không trả nguyên JSON audit hoặc dữ liệu cá nhân từ đối tượng nghiệp vụ.
- Dữ liệu mới có `audit_version=1`, driver/wallet, lý do, snapshot trước/sau
  khi có; lịch sử cũ không bị cập nhật. Các trường thiếu hiển thị “Chưa ghi nhận”,
  cùng chú thích bản ghi cũ. Số dư khôi phục từ snapshot ledger hoặc wallet_audits
  nếu có, không lấy số dư ví hiện tại để mô tả quá khứ.

## Thay đổi hợp đồng

- `POST /api/v1/admin/wallets/{wallet_id}/unlock` bắt buộc body
  `{"reason":"Đã kiểm tra sổ cái"}`, lý do trim dài 1..500 ký tự.
- Nạp tay mới yêu cầu lý do nghiệp vụ `reason` 1..500 ký tự, độc lập mã phiếu và
  tham chiếu chứng từ. Giao diện bắt buộc nhập trước bước xác nhận.
- Model nạp tay vẫn nhận reason vắng để giải quyết replay của yêu cầu đã ghi
  trước phiên bản này. Không cho tạo khoản nạp mới thiếu reason. Replay so sánh
  cả lý do với bản gốc; đổi lý do nhưng dùng lại request_id trả 409.
- Khoản nạp cũ được UI giữ trong sessionStorage vẫn có thể retry chính xác body
  cũ. Không tự sinh lý do cho lịch sử.
- Client cũ tạo khoản nạp mới/mở khóa phải bổ sung reason. Hai script cấp tiền
  demo và seed T-107 cùng test OCPP liên quan đã được cập nhật.
- Các phản hồi validation của command ví bỏ `input` và `ctx` để tránh echo bí mật;
  giữ error shape `detail` hiện có. API nhật ký dùng no-store.

## Transaction, lưu trữ và quyền

Các thao tác giữ ranh giới transaction hiện có. Không commit riêng audit;
request replay/no-op không tạo thêm dòng. Trigger append-only của audit_logs và
wallet_audits cùng quyền runtime insert/select-only được giữ nguyên. Chưa có
retention được duyệt nên không thêm purge. Migration `i230023a2026` chỉ tạo index
lookup theo action/time/id, không backfill hoặc sửa chứng từ cũ.

## Kiểm tra

- PostgreSQL thử riêng, migrate head; API/projection/scope/legacy/pagination,
  unlock reason, replay, rollback sau flush, lỗi audit không đổi tiền.
- Runtime role thật không được UPDATE/DELETE/TRUNCATE audit_logs/wallet_audits.
- Hồi quy phí đặt chỗ, script demo/seed và phạm vi phân quyền.
- Frontend: filter, phân trang, mở chi tiết, quyền các vai trò, lịch sử thiếu;
  nạp tay/confirmation/retry giữ nguyên request và lý do.
- Ruff, mypy, TypeScript, ESLint, build và xem thử giao diện.

Kết quả 17/10/2026: **186 test backend hồi quy đạt**, **13 test chốt cuối đạt**
(có giao nhau với hồi quy; không cộng hai số thành tổng test khác nhau),
**22 test frontend đạt**. Ruff, mypy cho 7 file backend liên quan, TypeScript,
ESLint và production build đạt. Build còn cảnh báo bundle chung trên 500 kB;
backend có cảnh báo deprecation từ pytest/Starlette, không có test lỗi.
Log/JUnit nằm ở scratch cha `s56-regression.*` và `s56-tests.*`.

Các kết quả trên là kiểm tra cục bộ; chưa nghiệm thu staging hoặc cập nhật Jira Done.
Nghiệm thu staging sau triển khai phải kiểm tra giao diện thực, transaction và
runtime role trên DB staging; bản xem thử dùng dữ liệu minh họa không thay thế bước này.
