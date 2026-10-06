# Kiểm tra CI của PR simulator — 06/10/2026

Log GitHub Actions người dùng cung cấp có một lỗi gốc: bài
`test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms`
đo 219,6 ms, vượt ngưỡng 200 ms; 407 bài khác đạt.

Job `simulator-scenario` phụ thuộc `quality`, nên quality thất bại làm
kịch bản S-26 bị bỏ qua. Required check `Build Docker image` có `if: always()`
và kiểm kết quả cả hai dependency, vì vậy cũng thất bại. Đây không phải
bằng chứng simulator S-26 đã chạy và gặp lỗi.

## Thay đổi

Đường xử lý MeterValues đọc phiên và số đo gần nhất của mỗi chuỗi trong
một truy vấn PostgreSQL LATERAL, thay cho hai lượt truy vấn riêng.
Chỉ đọc các trường số đo cần so sánh, không tạo đối tượng ORM cho lịch sử
số đo. Truy vấn vẫn kiểm trụ, đầu nối, transactionId và khóa phiên.

Snapshot được chuyển vào bộ xử lý số đo hiện có. Giữ việc kiểm timestamp,
chống trùng, cảnh báo công tơ giảm, xử lý pending, backfill phục hồi và
commit cache phản hồi cùng dữ liệu trước khi gửi CALLRESULT.

Không đổi ngưỡng 200 ms, pool database, tính bền vững giao dịch hoặc
cơ chế required check. Không thay workflow và không thêm retry cho bài đo.
Chưa xác định chính xác nguyên nhân biến động hiệu năng trên runner remote;
giảm lượt truy vấn không phải cam kết mọi môi trường đều đạt cùng độ trễ.

## Kiểm chứng

- Ruff lint/format toàn dự án và mypy src đạt.
- Bài đo riêng Windows sau thay đổi đạt 96 ms; chạy cùng nhóm regression
  có lượt 217 ms, nên kết quả riêng không đủ để kết luận CI đã được sửa.
- Linux/Python 3.12, database kiểm thử riêng: 407 bài đạt. Một bài kiểm tra
  cấu hình Compose bị skip do container không có Docker CLI; chạy bài ấy
  riêng trên host có Docker Compose và đạt. Tổng 408 bài tương ứng PR.
- S-26 chạy trong project Docker riêng với source đã sửa, OCPP 2.1.0 và
  WebSockets 15.0.1: verifier exit 0, log
  `S-26 verified 20/20 online chargers and sessions.`
- Kịch bản Docker dùng image kiểm chứng từ dependencies local đã cài,
  không phải một bản chạy GitHub Actions trên runner remote.

Sau khi push commit sửa, cần xác nhận lại quality, simulator-scenario và
required build check trên GitHub Actions. Kết quả local không thay CI remote.
