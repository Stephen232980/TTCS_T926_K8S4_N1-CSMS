# T-83 / S-33 — Test hoá đơn bất biến, không trùng và không đổi khi biểu giá đổi

## 1. Mục tiêu và phạm vi

Task T-83 hoàn thiện bộ ba kiểm thử tích hợp (theo mẫu T-29) nhằm chứng minh các tính chất cốt lõi của hoá đơn trong Story S-33:
- **Không trùng (Idempotent / Deduplication)**: Lập hoá đơn nhiều lần cho một phiên chỉ tạo đúng 1 bản ghi hoá đơn (`Invoice`) và không làm nhân bản các dòng hoá đơn (`InvoiceLine`).
- **Bất biến khi đổi biểu giá (Tariff Snapshot Immutability)**: Hoá đơn đã lưu đóng băng snapshot biểu giá tại thời điểm lập. Việc thay đổi hoặc ban hành biểu giá mới cho trạm sau đó tuyệt đối không làm thay đổi hoá đơn và số tiền của các phiên cũ.
- **Chống sửa/xoá bằng tài khoản ứng dụng (Database Mutation Rejection)**: Mọi thao tác `UPDATE`, `DELETE`, `TRUNCATE` trên bảng `invoices` và `invoice_lines` đều bị từ chối bởi PostgreSQL Trigger `reject_invoice_mutation()` và quyền tối thiểu (least privilege). Khoá ngoại `RESTRICT` ngăn chặn việc xoá các thực thể cha (`charging_sessions`, `stations`, `users`, `tariffs`) khi đã có hoá đơn tham chiếu.

PR chỉ bổ sung kiểm thử backend và tài liệu, không thay đổi giao diện.
Kiểm thử API ở đây không thay thế nghiệm thu trình duyệt hoặc staging của S-33.

## 2. Ba test tích hợp theo mẫu T-29

Tệp kiểm thử: `tests/test_t83_invoice_invariants.py`.

### Test 1: `test_t83_lap_hoa_don_hai_lan_cho_mot_phien_thi_mot_hoa_don`
- Gọi `lap_hoa_don(db, session_id)` lần 1 tạo hoá đơn thành công kèm các dòng chi tiết.
- Gọi `lap_hoa_don(db, session_id)` lần 2 và `chot_phien(session_id)`: trả về cùng snapshot đã lưu, cùng `invoice_id`.
- Kiểm tra truy vấn Database: `SELECT COUNT(*) FROM invoices WHERE session_id = :session_id` chính xác bằng 1.
- Kiểm tra số lượng dòng trong `invoice_lines` không bị nhân đôi.
- So sánh toàn bộ cột đã lưu của Invoice và InvoiceLine trước/sau các lần lập;
  truy vấn trực tiếp dữ liệu, không dựa vào cache đối tượng ORM.
- API tài xế (`GET /api/v1/driver/charging/sessions/{id}/invoice` và `GET /api/v1/driver/invoices`) trả về đúng 1 hoá đơn ở trạng thái `ready` với số tiền và dòng nguyên vẹn.

### Test 2: `test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi`
- Phiên 1 (Session 1) sạc và lập hoá đơn với Biểu giá A (3.000 đ/kWh, idle 200 đ/phút).
- Biểu giá A được đánh dấu `used_at` và được bảo vệ bất biến (`TariffImmutableError`).
- Trạm ban hành Biểu giá B mới (ngày hôm sau, 8.000 đ/kWh, idle 1.000 đ/phút).
- Tái lập hoá đơn Session 1: trả về nguyên vẹn hoá đơn ban đầu (tổng tiền 30.000 đ, đơn giá 3.000 đ/kWh, `tariff_id` vẫn là Biểu giá A).
- API tài xế đọc lại Session 1: dữ liệu snapshot cũ được giữ nguyên 100%.
- Phiên 2 mới (Session 2) tại cùng trạm thuộc thời điểm Biểu giá B nhận đúng mức giá mới 8.000 đ/kWh.
- Sau expire/reload, mọi cột snapshot và toàn bộ response API chi tiết của phiên 1
  vẫn bằng giá trị đã lưu trước khi thêm biểu giá B. ID và giá trị kỳ vọng được
  giữ trong biến thông thường trước expire để tránh truy vấn ORM ngầm.

### Test 3: `test_t83_update_hoac_delete_bang_tai_khoan_ung_dung_bi_tu_choi`
- Bảng `invoices` và `invoice_lines` có trigger chặn `UPDATE`, `DELETE`, `TRUNCATE`.
- Mọi câu lệnh sửa/xoá thông qua session/kết nối của ứng dụng đều bị PostgreSQL từ chối với lỗi `invoice evidence is append-only`.
- File `scripts/grant_invoice_evidence.sql` bắt buộc tồn tại, thiếu file làm test lỗi.
- Vai trò runtime ứng dụng được tạo bằng NOLOGIN/NOSUPERUSER/NOINHERIT, kiểm tra
  `current_user` sau SET LOCAL ROLE. SELECT và INSERT thực sự chạy trên cả hai bảng;
  UPDATE/DELETE/TRUNCATE bị từ chối với SQLSTATE `42501` (insufficient_privilege).
- Ràng buộc khoá ngoại FK `RESTRICT` chặn xoá `charging_sessions`, `stations`, `users`, `tariffs`.
- Các lần thử xoá cha phải nhận SQLSTATE `23503` (foreign_key_violation).
- Dữ liệu hoá đơn nguyên vẹn tuyệt đối sau các nỗ lực thao tác trái phép.

## 3. Coverage Matrix

| AC/NFR | Hành vi kiểm chứng | Test thực hiện | Kết quả kỳ vọng |
| :--- | :--- | :--- | :--- |
| **Không trùng hoá đơn** | Lập hoá đơn nhiều lần cho một phiên chỉ ra đúng 1 hoá đơn | `test_t83_lap_hoa_don_hai_lan_cho_mot_phien_thi_mot_hoa_don` | Đúng 1 bản ghi `Invoice`, không duplicate dòng, API tài xế trả về 1 hoá đơn duy nhất |
| **Bất biến khi đổi biểu giá** | Biểu giá trạm đổi sau đó không làm thay đổi hoá đơn cũ | `test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi` | Hoá đơn cũ giữ nguyên đơn giá/thành tiền/tariff snapshot; phiên mới nhận giá mới |
| **Bảo vệ toàn vẹn & append-only** | UPDATE hoặc DELETE bằng tài khoản app bị từ chối | `test_t83_update_hoac_delete_bang_tai_khoan_ung_dung_bi_tu_choi` | Trigger ném exception `append-only`, app role bị từ chối quyền, FK RESTRICT bảo vệ |
| **API đọc snapshot cũ** | Response chi tiết trước/sau đổi biểu giá giống nhau | `test_t83_doi_bieu_gia_sau_do_thi_hoa_don_cu_khong_doi` | So sánh toàn bộ response, không tính lại giá theo biểu giá mới |

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
mypy src
```

Test tự động được phát hiện và thực thi trong CI qua `.github/workflows/ci.yml`.
Trước khi push, chạy thêm toàn bộ test chức năng theo CI:

```powershell
pytest --deselect=tests/test_charging_sessions.py::test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms --deselect=tests/test_s19_meter_latency.py::test_twenty_real_sockets_periodic_meter_replies_under_200ms
```

Hai test độ trễ vẫn là gate riêng bắt buộc trong CI; không bỏ chúng khỏi workflow.
Database cần PostgreSQL đã `alembic upgrade head`; dùng database thử riêng.
Kết quả local không chứng minh CI hoặc staging đã đạt.

## 5. Kết quả local ngày 11/10/2026

- PostgreSQL 16, database thử riêng đã migrate; không dùng database phát triển.
- Ba test T-83: **3 passed**.
- Nhóm schema/T-80/T-81/T-82/T-83: **103 passed**.
- Toàn bộ test chức năng trên database mới: **1614 passed, 2 deselected**.
  Hai test bị deselect là gate độ trễ chạy riêng theo workflow CI.
- Ruff lint, Ruff format và `mypy src`: pass.

Nhóm hóa đơn có test commit dữ liệu thật; không dùng lại database của lượt nhóm
để chạy bộ chức năng từ đầu. Một lượt thử dùng lại database đã gây lỗi các test
cũ đếm phiên toàn database; lượt 1614 passed ở trên dùng database mới.
PR giữ nguyên commit gốc của thành viên, bổ sung sửa test và bằng chứng snapshot/
quyền ứng dụng trong commit riêng. Chưa có bằng chứng staging từ các lượt local.
