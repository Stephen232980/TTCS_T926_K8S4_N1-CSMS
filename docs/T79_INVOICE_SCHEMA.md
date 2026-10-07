# T-79 — Schema hoá đơn (S-33)

`Invoice` và `InvoiceLine` nằm trong `src.modules.billing.models`. Migration
`e120013a2026` nối `c100011a2026`. Không có API, hàm tính tiền hay chốt phiên trong task này.

## Hợp đồng cho T-80/T-81/T-102

- `invoices`: UUID, session_id unique, driver_id, station_id, total_vnd BIGINT
  không âm, rounding_rule văn bản không rỗng, created_at timestamp có múi giờ.
- `invoice_lines`: UUID, invoice_id, line_type `energy`/`idle`, local_date theo
  múi giờ trạm, started_at/ended_at timestamp có múi giờ (lưu UTC),
  energy_wh NUMERIC(24,6), rate_vnd BIGINT, band_label, interpolated,
  tariff_id, amount_vnd BIGINT. Energy dùng đồng/kWh; idle dùng đồng/phút và
  energy_wh=0. Cho phép nhiều dòng điện cùng phiên, qua ngày hoặc qua biểu giá.
- Tiền là nguyên đồng; đơn vị Wh giữ phần thập phân cho nội suy. Làm tròn và
  tổng bằng tổng các dòng thuộc T-80; không tự tính lại khi đọc hoá đơn.
- T-80 phải kiểm phiên/tài xế/trạm/biểu giá cùng nguồn, gọi
  `danh_dau_bieu_gia_da_dung` và ghi snapshot trong cùng giao dịch. Các FK bảo vệ
  sự tồn tại; schema này không thay thế kiểm tra nghiệp vụ và tổng tiền của T-80.
- `charging_sessions.settlement_completed_at` và `settlement_reason` mặc định
  NULL. Cả hai cùng NULL hoặc cùng có giá trị; reason chỉ nhận `debited`,
  `zero_invoice`, `legacy_exempt`. T-81 không đặt hai cột ngay sau lập hoá đơn;
  T-102 đặt sau hoàn tất thanh toán trong cùng giao dịch. Migration miễn dữ liệu
  cũ và mốc chuyển đổi thuộc T-102, không chạy ở T-79.

## Bất biến và quyền database

Trigger chặn UPDATE/DELETE/TRUNCATE cả hai bảng, kể cả TRUNCATE CASCADE từ
bảng cha và tài khoản chủ bảng thông thường. FK RESTRICT giữ phiên, tài xế,
trạm và biểu giá đang được hoá đơn tham chiếu. Quản trị có quyền sửa DDL vẫn
có thể gỡ trigger; ứng dụng không được có quyền quản trị database.

Với runtime role tách khỏi migration owner, chạy bằng migration owner:
`psql -v app_role=<runtime_role> -f scripts/grant_invoice_evidence.sql`.
Script cấp SELECT/INSERT và thu hồi quyền sửa/xoá; UUID không cần sequence.
Không đổi secrets hoặc grant trên demo/staging trong triển khai local này.

## Migration và phạm vi còn mở

Upgrade không tạo hoá đơn và không sửa dữ liệu phiên cũ. Downgrade gỡ bảng
hoá đơn, hai cột thanh toán và trigger/function: **mất dữ liệu hoá đơn/thanh toán**.
Chỉ dùng rollback này trên database thử hoặc sau khi có phương án sao lưu được
chấp thuận. Test round-trip giữ dữ liệu phiên sạc cũ.

Giữ unique theo phiên. Phí sau StopTransaction/hoá đơn bổ sung chưa được chốt,
không thay đổi thiết kế ở task này. T-85 đang có migration riêng cùng parent;
PR merge sau phải nối lại down_revision và cập nhật test head để giữ một Alembic head.
