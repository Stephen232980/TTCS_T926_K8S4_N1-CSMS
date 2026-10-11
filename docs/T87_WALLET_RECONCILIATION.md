# T-87 — đối chiếu và xử lý ví

Nhánh feature/S-41-T-87-wallet-reconciliation từ develop e8632dd đã có
T-57 A/B và T-88. Phạm vi theo S-41 và T-87 trong bảng chia việc Sprint 4–5.
Không triển khai T-101/T-102, không thêm giao diện hay bảng/migration.

## Quyết định xử lý được người dùng chốt

1. Sổ cái là nguồn tiền đúng. Chỉ lệch bản sao: quản trị kiểm bằng chứng
   rồi sửa cache bằng tổng sổ cái dưới khoá dòng, ghi trước/sau và audit;
   không ghi adjustment và chưa mở khoá.
2. Mở khoá chạy lại toàn bộ kiểm tra của job dưới khoá dòng. Còn sai thì
   từ chối với danh sách kiểm tra lỗi, giữ ví khoá. Không thêm hành động
   mở khoá vào wallet_audits; audit chung ghi ví và số dư đã kiểm.
3. Adjustment là lệnh riêng, số tiền khác 0, tham chiếu wallet_audits.id;
   ghi được khi ví khoá, không tự mở khoá. Cache phải khớp tổng trước khi
   điều chỉnh, để không dùng tiền thật che lệch cache. Sau đó gọi mở khoá
   riêng và kiểm lại. Không tự sửa hoặc viết lại sổ cái bất biến.
4. Mỗi hành động ghi một audit_logs qua ghi_nhat_ky cùng giao dịch. Các
   lần no-op/replay không thêm audit. Không sao chép lý do tự do vào JSON;
   lý do sửa cache/điều chỉnh ở wallet_audits, audit trỏ tới mã đó.

## Job và nguồn đối chiếu

doi_chieu_so_du khoá dòng ví bằng FOR UPDATE SKIP LOCKED trước khi đọc tổng
sổ cái và các hoá đơn của phiên có settlement_reason=debited. Ví bận bỏ qua
vòng này; đọc lại ORM bằng populate_existing để không dùng cache cũ.
Kiểm đúng người/ví, một dòng trừ, loại charging_debit, tham chiếu
charging_session/mã phiên, tiền bằng âm invoice.total_vnd. Ví thực sự bị
trừ nhầm cũng được kiểm nếu dòng sổ cái trỏ tới phiên/hoá đơn đó.
Không yêu cầu dòng trừ cho zero_invoice, legacy_exempt hoặc chưa settlement.

Có lỗi thì chuyển active thành locked và ghi wallet.reconciliation_locked
với actor hệ thống NULL, số dư/tổng và mã kiểm tra. Job không sửa tiền hay
mở khoá. Ví đã khoá không sinh audit/cảnh báo lặp.

Runner đọc mã ví theo lô 500, mỗi ví một giao dịch để không giữ khoá toàn
bộ trong một lần quét. Log cảnh báo chỉ phát sau commit thành công và chỉ
ghi mã ví. Một ví lỗi database không chặn các ví khác; vòng sau kiểm lại.
Lifespan ứng dụng chạy/cancel job cùng các tác vụ cũ. Mặc định quét sau
300 giây rồi lặp; cấu hình WALLET_RECONCILIATION_INTERVAL_SECONDS (>0),
đã truyền vào app trong Docker Compose.

Đối chiếu dựa vào hợp đồng T-101: reference_id là mã phiên. T-102 còn có
trách nhiệm ghi invoice, dòng trừ và settlement trong cùng giao dịch có
khoá ví; T-87 không triển khai việc chốt phiên thay cho T-102. Các test
T-87 tạo dữ liệu settlement để kiểm nền tảng trước khi T-102 được nối.

## Lệnh quản trị

Ba API admin (cookie session) được mô tả trong API_CONTRACT.md:
repair-cache, adjustments và unlock dưới /api/v1/admin/wallets/{wallet_id}.
Thứ tự cho cache lệch: job khoá → kiểm chứng sổ cái → repair-cache → unlock.
Thứ tự cho điều chỉnh được duyệt: adjustments → kiểm chứng → unlock.
Còn thiếu/sai dòng trừ hoá đơn: giữ khoá, xử lý nguồn nghiệp vụ; adjustment
tổng tiền không thay được mã tham chiếu dòng trừ.

Audit sửa cache/điều chỉnh dùng object_type=wallet_audit; audit khoá/mở
khoá dùng object_type=wallet. Quyền và vai trò người thực hiện lấy từ DB,
không nhận actor hoặc vai trò từ body. Runtime grants/trigger của T-57 A
và T-84/T-86 giữ nguyên, không áp dụng thay đổi quyền lên DB đang chạy.

## Ma trận kiểm chứng

| AC/NFR | Kiểm chứng |
| --- | --- |
| Lệch cache bị khoá, ví khớp không đổi | Sửa bằng SQL, một lần quét, số dư/ledger không đổi |
| Hai lần job không thêm tác dụng phụ | Một audit, một cảnh báo sau commit |
| Hoá đơn debited hợp lệ | Đúng một dòng đúng ví/tiền/loại/tham chiếu không bị khoá |
| Thiếu/thừa/sai dòng trừ | Bảy ca missing, duplicate, sai ví/tiền/loại/loại tham chiếu/mã |
| Không báo lệch giả khi đang ghi | Hai connection, skip ví bận rồi kiểm dữ liệu đã commit |
| Sửa cache không thêm tiền | Giữ một dòng sổ cái, audit trước/sau, chưa mở khoá |
| Mở khoá kiểm lại mọi điều kiện | Thiếu dòng trừ từ chối; chờ writer rồi thấy lệch mới commit |
| Adjustment khác 0, có bằng chứng | Zero/kiểu sai bị chặn; nợ được phép, audit UUID đúng |
| Replay/race adjustment | Cùng mã không ghi thêm; hai ví cùng mã một thắng, một conflict |
| Tiền/trạng thái và audit cùng giao dịch | Lỗi sau flush audit và rollback người gọi không để lại thay đổi |
| Chỉ admin hoạt động | 401/403 các vai trò, admin inactive, 404 ví chưa có |
| Không mở rộng schema/UI | Head b150015a2026, không migration mới, không sửa frontend |

## Kiểm chứng local ngày 08/10/2026

- 52 test T-87 mới đạt; cùng inventory quyền là 63 ca tập trung. Các phép
  đếm và kiểm tra bằng chứng chỉ xét ví/bản ghi do test sở hữu, kể cả khi
  database có dữ liệu từ các test cũ.
- Bộ hồi quy theo cấu hình CI: 803 passed, 2 deselected (hai ca latency
  tách gate riêng), 4 cảnh báo deprecation có sẵn.
- Ruff toàn repository đạt; format check 258 file đạt; mypy 92 file
  source và git diff check đạt.
- PostgreSQL 16: upgrade database thử rỗng thành công; một head
  b150015a2026 kế thừa T-57 A, không có migration/schema mới.
- Docker Compose đọc cấu hình chu kỳ: override 17 giây được truyền đúng
  vào app. Không khởi động/rebuild hay sửa database ứng dụng hiện hành.

CI, Jira và triển khai môi trường đang chạy cần được
xác nhận riêng với bằng chứng local này.
