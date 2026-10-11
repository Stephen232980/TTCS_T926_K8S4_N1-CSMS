# S-35: VNPAY PAY 2.1.0 sandbox

Quyết định ngày 11/10/2026: hoàn thiện AC sandbox gốc của S-35 trong Sprint
4–5. Ghi chú trước đây hoãn adapter sang S-67 được thay bằng phạm vi này;
không làm một adapter trùng ở S-67. FakeGateway vẫn dành cho local/CI.

## Luồng

T-93 tạo đơn pending trước khi tạo URL. Chế độ `sandbox` chọn VNPAY và dùng
order_id `vnpay<uuid>`; IPN không chấp nhận đơn FakeGateway cũ.
Backend ký query đã sắp xếp/form-encode bằng HMAC-SHA512, tiền VND nhân 100,
thời gian Asia/Ho_Chi_Minh, hết hạn mặc định 15 phút. IP khách lấy từ peer
đã được Uvicorn xác minh, không đọc X-Forwarded-For tùy ý trong handler.

- URL thanh toán: https://sandbox.vnpayment.vn/paymentv2/vpcpay.html
- Return: https://csms-staging.daominhtam2k6.id.vn/api/v1/payments/vnpay/return
- IPN: https://csms-staging.daominhtam2k6.id.vn/api/v1/payments/vnpay/ipn
- Trang trạng thái: https://csms-staging.daominhtam2k6.id.vn/wallet/topup/return

Return kiểm chữ ký rồi chuyển đến trang trạng thái T-94 với order_code.
Không ghi DB, không cộng ví, không lấy status URL làm bằng chứng. T-94 hỏi
API có bảo vệ chủ ví, tiếp tục hiển thị pending và làm mới ví khi IPN hoàn tất.
Đăng nhập cookie Secure vẫn dùng SameSite=Lax để quay về từ cổng.

IPN GET là server-to-server, không yêu cầu đăng nhập/CSRF. Kiểm chữ ký trước
merchant/mã đơn/số tiền/trạng thái. Thiếu/trùng/tamper query bị từ chối.
Chỉ thành công khi cả ResponseCode và TransactionStatus là 00; hai trường
mâu thuẫn không cộng ví. Mã 24 là cancelled; mã khác lưu failed kèm lý do cố
định theo code. TransactionNo thành công phải khác 0. TransactionNo=0 của
đơn thất bại được tham chiếu riêng theo đơn, không gây trùng mọi đơn thất bại.

IPN tái sử dụng transaction/row lock/idempotency/audit T-95–T-97. Commit
trước trả lời. Dữ liệu bất thường giữ needs_review, không tự phục hồi/cộng tiền.
Router xóa query khỏi scope trước xử lý để access log Uvicorn không ghi chữ ký;
không bật access log chứa full URL cho IPN/Return ở proxy ngoài.

| Trường hợp IPN | HTTP | RspCode |
| --- | --- | --- |
| Ghi nhận kết quả hợp lệ lần đầu | 200 | 00 |
| Đã xác nhận, callback lặp khớp | 200 | 02 |
| Không có đơn | 200 | 01 |
| Số tiền lệch | 200 | 04 |
| Chữ ký thiếu/sai | 200 | 97 |
| Payload lỗi/mâu thuẫn, cần review hoặc DB lỗi | 200 | 99 |

Đây là giao thức VNPAY: HTTP 200 không có nghĩa đã cộng tiền. S-39 generic
JSON webhook vẫn giữ HTTP 401/404 cũ; nghiệm thu adapter VNPAY đối chiếu
RspCode tương ứng. Callback lặp không được cộng thêm dù nhận RspCode 02.

## Chuẩn bị staging

DNS và Caddy HTTPS đã được người dùng kiểm tra; không cần chuyển cổng frontend
80, không đổi workflow/build/deploy. Caddy nằm cùng mạng Docker, /api/ chuyển
thẳng đến csms-app:8000. Chứng chỉ lưu volume riêng, không xóa khi deploy app.

Tệp cấu hình staging đã được kiểm tra tại `/home/deploy/.env` ngày 11/10/2026.
Sau merge PR #125, backend đã deploy chế độ sandbox và cookie Secure=true.
Không tạo .env trong /home/azureadmin hoặc bỏ mất DATABASE_URL hiện có.
Sau khi PR merge, lấy scripts/configure_vnpay_staging.py từ commit đã review
vào /tmp/configure_vnpay_staging.py và chạy bằng deploy để giữ quyền sở hữu:

```bash
sudo -u deploy python3 /tmp/configure_vnpay_staging.py --env-file /home/deploy/.env
```

Script hỏi TmnCode và HashSecret tại terminal, ẩn khóa khi nhập. Nó lưu backup
private, giữ biến khác, bật AUTH_COOKIE_SECURE và chỉ tin IP Docker hiện tại
của csms-https qua FORWARDED_ALLOW_IPS. Không restart, deploy hoặc in khóa.
HashSecret VNPAY dùng PAYMENT_WEBHOOK_SECRET, khác khóa fake; không đặt trong
frontend/Git/chat. Khi tạo lại container Caddy làm IP đổi, chạy cấu hình lại
và deploy backend để cập nhật peer tin cậy.

Thực hiện deploy backend theo quy trình CI/CD sau khi cấu hình đã lưu. Cần
kiểm tra candidate/readiness, login HTTPS, và POST tạo đơn trước mở cổng thật.
Không tái sử dụng đơn pending FakeGateway để test VNPAY. Không chạy bộ pytest
trên DB staging. QueryDR/refund, đối soát tự động và production không thuộc PR.

Khóa thật không nằm trong repository. Ngày 11/10/2026, ảnh SIT ghi nhận 5/6
ca đạt; ví hiển thị đúng một dòng +50.000 VND với tham chiếu vnpay:15701350.
Ca không tìm thấy đơn trả 99 thay vì 01 do kiểm tra mã theo mẫu UUID nội bộ.
Bản sửa xác thực chữ ký trước, nhận mã ASCII alphanumeric dài 1–100 theo
giao thức VNPAY, rồi tra cứu để trả 01 nếu không có đơn. Mã không đúng định
dạng vẫn trả 99. Không đổi cách sinh mã đơn hoặc quy tắc cộng tiền.
Sau deploy bản sửa phải chạy lại SIT; không chuyển S-35 Done chỉ dựa trên CI.

## Nghiệm thu với VNPAY

1. Đăng ký IPN HTTPS trên với VNPAY/SIT theo email merchant, dùng tài khoản
   SIT riêng; không gửi mật khẩu vào chat.
   Theo hướng dẫn SIT, tạo hai đơn mới: chọn thẻ nội địa/ATM → NCB, nhập dữ
   liệu thẻ TEST, dừng tại màn hình OTP rồi đóng cửa sổ, không thanh toán/hủy.
   Dùng các phiên ẩn danh riêng cho dữ liệu SIT khi giao diện giữ đơn pending;
   không xóa hoặc sửa trạng thái đơn cũ. Chọn đúng terminal trên SIT, chọn một
   đơn cho ca thành công và đơn còn lại cho ca thất bại, chạy Tiến hành kiểm tra.
2. Đăng nhập tài xế thử; nạp 50.000 VND, kiểm tra chuyển đúng sandbox và order
   pending, ví chưa tăng trước IPN.
3. Thanh toán bằng dữ liệu thử chính thức VNPAY; Return hiển thị trạng thái
   backend, sau IPN ví tăng đúng 50.000 và có một ledger.
4. Gửi lại IPN hợp lệ ít nhất 5 lần bằng SIT: trả 02 sau lần đầu, ví/ledger
   không tăng thêm. Lưu bằng chứng đã che chữ ký/khóa/thông tin thẻ.
5. Kiểm tra sai chữ ký (97), đơn không tồn tại (01), lệch tiền (04), failed/
   cancelled, quay về trước IPN và IPN đồng thời. Xác nhận không cộng sai.
6. Sau một lần deploy tiếp theo, HTTPS/login/IPN vẫn hoạt động.

Đơn 100.000 VND tạo trước khi chuẩn bị SIT vẫn pending theo ảnh ngày
11/10/2026; nó khác hai đơn SIT. Không suy ra thất bại từ timeout hoặc suy ra
thành công từ Return. Cần IPN hợp lệ hoặc quy trình đối soát với VNPAY trước
khi chốt trạng thái; bản sửa SIT không cập nhật thủ công đơn này.

## Tài liệu chính thức

- [PAY/IPN/Return và mã phản hồi](https://sandbox.vnpayment.vn/apis/docs/thanh-toan-pay/pay.html)
- [Mã lỗi](https://sandbox.vnpayment.vn/apis/docs/bang-ma-loi/)
- [SIT](https://sandbox.vnpayment.vn/vnpaygw-sit-testing/user/login)

tests/test_vnpay_sandbox.py kiểm wire format, tamper, merchant/amount,
Return không settlement, IPN thực với PostgreSQL và 5 callback đồng thời.
Các test fake T-90/T-93/T-95/T-96/T-97/T-98 giữ nguyên và được chạy hồi quy.
Đây là kiểm chứng local/CI; không thay thế giao dịch từ máy chủ VNPAY sandbox.
