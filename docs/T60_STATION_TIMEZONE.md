# S-28 / T-60 — múi giờ trạm

`stations.timezone` đã tồn tại từ migration `7b1d4f2a9c30`, NOT NULL và có server default `Asia/Ho_Chi_Minh`. T-60 giữ nguyên cột và lịch sử migration; không thêm revision hoặc backfill lại dữ liệu hợp lệ.

## Hợp đồng API

- `POST /api/v1/stations`: nhận thêm `timezone`, mặc định `Asia/Ho_Chi_Minh` khi bỏ qua. Vẫn yêu cầu `Idempotency-Key`. Cùng khoá với timezone khác trả `409 idempotency_conflict`. Hash khi dùng timezone mặc định giữ tương thích với các yêu cầu cũ.
- `GET /api/v1/stations`, `GET /api/v1/stations/{id}`, response POST/PATCH: trả thêm `timezone`.
- `PATCH /api/v1/stations/{id}` nhận timezone tuỳ chọn. Trường này không được null; chuỗi rỗng, tên sai hoặc offset như `+07:00` trả 422.
- Quyền và phạm vi sở hữu giữ nguyên. Chủ trạm khác không được thay đổi timezone của trạm; tài xế không có quyền quản lý.

Ví dụ PATCH:

```json
{"timezone": "Asia/Tokyo"}
```

Khi trạm chưa có phiên: 200 và response có timezone mới. Khi đã có bất kỳ phiên nào: 409 với `{"detail":"station_timezone_locked"}`. Phiên đã kết thúc hoặc có xác thực không hợp lệ vẫn làm timezone bất biến. Gửi lại timezone đang lưu được phép; các field như tên/địa chỉ vẫn sửa được. Payload đổi timezone bị từ chối không cập nhật các field khác đi kèm.

## Kiểm tra và giao dịch

Hàm `validate_station_timezone` dùng ZoneInfo; dependency tzdata được khai báo để Windows có dữ liệu múi giờ. Schema, model và repository dùng cùng hàm. API không cần thêm form trong T-60.

Repository khoá dòng Station trước khi kiểm lịch sử qua `charging_sessions → charge_points → stations`. StartTransaction cũng khoá dòng Station trước khi tạo phiên trong cùng giao dịch. Hai thao tác vì thế được tuần tự hoá: nếu phiên tạo trước, thay timezone bị từ chối; nếu timezone đổi trước, phiên được tạo sau khi đổi đã commit. Giữ thứ tự khoá trong OCPP: charger → station → connector/session.

Các đường thay timezone sau này phải dùng `StationRepository.update_station`; các đường tạo phiên mới phải phối hợp với cùng khoá Station. Đây là quy tắc tầng ứng dụng, không phải trigger database cho các lệnh SQL quản trị. Không tạo thêm giao dịch hoặc tự commit trong repository/service.

## Kiểm chứng

`tests/test_station_timezones.py` kiểm tên IANA, default, hash tương thích, HTTP tạo/đọc/đổi, lỗi dữ liệu, trạm có phiên đang mở/đã kết thúc, quyền chủ trạm và hai chiều cạnh tranh với StartTransaction trên hai kết nối thật. Test cạnh tranh xác nhận blocking bằng `pg_blocking_pids`, không chỉ dựa vào thứ tự chạy coroutine.

Test phải dùng PostgreSQL riêng; không chạy suite trên database demo/staging. Không cần đổi Alembic head của T-59.
