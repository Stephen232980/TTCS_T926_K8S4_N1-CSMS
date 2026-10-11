# S-35: đối soát VNPAY QueryDR

Đào Minh Tâm đã đồng ý bổ sung QueryDR để xử lý đơn cũ 100.000 VND còn
pending sau khi thanh toán sandbox, ngày 11/10/2026. Đây là mở rộng đối soát
do quản trị viên thực hiện. Luồng thanh toán thường vẫn dùng IPN có chữ ký;
Return và timeout không được làm căn cứ cộng tiền hoặc kết luận thất bại.

## Cách dùng sau merge và deploy

Backend cần `VNPAY_QUERY_IP` là IP public của máy chủ gọi QueryDR. Staging:
23.100.101.246. Merchant và HashSecret dùng cấu hình backend hiện có, không
nhập lại qua API. Compose chỉ thêm biến này; không đổi workflow hoặc Caddy.

Tại terminal SSH, xem kết quả trước:

```bash
docker exec -it csms-app python -m scripts.reconcile_vnpay_topup --order vnpay1c461b44240b4bf393ccb45c8277338d
```

Nhập tài khoản **quản trị viên CSMS**, không phải tài khoản SIT. Mật khẩu được
ẩn khi nhập; phiên chỉ nằm trong bộ nhớ và được logout khi kết thúc. `--help`
chỉ in hướng dẫn, không đăng nhập hay sửa dữ liệu. Mặc định chỉ xem kết quả.

Nếu `query_response_code=00`, `transaction_status=00`, không cần review,
áp dụng bằng cùng lệnh thêm `--apply`:

```bash
docker exec -it csms-app python -m scripts.reconcile_vnpay_topup --order vnpay1c461b44240b4bf393ccb45c8277338d --apply
```

Lần đầu dự kiến `status=succeeded`, `applied=true`. Chạy lại hoặc IPN đến
sau đó không cộng thêm. Đăng nhập lại tài xế, làm mới ví: tăng đúng 100.000 VND
và thêm đúng một dòng nạp của đơn cũ. Nếu ví trước đó 100.000 thì thành 200.000;
đối chiếu số dư thực tế ngay trước áp dụng, không giả định không có hoạt động khác.
Thông báo pending của đơn cũ phải chuyển sang thành công khi kiểm tra trạng thái.

Endpoint cho ứng dụng quản trị:
`POST /api/v1/admin/payments/vnpay/topups/{order_id}/reconcile`, cookie session
admin, body `{"apply": false}` hoặc `{"apply": true}`. Quyền
`admin.wallet.topup.reconcile`, phạm vi all; vai trò khác bị từ chối trước gọi
VNPAY. Chưa thêm nút giao diện quản trị trong bản này.

## Quy tắc bảo toàn số tiền

- Request/response QueryDR dùng HMAC-SHA512 theo thứ tự trường nối bằng `|`,
  khác chữ ký PAY/IPN. URL sandbox cố định, timeout 10 giây, không theo redirect,
  giới hạn response 32 KiB và từ chối JSON có khóa lặp.
- Xác thực chữ ký rồi đối chiếu merchant, order, loại thanh toán `01`, số tiền
  và mã giao dịch. `vnp_ResponseCode=00` chỉ là truy vấn thành công; dùng
  `vnp_TransactionStatus` để quyết định kết quả thanh toán.
- Trạng thái `00` đi qua settlement chung với IPN; `02` ghi failed, không cộng
  tiền. `01` chưa hoàn tất, `04` đảo, trạng thái hoàn tiền/gian lận hoặc trạng
  thái khác không tự kết thúc đơn. `91` không tìm thấy, `94` rate limit và lỗi
  truy vấn cũng không chứng minh thanh toán thất bại.
- Sai số tiền đi vào needs_review khi yêu cầu apply; preview không đổi trạng
  thái. Các xung đột/late success/đơn đã needs_review giữ quy tắc settlement
  hiện có, không cho quản trị viên ép ghi đè kết quả.
- Query và IPN dùng cùng khóa hàng, gateway ID và ledger duy nhất. Không giữ
  khóa DB khi chờ HTTP; áp dụng sẽ đọc/khóa lại trạng thái mới nhất. Audit và
  cập nhật ví commit cùng transaction; lỗi commit rollback cả hai.
- Audit ghi actor, quyền, vai trò, request ID, thời gian truy vấn, mã kết quả,
  trạng thái trước/sau và có áp dụng hay không. Không lưu khóa, cookie, chữ ký
  hoặc nguyên response provider. Lỗi truy vấn có audit theo nhóm lỗi cố định.

PAY mới dùng `wallet_topups.created_at` (GMT+7, đến giây) cho vnp_CreateDate;
QueryDR dùng cùng giá trị. Không cần migration hoặc backfill. Đơn cũ có thể
có vnp_CreateDate lệch thời điểm DB; nếu VNPAY trả 91, đối chiếu request PAY
gốc rồi dùng `--transaction-date YYYYMMDDHHMMSS`, không thử hàng loạt thời gian.
Ngày có định dạng hợp lệ chỉ là đầu vào truy vấn; vẫn phải xác minh response.

## Bằng chứng và phần còn chờ

Ngày 11/10/2026 đã gọi **QueryDR thật chỉ đọc** cho đơn cũ bằng cấu hình đang
chạy trên staging: transaction_date=20261011151040, chữ ký hợp lệ,
query_response_code=00, transaction_status=00, amount_vnd=100000.
CSMS vẫn pending tại thời điểm kiểm tra; chưa apply, chưa thay đổi ví.

Sau merge/deploy phải preview lại rồi apply, kiểm tra một ledger/số dư/trạng
thái và audit admin. Kết quả chỉ đọc không chứng minh nghiệm thu apply trên VM.
Bản này không có refund, job tự động, production hoặc sửa trực tiếp DB.

Nguồn giao thức:
[VNPAY QueryDR](https://sandbox.vnpayment.vn/apis/docs/truy-van-hoan-tien/querydr&refund.html).
