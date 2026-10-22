# Rà soát màn kế toán — 19/10/2026

## Phạm vi sửa nhỏ đã làm
- Nhánh riêng fix/accountant-reconciliation-ui-20261019 từ develop df2c704.
- Bỏ (S-53) ở sidebar và tiêu đề đợt đối soát.
- CSV doanh thu chỉ nằm ở danh sách Phiên sạc & thanh toán; không hiện ở chi tiết phiên, Hóa đơn, Cần đối chiếu hoặc Đợt đối soát. CSV sai lệch vẫn ở chi tiết đợt đối soát.
- Sửa lỗi CSV sai lệch: kết quả SQLAlchemy là Row, không phải tuple/list; trước sửa đọc issue.details gây AttributeError, sau sửa endpoint trả 200.

## Kết quả kiểm tra
- Staging chỉ đọc: reconciliation_runs = 0, invoices = 192. Quyền csms_runtime có INSERT và UPDATE trên reconciliation_runs. Không tạo đợt hoặc sửa dữ liệu staging.
- PostgreSQL 16 riêng, migration đến m170029a2026: POST tạo run 201, GET issues 200, CSV sau sửa 200. Tạo dữ liệu minh họa có sai lệch và kiểm tra API thật; auth được thay bằng actor kế toán trong test, không coi đây là bằng chứng login staging.
- 19 test backend đối soát đạt, gồm regression SQL thật/API/CSV. 25 test frontend FinancePage/ReconciliationRunsView đạt. Frontend lint/build, Ruff/format và mypy được kiểm tra riêng.

## Đánh giá phần lõi: mức vừa/lớn, chưa triển khai khi chưa có quyết định
1. cutoff_at được ghi và đưa vào hash nhưng truy vấn input không giới hạn theo cutoff. Probe với đồng hồ cố định 01/10 vẫn nhận hóa đơn tạo sau 01/10 trong kỳ tháng 10.
2. GET chi tiết sai lệch join email tài xế, tên trạm và phiên hiện tại. Đổi email trong DB thử nghiệm làm email trong đợt cũ đổi theo. Các số tổng và số tiền sai lệch đã được lưu; không kết luận các số tiền tự đổi theo.
3. Bảng run chưa có bảo vệ sửa dữ liệu ở DB: UPDATE bản tổng hợp trong transaction thử nghiệm được chấp nhận (đã rollback); role runtime trên staging cũng có quyền UPDATE. Chưa có endpoint sửa run, nên đây là thiếu bảo vệ dữ liệu lịch sử, không phải khẳng định UI đang sửa run.

Đề xuất PR lõi riêng: snapshot đầy đủ trường chứng cứ phục vụ tra cứu, nguồn đọc nhất quán và áp mốc chốt thật, khóa sửa run/issues theo quyền/DB, tests commit/reload và cạnh tranh ghi. Không sửa chứng từ hoặc số dư trong luồng đối soát. Không gộp S-54/S-55 vào việc này.

Kết luận: luồng tạo/xem/phát hiện sai lệch đã chạy được; chưa đủ kết luận đợt đối soát hoàn toàn bất biến theo mốc chốt. Ảnh 0 đợt phản ánh chưa có lịch sử chạy trên staging, không chứng minh chức năng hỏng.

Quyết định của người dùng: chỉ sửa giao diện/CSV trong PR này; để lõi đối soát xử lý sau. Không thực hiện thay đổi snapshot/cutoff/schema/quyền DB.
