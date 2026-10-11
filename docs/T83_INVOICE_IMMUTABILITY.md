# T-83 / S-33 — Test hoá đơn bất biến, không trùng và không đổi khi biểu giá đổi

## 1. Mục tiêu và phạm vi

Task T-83 hoàn thiện bộ ba kiểm thử tích hợp (theo mẫu T-29) nhằm chứng minh các tính chất cốt lõi của hoá đơn trong Story S-33:
- **Không trùng (Idempotent / Deduplication)**: Lập hoá đơn nhiều lần cho một phiên chỉ tạo đúng 1 bản ghi hoá đơn (`Invoice`) và không làm nhân bản các dòng hoá đơn (`InvoiceLine`).
- **Bất biến khi đổi biểu giá (Tariff Snapshot Immutability)**: Hoá đơn đã lưu đóng băng snapshot biểu giá tại thời điểm lập. Việc thay đổi hoặc ban hành biểu giá mới cho trạm sau đó tuyệt đối không làm thay đổi hoá đơn và số tiền của các phiên cũ.
- **Chống sửa/xoá bằng tài khoản ứng dụng (Database Mutation Rejection)**: Mọi thao tác `UPDATE`, `DELETE`, `TRUNCATE` trên bảng `invoices` và `invoice_lines` đều bị từ chối bởi PostgreSQL Trigger `reject_invoice_mutation()` và quyền tối thiểu (least privilege). Khoá ngoại `RESTRICT` ngăn chặn việc xoá các thực thể cha (`charging_sessions`, `stations`, `users`, `tariffs`) khi đã có hoá đơn tham chiếu.

Toàn bộ luồng và giao diện tuân thủ 100% giao diện hiện tại của hệ thống (`DriverInvoicePage.tsx`), không làm khác.

## 2. Ba test tích hợp theo mẫu T-29

Tệp kiểm thử: `tests/test_t83_invoice_invariants.py`.

### Test 1: `test_t83_lap_hoa_don_hai_lan_cho_mot_phien_thi_mot_hoa_don`
- Gọi `lap_hoa_don(db, session_id)` lần 1 tạo hoá đơn thành công kèm các dòng chi tiết.
- Gọi `lap_hoa_don(db, session_id)` lần 2 và `chot_phien(session_id)`: trả về cùng snapshot đã lưu, cùng `invoice_id`.
- Kiểm tra truy vấn Database: `SELECT COUNT(*) FROM invoices WHERE session_id = :session_id` chính xác bằng 1.
- Kiểm tra số lượng dòng trong `invoice_lines` không bị nhân đôi.
- API tài xế (`GET /api/v1/driver/charging/sessions/{id}/invoice` và `GET /api/v1/driver/invoices`) trả về đúng 1 hoá đơn ở trạng thái `ready` với số tiền và dòng nguyên vẹn.

### Test 2: `test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi`
- Phiên 1 (Session 1) sạc và lập hoá đơn với Biểu giá A (3.000 đ/kWh, idle 200 đ/phút).
- Biểu giá A được đánh dấu `used_at` và được bảo vệ bất biến (`TariffImmutableError`).
- Trạm ban hành Biểu giá B mới (ngày hôm sau, 8.000 đ/kWh, idle 1.000 đ/phút).
- Tái lập hoá đơn Session 1: trả về nguyên vẹn hoá đơn ban đầu (tổng tiền 30.000 đ, đơn giá 3.000 đ/kWh, `tariff_id` vẫn là Biểu giá A).
- API tài xế đọc lại Session 1: dữ liệu snapshot cũ được giữ nguyên 100%.
- Phiên 2 mới (Session 2) tại cùng trạm thuộc thời điểm Biểu giá B nhận đúng mức giá mới 8.000 đ/kWh.

### Test 3: `test_t83_update_hoac_delete_bang_tai_khoan_ung_dung_bi_tu_choi`
- Bảng `invoices` và `invoice_lines` có trigger chặn `UPDATE`, `DELETE`, `TRUNCATE`.
- Mọi câu lệnh sửa/xoá thông qua session/kết nối của ứng dụng đều bị PostgreSQL từ chối với lỗi `invoice evidence is append-only`.
- Vai trò runtime ứng dụng (`scripts/grant_invoice_evidence.sql`) chỉ có quyền `SELECT` và `INSERT`; lệnh `UPDATE`/`DELETE` bị từ chối quyền.
- Ràng buộc khoá ngoại FK `RESTRICT` chặn xoá `charging_sessions`, `stations`, `users`, `tariffs`.
- Dữ liệu hoá đơn nguyên vẹn tuyệt đối sau các nỗ lực thao tác trái phép.

## 3. Coverage Matrix

| AC/NFR | Hành vi kiểm chứng | Test thực hiện | Kết quả kỳ vọng |
| :--- | :--- | :--- | :--- |
| **Không trùng hoá đơn** | Lập hoá đơn nhiều lần cho một phiên chỉ ra đúng 1 hoá đơn | `test_t83_lap_hoa_don_hai_lan_cho_mot_phien_thi_mot_hoa_don` | Đúng 1 bản ghi `Invoice`, không duplicate dòng, API tài xế trả về 1 hoá đơn duy nhất |
| **Bất biến khi đổi biểu giá** | Biểu giá trạm đổi sau đó không làm thay đổi hoá đơn cũ | `test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi` | Hoá đơn cũ giữ nguyên đơn giá/thành tiền/tariff snapshot; phiên mới nhận giá mới |
| **Bảo vệ toàn vẹn & append-only** | UPDATE hoặc DELETE bằng tài khoản app bị từ chối | `test_t83_update_hoac_delete_bang_tai_khoan_ung_dung_bi_tu_choi` | Trigger ném exception `append-only`, app role bị từ chối quyền, FK RESTRICT bảo vệ |
| **Giao diện không đổi** | Giao diện tài xế hiển thị đầy đủ chi tiết từng đoạn giá | `DriverInvoicePage.tsx`, `DriverInvoicePage.test.tsx` | Giữ nguyên 100% component và style hiện có, format tiền `invoiceMoney` |

## 4. Hướng dẫn chạy kiểm thử

Chạy kiểm thử cục bộ:
```powershell
pytest tests/test_t83_invoice_invariants.py -q
```

Chạy toàn bộ nhóm test hoá đơn và kiểm thử chất lượng mã nguồn:
```powershell
pytest tests/test_invoice_schema.py tests/test_t80_invoicing.py tests/test_t81_closure.py tests/test_t82_driver_invoice.py tests/test_t83_invoice_invariants.py -q
ruff check tests/test_t83_invoice_invariants.py
ruff format --check tests/test_t83_invoice_invariants.py
mypy tests/test_t83_invoice_invariants.py
```

Test tự động được phát hiện và thực thi trong CI qua `.github/workflows/ci.yml`.
