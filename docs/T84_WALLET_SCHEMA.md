# S-41 / T-84 — bảng ví và sổ cái

Migration `a080009a2026` nối sau `f070008a2026` (T-59). Task độc lập với T-60; không có API/UI, tạo ví tự động, backfill, hàm ghi sổ cái hay job đối chiếu trong T-84.

## Hợp đồng dữ liệu

Model: `src/modules/wallet/models.py`, lớp `Wallet` và `WalletLedger`; đã đăng ký trong `migrations/env.py`.

`wallets`:

| Cột | Kiểu | Quy tắc |
| --- | --- | --- |
| id | UUID | Khoá chính; ORM sinh UUID, SQL trực tiếp phải truyền ID |
| driver_id | UUID | FK users, unique, không rỗng; T-85 kiểm vai trò tài xế |
| balance_vnd | BIGINT | Mặc định 0, cho phép âm |
| status | VARCHAR(20) | active (mặc định) hoặc locked |
| created_at / updated_at | timestamptz | Mặc định thời điểm DB; ORM cập nhật updated_at khi sửa ví |

`wallet_ledger`:

| Cột | Kiểu | Quy tắc |
| --- | --- | --- |
| id | BIGINT identity | Khoá chính tăng tự động |
| wallet_id | UUID | FK wallets, không rỗng |
| entry_type | VARCHAR(30) | gateway_topup, manual_topup, charging_debit, adjustment |
| amount_vnd | BIGINT | Số tiền có dấu; các hàm nghiệp vụ kiểm dấu tương ứng loại |
| balance_after_vnd | BIGINT | Số dư sau giao dịch, có thể âm |
| reference_type | VARCHAR(50) | Loại đối tượng tham chiếu, không trắng/rỗng |
| reference_id | VARCHAR(128) | Mã đối tượng tham chiếu, không trắng/rỗng |
| actor_id | UUID nullable | FK users; hệ thống/cổng không có người thực hiện thì NULL |
| created_at | timestamptz | Mặc định thời điểm DB |

Khoá unique toàn bảng là `(entry_type, reference_id)`, **không** gồm wallet_id hay reference_type. Trùng khoá ở ví khác vẫn bị DB từ chối. T-86/T-95 phải so ví và số tiền khi xử lý idempotency; không được coi mọi xung đột unique là thành công.

Chỉ mục lịch sử `(wallet_id, id DESC)` hỗ trợ phân trang theo mã dòng. Tất cả tiền tính bằng nguyên đồng VND, không dùng float; số 0 vẫn lưu được ở mức schema, quy tắc nghiệp vụ thuộc hàm ghi sổ cái. Schema không tự tính balance_after_vnd hay bảo đảm balance_vnd bằng tổng sổ cái; T-86 thực hiện cùng giao dịch, T-87 đối chiếu.

Các FK đều RESTRICT: không xoá ví có sổ cái, tài xế có ví, hoặc người thực hiện đang được sổ cái tham chiếu. Không cascade xoá lịch sử tài chính.

## Adjustment và task tiếp theo

- `adjustment` có sẵn trong migration M1. DB yêu cầu actor_id khác NULL và reference_type = `audit`; reference_id là mã bản ghi audit.
- Schema cho phép chèn adjustment vào ví locked. Kiểm quyền quản trị, tồn tại bản ghi audit và ghi audit cùng giao dịch do lệnh quản trị T-87 triển khai; T-84 chưa cung cấp đường gọi này và không tạo audit giả.
- T-85 tạo đúng một ví/tài xế, số dư 0, trong giao dịch tạo tài khoản; backfill tài xế cũ thuộc T-85. Upgrade T-84 không tự tạo ví.
- T-86 là đường duy nhất đổi số dư trong ứng dụng: khoá ví, kiểm xung đột, chèn sổ cái, cập nhật ví; ví locked chỉ nhận adjustment. Cần kiểm số nguyên, dấu của từng loại, giới hạn BIGINT và rollback toàn bộ khi lỗi.
- Quy ước tham chiếu: gateway_topup → wallet_topup/mã đơn nội bộ; manual_topup → manual_topup/mã yêu cầu; charging_debit → charging_session/mã phiên; adjustment → audit/mã audit. Chuẩn hoá mã thành chuỗi trước khi ghi, không thêm tiền tố theo ví để né khoá unique.

## Bảo vệ chỉ ghi thêm

Theo mẫu T-57, trigger PostgreSQL chặn UPDATE, DELETE và TRUNCATE trên wallet_ledger, kể cả với tài khoản app hiện sở hữu bảng. TRUNCATE wallets CASCADE cũng bị chặn khi đụng sổ cái. Migration thu hồi UPDATE/DELETE/TRUNCATE từ PUBLIC; không cấp quyền đọc/chèn cho PUBLIC.

Nếu môi trường có tài khoản runtime riêng, dùng chủ migration chạy:

```text
psql <kết-nối-DB-bằng-chủ-migration> -v app_role=<tên-role-runtime-đã-có> -f scripts/grant_wallet_ledger.sql
```

Script chỉ cấp USAGE schema, SELECT/INSERT sổ cái và USAGE sequence; thu hồi UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER khỏi role đó. Không tạo role, không sửa mật khẩu hay cấu hình deploy. Role runtime phải không là superuser/owner và không kế thừa quyền quản trị nếu muốn giới hạn bằng ACL. Trigger vẫn bảo vệ DML thông thường khi app dùng owner như môi trường hiện có; DBA có quyền thay DDL/trigger không nằm trong bảo đảm này.

Sau khi downgrade rồi upgrade lại, cấp lại quyền cho runtime role nếu có. Không tự thay quyền tất cả các bảng khác trong task này.

## Migration và kiểm thử

Trên database kiểm thử riêng:

```text
alembic upgrade head
alembic check
pytest -q tests/test_wallet_schema.py tests/test_charge_points_migration.py
```

Downgrade tới `f070008a2026` xoá hai bảng ví mới cùng trigger/function/sequence liên quan; dữ liệu ví/sổ cái trong các bảng này bị xoá. Người dùng, trạm, biểu giá và các bảng trước đó được giữ nguyên. Không chạy downgrade trên database có dữ liệu tài chính cần giữ nếu chưa có phương án lưu/khôi phục dữ liệu.

Test dùng PostgreSQL thật: số tiền vượt 32-bit, nợ âm, các loại giao dịch, unique xuyên ví, FK/ràng buộc, thứ tự lịch sử, chặn sửa/xoá/truncate ở owner, và tài khoản không có quyền quản trị đọc/chèn được nhưng bị từ chối sửa/xoá/truncate. Test tạo role riêng trong giao dịch rồi rollback; không để lại role trên DB.
