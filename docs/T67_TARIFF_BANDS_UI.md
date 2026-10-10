# S-29 / T-67 — Form nhiều khung giờ

## Phạm vi

Mở rộng form T-62 trong chi tiết trạm. Chủ trạm chọn một giá cả ngày hoặc nhiều
khung giờ. Giữ quy tắc ngày hiệu lực theo múi giờ trạm, phí chiếm trụ/ân hạn,
phân quyền hiện có và chặn gửi hai lần. Không triển khai lịch sử biểu giá T-69.

## Hành vi

- Thêm/xoá dòng với giờ bắt đầu, giờ kết thúc HH:MM và đơn giá nguyên không âm.
  Bắt đầu trong 00:00–23:59; cuối ngày cho phép 24:00; hai mốc bằng nhau không hợp lệ.
- Khung vắt đêm được chia để tính độ phủ ngay trên client, nhưng POST gửi khung gốc
  cho API T-66 chuẩn hoá và lưu. Sau lưu đọc lại context từ backend.
- Bản xem trước 24 giờ hiển thị phần đã phủ, khoảng hở, khoảng chồng với chú thích.
  Dòng liên quan có lỗi chữ và viền đỏ ngay khi nhập, trước khi bấm lưu.
- Không lưu khi thiếu khung, giờ/giá sai, chồng hoặc hở. Lỗi 422 theo input_indices
  hoặc loc của API hiển thị ở dòng tương ứng và giữ dữ liệu để sửa.
- Payload multi-band chỉ có bands, không kèm energy_rate_vnd_per_kwh ở cấp ngoài.
  JSON number được tạo từ BigInt để giữ chính xác tiền 64-bit, không qua Number.
- Biểu giá hiện tại/sắp áp dụng hiển thị giờ đã chuẩn hoá: khung 22:00–02:00 trở
  thành 22:00–24:00 và 00:00–02:00 khi đọc lại. Luồng cũ một giá vẫn hoạt động.

## Kiểm tra acceptance

1. Chọn nhiều khung; nhập 22:00–02:00 và 03:00–22:00: cả dòng liên quan báo
   khoảng hở 02:00–03:00, preview có đoạn vàng và nút lưu bị khoá.
2. Đổi khung thứ hai thành 01:00–22:00: báo chồng 01:00–02:00 ở hai dòng.
3. Sửa thành 02:00–22:00, nhập phí/ân hạn hợp lệ và lưu: POST nhận bands gốc;
   context sau lưu hiển thị ba dòng, gồm hai phần của khung vắt đêm.
4. Rời chi tiết rồi mở lại: đọc dữ liệu đã chuẩn hoá từ API, không dựa trên form cũ.
5. Kiểm tra ở 360px: ô giờ hai cột, giá một cột, nút/preview truy cập được bằng cuộn.

Test `TariffBands.test.tsx` bao phủ gap/overlap, empty rows, mốc giờ/BIGINT,
API row errors, double submit và save/reopen. Các test T-62 vẫn giữ nguyên.
Kiểm tra browser trên app thật dùng API fixture: desktop 1440×900 và mobile
360×800, không lỗi JavaScript hoặc tràn ngang; không phải xác nhận staging.
