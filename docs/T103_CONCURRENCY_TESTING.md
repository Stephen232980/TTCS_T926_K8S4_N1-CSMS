# Tài liệu Kỹ thuật T-103: Kiểm thử Tích hợp Đồng thời Chốt phiên & Trừ ví (Story S-37)

## 1. Giới thiệu & Mục tiêu
- **Story**: S-37 - Ví bị trừ tự động khi phiên kết thúc, có bản ghi giao dịch.
- **Task**: T-103 - Viết test tích hợp đồng thời (concurrency integration test) sử dụng kết nối cơ sở dữ liệu thật (PostgreSQL real sessions).
- **Tiêu chuẩn nghiệm thu**: *"Bốn test xanh, lặp 50 lần không lần nào lệch"*.
- **Vị trí file test**: [`tests/test_t103_concurrency.py`](file:///c:/Folder/CSMS/tests/test_t103_concurrency.py).

---

## 2. Chi tiết 4 Kịch bản Đồng thời Bắt buộc

### Kịch bản 1: Hai phiên của một tài xế chốt cùng lúc
- **Hàm test**: `test_t103_hai_phien_cung_tai_xe_chot_dong_thoi`
- **Mô tả hành vi**:
  - Tài xế có số dư ví ban đầu là 200.000 VNĐ.
  - Hai phiên sạc độc lập của tài xế (Phiên 1: 5 kWh ~ 15.000 VNĐ; Phiên 2: 10 kWh ~ 30.000 VNĐ) được kích hoạt chốt đồng thời (`asyncio.gather(chot_phien(s1), chot_phien(s2))`) qua 2 kết nối database tách biệt.
- **Kỳ vọng nghiệm thu**:
  - Cả hai phiên đều hoàn tất thành công (`status == 'ready'`).
  - Số dư ví cuối cùng: `200.000 - (15.000 + 30.000) = 155.000 VNĐ`.
  - Sổ cái ghi nhận đủ 2 dòng `charging_debit` tương ứng với mã phiên sạc.
  - Tổng số tiền trên sổ cái (`wallet_ledger`) khớp 100% với số dư hiện tại của ví (`wallet.balance_vnd`).
  - Trạng thái phiên đánh dấu `debited` và ghi nhận `settlement_completed_at`.

### Kịch bản 2: Hai (hoặc 4) tiến trình cùng chốt một phiên (Race Condition / Double Closure)
- **Hàm test**: `test_t103_hai_tien_trinh_cung_chot_mot_phien_race_condition`
- **Mô tả hành vi**:
  - 4 tiến trình độc lập đồng thời gọi `chot_phien(session_id, settle=True)` trên cùng một phiên sạc duy nhất.
- **Kỳ vọng nghiệm thu**:
  - Nhờ cơ chế khoá dòng `with_for_update()` và kiểm tra settlement:
    - Chỉ tạo **ĐÚNG 1** hoá đơn trong bảng `invoices`.
    - Chỉ trừ tiền ví **ĐÚNG 1** lần (chỉ 1 dòng ledger `charging_debit` tham chiếu đến `session_id`).
    - Tất cả 4 tiến trình đều nhận được kết quả `ready` hợp lệ kèm theo ID hoá đơn duy nhất đó.

### Kịch bản 3: Ví thiếu tiền thì số dư âm (Debt Balance)
- **Hàm test**: `test_t103_vi_thieu_tien_van_tru_de_so_du_am`
- **Mô tả hành vi**:
  - Ví tài xế ban đầu chỉ có 10.000 VNĐ.
  - Hai phiên sạc đồng thời phát sinh chi phí mỗi phiên 15.000 VNĐ (tổng chi phí 30.000 VNĐ, vượt số dư hiện có).
- **Kỳ vọng nghiệm thu**:
  - Cả 2 giao dịch chốt phiên đều thành công trọn vẹn.
  - Số dư ví chuyển sang số âm: `10.000 - 30.000 = -20.000 VNĐ` (thể hiện nợ tiền sạc).
  - Cả hai dòng debit được ghi nhận đầy đủ vào `wallet_ledger`.
  - Cả 2 phiên đều được đánh dấu `debited` và lưu mốc thời gian hoàn tất chốt phiên.

### Kịch bản 4: Lỗi giữa chừng rollback toàn bộ, không mồ côi hoá đơn
- **Hàm test**: `test_t103_loi_giua_chung_khong_de_lai_hoa_don_mo_coi`
- **Mô tả hành vi**:
  - Giả lập lỗi cơ sở dữ liệu bất ngờ (`SQLAlchemyError`) tại bước trừ ví (`tru_vi`).
- **Kỳ vọng nghiệm thu**:
  - Toàn bộ transaction bị rollback sạch sẽ:
    - Không tồn tại hoá đơn mồ côi trong bảng `invoices` cho phiên sạc này.
    - Không tồn tại dòng trừ tiền mồ côi trong `wallet_ledger`.
    - Trạng thái phiên sạc không bị gắn nhãn hoàn tất (`settlement_completed_at IS NULL`).
  - Khi khắc phục lỗi và gọi chốt lại, phiên sạc được xử lý thành công trọn vẹn.

---

## 3. Nghiệm thu Stress Test 50 lần liên tục
- **Hàm test**: `test_t103_nghiem_thu_50_lan_dong_thoi_khong_sai_lech`
- **Thiết kế kiểm thử**:
  - Chạy lặp lại 50 chu kỳ kiểm thử liên tiếp trên kết nối PostgreSQL thực.
  - Ở mỗi vòng lặp:
    1. Kích hoạt đồng thời 2 tiến trình cùng chốt phiên `s1` (race condition double-closure).
    2. Song song đó, chốt đồng thời phiên `s2` của cùng tài xế (concurrent session settlement).
  - Kiểm tra số dư ví giảm chính xác sau từng vòng lặp: `current_balance = prev_balance - (inv1 + inv2)`.
  - Sau trọn vẹn 50 vòng lặp:
    - Tổng sổ cái `sum(WalletLedger.amount_vnd)` khớp tuyệt đối với số dư ví `wallet.balance_vnd`.
    - 50/50 chu kỳ không có bất kỳ sai lệch hay tranh chấp lỗi cơ sở dữ liệu nào.

---

## 4. Bằng chứng Thực thi (Test Execution Evidence)

```powershell
# Chạy bộ kiểm thử đồng thời T-103
.venv\Scripts\python.exe -m pytest tests/test_t103_concurrency.py -v
```

**Kết quả thực tế:**
```text
tests/test_t103_concurrency.py::test_t103_hai_phien_cung_tai_xe_chot_dong_thoi PASSED [ 20%]
tests/test_t103_concurrency.py::test_t103_hai_tien_trinh_cung_chot_mot_phien_race_condition PASSED [ 40%]
tests/test_t103_concurrency.py::test_t103_vi_thieu_tien_van_tru_de_so_du_am PASSED [ 60%]
tests/test_t103_concurrency.py::test_t103_loi_giua_chung_khong_de_lai_hoa_don_mo_coi PASSED [ 80%]
tests/test_t103_concurrency.py::test_t103_nghiem_thu_50_lan_dong_thoi_khong_sai_lech PASSED [100%]

======================= 5 passed, 4 warnings in 18.51s ========================
```

**Kiểm tra chất lượng mã nguồn:**
- `ruff check .` -> *All checks passed!*
- `ruff format --check .` -> *359 files already formatted*
- `mypy src` -> *Success: no issues found in 114 source files*
