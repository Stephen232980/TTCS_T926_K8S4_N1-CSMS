# T-88 API nạp ví thủ công

T-88 thuộc S-36, cung cấp API nạp theo phiếu thu cho admin. Màn hình xác nhận
hai bước thuộc T-89. Nguồn phạm vi: Backlog CSMS S-36 và dòng T-88 cùng quyết
định số 7 của Chia_viec_Sprint_4-5_cap_nhat.xlsx.

## Giao dịch và nhật ký

Service khoá dòng ví, kiểm phiếu, gọi `ghi_so_cai` rồi `ghi_nhat_ky` trong
cùng giao dịch. Router chỉ commit khi cả hai xong. Unique của sổ cái bảo vệ
phiếu giữa các ví; yêu cầu trùng trả 409, không phát lại kết quả thành công.
Hai phiếu khác nhau cho cùng ví không mất cập nhật.

T-88 dùng `audit_logs` và helper `src.platform.audit.service.ghi_nhat_ky`
đã merge trong T-57 A. Không thêm bảng, helper hoặc migration audit riêng.
Audit ghi `action=wallet.manual_topup`, `object_type=wallet`, `object_id`
là UUID ví dạng chuỗi; JSON chỉ có `ledger_id`, `amount_vnd`, `receipt_code`.
Actor, permission và snapshot actor_roles được ghi ngoài JSON. Nguồn chi
tiết là wallet_ledger; audit là chỉ mục tham chiếu, cùng commit/rollback.

Không sao chép tên, email, điện thoại, token hoặc IP vào audit. Service
chịu trách nhiệm một dòng audit cho mỗi nạp thành công; không có unique
riêng theo ledger_id ở audit_logs. Quyền database và trigger bất biến dùng
nền tảng T-57 A. Màn hình S-56, T-57 B, T-87 và T-89 ngoài phạm vi.

## Ma trận kiểm chứng

| AC/NFR | Cài đặt | Kiểm chứng |
| --- | --- | --- |
| Nạp 500.000 đồng, một dòng sổ và nhật ký | Giao dịch service và router | HTTP 201, kiểm balance, actor, receipt và hai bảng |
| Phiếu đã dùng bị chặn | Khoá ví, kiểm phiếu và unique sổ cái | Replay cùng/khác tiền và hai request đồng thời cùng/khác ví |
| Chỉ quản trị được nạp | Policy all/admin và kiểm admin hoạt động | Anonymous, các role khác và admin bị vô hiệu |
| Số tiền nguyên dương, tối đa cấu hình | Strict schema và service | Âm, 0, boolean, số lẻ, chuỗi, ngoài BIGINT, vượt/đúng mức cấu hình |
| Nhật ký bất biến | Bảng audit_logs, trigger và runtime grants | UPDATE/DELETE/TRUNCATE bị từ chối |
| Tiền và nhật ký cùng giao dịch | Savepoint và commit cuối request | Lỗi sau flush audit/ledger không để lại số dư, sổ cái hoặc audit |
| Không mất nạp đồng thời | Khoá ví | Hai phiếu khác nhau đều tăng số dư |
| Không thêm schema trùng | Dùng T-57 A | Một head b150015a2026, không có migration riêng T-88 |

Đây là bằng chứng local cho T-88, không phải nghiệm thu toàn bộ S-36,
S-56, CI hay staging.

## Kiểm chứng local ngày 08 tháng 10 năm 2026

Baseline `develop`: `3042656` đã merge T-57 A. Phần audit riêng chưa commit
của T-88 cũ đã bỏ, không chạy migration a140015a2026. Dùng database mới
riêng để kiểm chứng schema dùng chung.

- 67 test tập trung cho nạp tay, schema ví, migration chain và inventory
  quyền đạt, bao gồm lỗi sau flush audit và sau flush ledger.
- Bộ hồi quy theo cấu hình CI: 737 passed, 2 deselected (hai ca latency
  tách riêng), 4 cảnh báo deprecation có sẵn.
- Upgrade từ database rỗng đạt, một head b150015a2026; không có migration
  riêng T-88. Không thay schema T-57 đã merge.
- Ruff toàn source/tests/migrations đạt; format check 182 file đạt;
  mypy 88 file source và git diff check đạt.

Không thay đổi database ứng dụng; kiểm chứng dùng container thử riêng và
database tạm. Chưa commit/push, chưa có kết quả CI hoặc review cho T-88.
