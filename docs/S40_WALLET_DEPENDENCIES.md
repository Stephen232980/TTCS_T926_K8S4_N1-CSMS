# S-40 — ví, sổ cái và chi tiết lần nạp

API ví dùng tài xế đang đăng nhập; query driver_id/wallet_id bị từ chối 403.
GET /api/v1/driver/wallet/transactions mặc định 50 dòng, tối đa 50, cursor
là mã dòng cuối; insert mới không làm trùng/sót các trang cũ.

GET /api/v1/driver/wallet/transactions/{entry_id} đọc dòng sổ cái đã lưu,
404 nếu không có, 403 nếu thuộc ví khác. Không ghi, cộng tiền hoặc chốt phiên.
Chi tiết gồm loại, số tiền, số dư sau, thời điểm, tham chiếu. Gateway top-up
được nối tới wallet_topups theo driver_id và gateway_transaction_id, trả
thêm topup_order_id/topup_status/topup_reason. Không suy mã đơn từ chuỗi mã
cổng; dữ liệu cũ không có lệnh tương ứng vẫn hiển thị chứng từ sổ cái.
Nạp tay hiển thị mã phiếu và thời điểm đã ghi nhận. Mã phiên sạc số nguyên
mở API phiên có kiểm quyền và có đường xem hóa đơn.

Mọi trường tiền trong response ví, list và detail (balance_vnd/balance,
debt_amount_vnd/debt_amount, amount_vnd/amount, balance_after_vnd/balance_after)
là **chuỗi decimal số nguyên đồng** qua JSON để giữ chính xác miền BIGINT.
DB và mô hình nội bộ vẫn là số nguyên; request nạp tiền vẫn dùng hợp đồng
hiện có. Client cần đọc chuỗi bằng BigInt/Decimal/int, không chuyển sang Number.
Frontend ví chấp nhận giá trị số legacy và chuỗi .00 legacy nhưng API mới
trả chuỗi số nguyên. Alias không còn là số JSON; thay đổi này được khai trong
OpenAPI và tests của client HTTP được cập nhật.

Màn hình ví không dùng một ngưỡng khởi động giả cố định cho mọi trạm. Ngưỡng
thực tế xuất hiện ở bước chọn đầu nối và do backend eligibility quyết định.
Return không coi lỗi 404/auth là đang chờ IPN. Chỉ webhook/đối soát xác thực
mới cộng tiền; đọc chi tiết hoặc mở trang quay về không thay đổi tài chính.
