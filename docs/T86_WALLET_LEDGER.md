# S-41 / T-86 — Ghi sổ cái và quản lý số dư

T-86 là hợp đồng chung cho T-88, T-95, T-101 và nhánh phục hồi cache của T-87.
Chưa tạo ví tự động (T-85), job đối chiếu, lệnh/API quản trị (T-87), nạp tiền hay trừ tiền phiên sạc.

## Ghi biến động tiền

```python
from src.modules.wallet.service import ghi_so_cai

async with session.begin():
    row = await ghi_so_cai(
        session,
        wallet_id=wallet_id,
        entry_type="charging_debit",
        amount_vnd=-invoice_total_vnd,
        reference_type="charging_session",
        reference_id=str(charging_session_id),
    )
    # Lập hóa đơn, đánh dấu settlement và ghi sổ cùng giao dịch ở T-102.
```

- Hàm khóa ví bằng `SELECT FOR UPDATE`, đọc lại số dư hiện tại, ghi sổ và cập nhật số dư trong savepoint. Không commit/rollback giao dịch ngoài; người gọi quyết định commit. Lỗi SQL trong phần ghi không làm hỏng giao dịch ngoài.
- Tiền phải là `int` nguyên đồng trong BIGINT có dấu; không nhận bool, float hay Decimal. Nạp tiền dương, trừ tiền âm, adjustment khác 0. Hóa đơn 0 đồng không gọi hàm ghi sổ.
- Khóa chống trùng toàn hệ thống là `(entry_type, reference_id)`. Cùng khóa, đúng ví và số tiền trả dòng cũ, giữ số dư; khác ví hoặc số tiền báo `WalletLedgerConflictError` và không ghi thêm. `reference_type` không thuộc khóa chống trùng; các module phải thống nhất cách đặt tham chiếu.
- Ví `locked` từ chối cả giao dịch thường mới và gọi lại giao dịch thường. Chỉ adjustment có quyền/audit hợp lệ được ghi; không tự mở khóa.
- Các ví khác nhau tranh cùng khóa được xử lý bằng PostgreSQL `ON CONFLICT`, không dùng việc bắt lỗi unique rồi bỏ qua giao dịch đã hỏng.
- Người gọi không được tự ghi WalletLedger hoặc tự UPDATE số dư. Khi một giao dịch thao tác nhiều ví, khóa theo thứ tự UUID cố định để tránh deadlock. Dùng mức cô lập READ COMMITTED như cấu hình hiện tại; nếu lỗi deadlock/serialization xảy ra, rollback và thử lại toàn bộ giao dịch ở tầng điều phối.
- `actor_id` lấy từ người dùng đã xác thực, không lấy trực tiếp từ nội dung yêu cầu. Quyền nạp tiền/thanh toán do endpoint tương ứng kiểm tra; module này tự kiểm tra admin đang active đối với adjustment và phục hồi cache.

## Adjustment có audit

T-87 cần khóa ví, xác minh sai lệch nghiệp vụ và tạo `WalletAudit` trong cùng giao dịch, với:

- `action="adjustment_authorized"`, ví và admin thực hiện;
- số dư trước/sau, số tiền chênh lệch khác 0, lý do 1–500 ký tự;
- sau = trước + số tiền.

Sau đó gọi `ghi_so_cai` với `entry_type="adjustment"`, `reference_type="audit"`, `reference_id=str(audit.id)`, cùng actor và số tiền. Module kiểm tra quyền admin từ database, audit đúng ví/actor/số tiền và số dư chưa thay đổi. Gọi lại cùng audit không cộng/trừ lại, kể cả đã có adjustment tiếp theo. Audit và dòng tiền phải commit cùng nhau; nếu thất bại, lệnh quản trị rollback toàn giao dịch. T-86 chưa cung cấp lệnh quản trị cho người dùng.

## Sửa riêng số dư lưu sẵn

```python
from src.modules.wallet.service import phuc_hoi_so_du_cache

await phuc_hoi_so_du_cache(
    session,
    wallet_id=wallet_id,
    actor_id=authenticated_admin_id,
    reason="Đã xác minh sổ cái; sửa số dư lưu sẵn",
)
```

T-87 phải xác minh sổ cái và liên kết hóa đơn trước khi gọi. Hàm khóa ví, tính tổng sổ cái trong lúc giữ khóa, đặt cache bằng tổng và ghi audit `cache_repaired`. Số dư 100.000 nhưng sổ cái 80.000 sẽ trở thành 80.000, không tạo adjustment giả. Gọi lại khi đã khớp không tạo thêm audit. Giữ nguyên trạng thái khóa; lỗi hóa đơn/sổ cái nghiệp vụ không được giải quyết bằng sửa cache.

## Migration và quyền database

- Migration mới: `b090010a2026`, nối `a080009a2026`; chỉ thêm `wallet_audits`, không backfill ví hoặc đổi số dư cũ.
- Audit được bảo vệ bởi trigger cấm UPDATE/DELETE/TRUNCATE, kể cả chủ bảng. Script `scripts/grant_wallet_ledger.sql` cấp SELECT/INSERT cho cả ledger và audit; chạy sau upgrade bằng tài khoản migration và biến psql `app_role` là role runtime đã tồn tại. Script không tạo role và không cấp quyền ghi ví/người dùng.
- Runtime cần các quyền đọc identity và đọc/cập nhật ví từ cấu hình ứng dụng; phải dùng role không sở hữu bảng, không superuser. Hàm Python là điểm tập trung cập nhật; quyền database UPDATE ví vẫn cần cho ứng dụng.
- Downgrade về T-84 giữ ví/sổ cái và trigger của sổ cái, nhưng xóa toàn bộ audit mới. Không downgrade môi trường có audit cần giữ nếu chưa có kế hoạch sao lưu/phục hồi.

## Kiểm chứng

`tests/test_wallet_service.py` kiểm tra giao dịch thật, replay/xung đột, ví khóa, quyền/audit, phục hồi cache và ACL. Các ca commit đồng thời tự tạo/xóa database tạm có tên `t86_<uuid>`; tài khoản kiểm thử cần CREATEDB. Không dùng tài khoản runtime để chạy bộ test này, không trỏ test vào database demo/staging. Ca 100 lần ghi dùng hai kết nối PostgreSQL thật; ca tranh khóa dùng `pg_blocking_pids` để xác nhận có chờ khóa trước khi commit.
