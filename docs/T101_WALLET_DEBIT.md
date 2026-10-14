# S-37 / T-101 — Hàm `tru_vi` trừ ví theo hoá đơn

> **Story**: S-37 — Ví bị trừ tự động khi phiên kết thúc, có bản ghi giao dịch (5 Story Points)  
> **Task**: T-101 — Hàm `tru_vi` trừ ví theo hoá đơn, ví thiếu tiền vẫn trừ để âm  
> **Phụ trách**: TV6 | **Phân loại**: Backend Service & Kiểm thử tự động  
> **Module**: `src.modules.wallet`

---

## 1. Mục tiêu và phạm vi

Task T-101 xây dựng hàm nghiệp vụ nền tảng `tru_vi` để trừ tiền ví tài xế sau khi phiên sạc đã được lập hoá đơn (`lap_hoa_don` - T-80).

### Hợp đồng hàm `tru_vi`:
```python
from src.modules.wallet.service import tru_vi


async def tru_vi(
    session: AsyncSession,
    *,
    invoice: Invoice | None = None,
    session_id: int | None = None,
    wallet_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> WalletLedger | None: ...
```

---

## 2. Các nguyên tắc bất biến (Invariants)

1. **Transaction của Caller**:
   - Hàm nhận `session: AsyncSession` từ người gọi và tuyệt đối không tự `commit()` hay `rollback()`.
   - Toàn bộ thao tác ghi sổ và cập nhật số dư chạy an toàn trong savepoint nội bộ của `ghi_so_cai` (`session.begin_nested()`). Caller quyết định commit toàn bộ chu trình xử lý.

2. **Ghi sổ cái trừ tiền sạc**:
   - Loại giao dịch: `entry_type="charging_debit"`.
   - Số tiền: `amount_vnd = -invoice.total_vnd` (luôn là số âm khi hoá đơn > 0).

3. **Chống trừ lặp bằng Unique Reference (Idempotency)**:
   - Tham chiếu: `reference_type="charging_session"`, `reference_id=str(invoice.session_id)`.
   - Ràng buộc duy nhất `uq_wallet_ledger_reference (entry_type, reference_id)` chặn trừ hai lần cho cùng một phiên sạc.
   - Nếu gọi lại `tru_vi` cho phiên sạc đã trừ, hàm trả về chính bản ghi `WalletLedger` cũ và không trừ thêm tiền.

4. **Số dư âm là nợ (Debt Allowed)**:
   - Cột `wallets.balance_vnd` là kiểu BIGINT có dấu không ràng buộc `>= 0`.
   - Khi số dư không đủ (kể cả 0đ hoặc đang âm), hệ thống vẫn trừ bình thường; số dư âm đại diện cho khoản nợ tiền sạc của tài xế.

5. **Bỏ qua hoá đơn 0 đồng**:
   - Nếu `invoice.total_vnd == 0`, hàm lập tức trả về `None`, không gọi `ghi_so_cai` và không sinh bất kỳ bản ghi nào trong `wallet_ledger`.

6. **Không đặt cờ `settlement_*`**:
   - Hàm `tru_vi` **không** chạm vào các trường `settlement_completed_at` hoặc `settlement_reason` trên bảng `charging_sessions`.
   - Việc chốt trạng thái phiên sạc và hoàn tất thanh toán thuộc trách nhiệm của Task T-102.

7. **Tự động tìm hoặc khởi tạo ví tài xế**:
   - Nếu `wallet_id` không được truyền vào, hàm tìm ví theo `invoice.driver_id`.
   - Nếu tài xế chưa có ví, hàm gọi `ensure_driver_wallet(session, invoice.driver_id)` để khởi tạo ví mới trước khi ghi sổ.
   - Nếu truyền `wallet_id`, hàm khóa ví và kiểm tra `wallet.driver_id == invoice.driver_id`; sai chủ sở hữu trả `WalletOwnershipError`, không ghi sổ hay đổi số dư. Ví không tồn tại trả `WalletNotFoundError`.
   - Nếu đồng thời truyền `invoice` và `session_id`, hai giá trị phải thuộc cùng phiên. Tổng tiền phải là số nguyên VND trong miền signed BIGINT, không nhận boolean hoặc số thập phân.

8. **Bảo tồn giao diện hệ thống**:
   - Giữ nguyên 100% cấu trúc, logic và style của frontend (`frontend/src/features/driver/DriverWalletPage.tsx`).
   - Giao diện tài xế đã hỗ trợ hiển thị nợ âm (`isLowBalance`, `-15.000 ₫`) và giao dịch `charging_debit` (`⚡ Thanh toán phiên sạc`).

---

## 3. Ma trận kiểm thử tự động (`tests/test_t101_wallet_debit.py`)

| Test Case | Mục đích kiểm chứng | Kết quả mong đợi |
| :--- | :--- | :--- |
| `test_tru_vi_thanh_cong_va_ghi_so_cai` | Trừ ví khi có đủ tiền | Trả về `WalletLedger`, số tiền âm, số dư giảm đúng, tham chiếu là session ID. |
| `test_tru_vi_thieu_tien_van_tru_de_so_du_am` | Trừ ví khi thiếu tiền hoặc đã âm | Trừ thành công, số dư sau trừ chuyển sang âm (nợ). |
| `test_tru_vi_hoa_don_zero_dong_bo_qua_khong_ghi_dong` | Hoá đơn 0 đồng | Trả về `None`, số dư không đổi, không có dòng sổ cái nào. |
| `test_tru_vi_hai_lan_cho_cung_phien_idempotent_chan_tru_trung` | Gọi lại lần 2 cho cùng phiên | Trả về dòng cũ, số dư chỉ trừ 1 lần, không trùng bản ghi. |
| `test_tru_vi_khong_dat_settlement_fields` | Bảo vệ trường settlement | `settlement_completed_at` và `settlement_reason` vẫn là `None`. |
| `test_tru_vi_trong_giao_dich_caller_rollback_sach` | Caller rollback transaction | Số dư và sổ cái phục hồi sạch về trạng thái ban đầu. |
| `test_tru_vi_tu_choi_khi_vi_bi_khoa` | Ví ở trạng thái `locked` | Bị từ chối với `WalletLockedError`, không trừ tiền. |
| `test_tru_vi_tu_dong_tao_vi_khi_tai_xe_chua_co_vi` | Tài xế chưa có bản ghi `wallets` | Tự động tạo ví mới và trừ tiền thành công. |
| `test_tru_vi_tra_cuu_qua_session_id` | Gọi với `session_id` | Tự tìm hoá đơn tương ứng và thực hiện trừ tiền. |
| `test_tru_vi_tham_so_hop_le_va_ngoai_le` | Tham số sai, thiếu hoặc hoá đơn âm | Bắt đúng `ValueError`, `LookupError`, `WalletAmountError`. |
| `test_tru_vi_tuong_thich_reconciliation_doi_chieu` | Chạy hàm `wallet_issues` | Số dư khớp tổng sổ cái, 0 lỗi bất thường (`issues == []`). |
| `test_explicit_wallet_must_belong_to_invoice_driver` | Chặn ví khác chủ và ví không tồn tại | Cả hai số dư không đổi, không sinh debit; ví đúng chủ vẫn trừ được trong transaction đó. |
| `test_zero_balance_becomes_debt` | Ví có số dư chính xác 0 | Trừ thành -15.000 VND; tổng ledger khớp số dư. |
| `test_mismatched_session_and_invalid_money_rejected` | Sai mã phiên hoặc kiểu tiền | Từ chối trước khi ghi sổ, số dư không đổi. |
| `test_concurrent_debits_use_separate_connections` | Hai kết nối PostgreSQL thật | Cùng phiên chỉ một debit; hai phiên cùng ví đều trừ, số dư cuối đúng tổng hai hóa đơn. |
| `test_outer_rollback_removes_invoice_debit_and_balance_change` | Rollback transaction ngoài | Kết nối khác không thấy ghi chưa commit; sau rollback không còn hóa đơn/debit, số dư ban đầu được giữ. |

## 4. Cách thiết lập dữ liệu và giới hạn nghiệm thu

- Fixture tài xế không cấp ví sẵn để test tự tạo ví thực sự chạy nhánh provisioning. Các test còn lại cấp ví 0 VND và nạp số dư qua `ghi_so_cai`; không gán số dư cache thay cho ledger.
- Test rollback savepoint chỉ rollback savepoint đó, lưu mã phiên trước khi ORM bị expire. Test transaction ngoài dùng database riêng và kết nối quan sát độc lập.
- Test đối soát mô phỏng phần hoàn tất của T-102 bằng cả `settlement_reason='debited'` và `settlement_completed_at`; đây là thiết lập test, không phải hành vi mới của `tru_vi`.
- Hai test đồng thời dùng database riêng, barrier và hai backend PID khác nhau; database được dọn bởi fixture sau test.
- T-101 cung cấp service trừ ví. Bằng chứng này chưa xác nhận tích hợp tự động khi phiên kết thúc, đánh dấu thanh toán của T-102, hoặc UI/staging của toàn bộ S-37.

Kiểm tra: `pytest tests/test_t101_wallet_debit.py -q`, `ruff check .`, `ruff format --check .`, `mypy src`. Toàn bộ test chức năng cần database mới, vì một số test hóa đơn khác commit bản ghi thật; hai test độ trễ OCPP chạy ở gate riêng của CI.

## 5. Kết quả kiểm chứng local ngày 11/10/2026

- T-101: **17 test pass**, gồm hai trường hợp đồng thời và rollback transaction ngoài trên database riêng.
- Nhóm T-101, wallet service, reconciliation, provisioning và T-80/T-81/T-82/T-83: **161 test pass**.
- Toàn bộ test chức năng trên database mới: **1.631 test pass, 2 test độ trễ deselect**, 4 cảnh báo deprecation; hai test độ trễ vẫn bắt buộc ở bước riêng của CI.
- Ruff, kiểm tra định dạng và `mypy src`: đạt; không thay đổi workflow CI.
- Các kết quả trên là kiểm chứng local, không thay cho trạng thái CI, Jira hoặc nghiệm thu staging.
