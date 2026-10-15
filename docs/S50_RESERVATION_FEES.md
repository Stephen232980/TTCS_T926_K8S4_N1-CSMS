# S-50 — Quá hạn đặt chỗ và phí không đến

G6 mở rộng G5 (S-48/S-49/S-51), dùng ví và sổ cái hiện có. Không phụ thuộc cấu hình SMTP.

## Chính sách và chấp nhận

- Owner chỉ xem/sửa chính sách trạm thuộc mình qua `GET/PUT /api/v1/owner/stations/{id}/reservation-policy`.
- `fee_vnd` là số nguyên 0–1.000.000 VND, mặc định 0; `expected_version` chống ghi đè thay đổi đồng thời. Đề xuất demo 10.000 VND, owner quyết định mức thực tế.
- Driver đọc `GET /api/v1/driver/reservations/policy?connector_id=UUID`. Khi phí dương, phải đồng ý mức phí và gửi `accepted_fee_vnd`, `accepted_policy_version` lúc đặt. Chính sách đã đổi trả 409, yêu cầu đọc và chấp nhận lại.
- Đặt chỗ lưu snapshot phí/version, kiểm tra số dư tối thiểu bắt đầu sạc cộng phí. Không giữ hay trừ tiền khi đặt; không miễn lần đầu. Idempotency key gắn với người dùng và payload, retry không tạo thêm đặt chỗ.
- Đặt chỗ cũ được migration gán `legacy_exempt`, phí 0, không thu hồi tố. Thay đổi chính sách chỉ ảnh hưởng đặt chỗ mới.

## Quá hạn và thu phí

Worker phí chạy mỗi 15 giây, chờ thêm 30 giây sau hạn giữ để nhận StartTransaction đến chậm. Worker hết hạn gửi CancelReservation và retry theo cơ chế G5; việc xác định phí độc lập với ACK hủy. Chỉ giải phóng đầu nối khi có bằng chứng G5 chấp nhận, không dựa trên ý định hủy.

Chỉ thu phí dương cho đặt chỗ đã được trụ xác nhận, có bằng chứng online/capability phù hợp, không lỗi, có liên lạc từ trụ sau hạn giữ và chưa bắt đầu phiên. Mất kết nối, trạm ngừng hoạt động hoặc bằng chứng không chắc chắn không tự động phạt: ghi miễn phí hoặc cần kiểm tra theo nguyên nhân. Hủy đúng hạn, đã dùng đặt chỗ, ReserveNow bị từ chối/chưa gửi và phí 0 không tạo bút toán phí.

Khóa theo thứ tự trụ → trạm → đầu nối → đặt chỗ → ví. Bút toán `reservation_fee` âm, reference_type `reservation`, reference_id UUID đặt chỗ, cập nhật số dư, quyết định phí, sự kiện và audit cùng transaction. Unique ledger reference và khóa chống thu lại khi hai worker chạy đồng thời, scan lại hoặc khởi động lại. Phí 0 không tạo ledger 0. Cho phép ví âm sau phí; điều kiện số dư hiện có chặn lần bắt đầu sạc tiếp theo.

StartTransaction có thời gian nguồn trước hạn nhưng đến trong 30 giây có thể dùng đặt chỗ sau ACK hủy nếu đầu nối chưa được giữ bởi đặt chỗ khác. Đến sau khoảng chờ thì từ chối mở phiên và chuyển cần kiểm tra, lưu source timestamp, received time và message id. Nếu đã thu phí, giữ nguyên bút toán; không tự xóa/hoàn phí. Admin xử lý bằng luồng điều chỉnh ví hiện có, có lý do và audit.

## Giao diện và vận hành

Owner có mục Chính sách phí không đến. Driver thấy phí trước khi gửi, xác nhận rõ điều kiện thu và khả năng ví âm; chi tiết đặt chỗ hiển thị snapshot/kết quả. Lịch sử ví ghi Phí không đến và liên kết về đúng đặt chỗ.

Migration `e250025a2026` nối `d240024a2026`, giữ một Alembic head. Downgrade bị chặn khi có ledger reservation_fee để bảo vệ sổ cái; không xóa dữ liệu tiền để ép rollback. Cấu trúc gateway OCPP vẫn là một tiến trình kết nối trụ như hệ thống hiện tại; không tuyên bố hỗ trợ gateway phân tán.

## Bằng chứng kiểm tra local

Kiểm thử PostgreSQL thật bao phủ hai worker/năm scan, snapshot, số dư âm, rollback khi audit lỗi, không phạt khi offline/thiếu liên lạc sau hạn, hủy/consume, StartTransaction chậm, quyền owner, đồng ý/version, miễn đặt chỗ cũ và upgrade → downgrade → upgrade. Regression G5 bao gồm OCPP TCP thật tới simulator và đóng phiên tự động. Kiểm thử hiệu năng 20 socket đạt dưới 200 ms; không thay đổi đường MeterValues.

Ảnh UI local dùng tài khoản/dữ liệu demo và rút ngắn timeline một đặt chỗ trong DB disposable để quan sát worker. Đây là bằng chứng giao diện và luồng local, không thay thế nghiệm thu phần cứng hoặc staging. CI/CD và triển khai do người dùng kiểm tra riêng.

## S-19 — Phản hồi số đo

Báo cáo thường và dữ liệu gửi bù sau reconnect ghi các số đo hợp lệ theo lô tối đa 1.024 dòng/câu lệnh, không cần trả về ID từng số đo. Kiểm tra timestamp, đơn vị, hồi quy và trùng giữ nguyên. Dữ liệu cùng durable reply vẫn thuộc một transaction và commit trước OCPP ACK; lỗi ghi reply rollback cả lô, retry không nhân đôi. Ngưỡng CI vẫn 200 ms cho 20 socket, không bỏ worker hoặc bỏ kiểm tra tính bền vững.

Bổ sung tối ưu S-19: dispatcher dùng data-modifying CTE ghi các lô số đo và durable reply trong cùng một câu SQL. Truy vấn khóa phiên/số đo tái sử dụng hai cấu trúc bind-parameter (có/không transactionId), không cache kết quả hoặc bỏ khóa. Mục tiêu giảm round trip và tạo object khi 20 trụ báo đồng thời; không thay ngưỡng NFR, không ACK sớm và không tắt worker nền. Kiểm thử riêng xác nhận hai MeterValues cùng message id đồng thời tạo một tập số đo/một reply, rồi replay qua session mới.
