# API bổ sung cho giao diện chủ trạm

Ngày triển khai cục bộ: 04/10/2026. Phạm vi được người dùng đồng ý: bổ sung API trước khi xây giao diện chủ trạm theo các mẫu đã chốt. Không ghi đè bản mẫu trong `impeccable`, không sửa frontend trong bước này.

## 1. Ảnh đại diện trạm

| Endpoint | Quyền | Kết quả |
|---|---|---|
| PUT `/api/v1/stations/{id}/photo` | station_owner, theo sở hữu | Tạo/thay ảnh; trả StationResponse có `photo_url` |
| GET `/api/v1/stations/{id}/photo` | station_owner theo sở hữu; operator/admin | Trả ảnh đã chuẩn hóa, hoặc 404 khi chưa có ảnh |
| DELETE `/api/v1/stations/{id}/photo` | station_owner, theo sở hữu | Xóa ảnh, 204; gọi lại vẫn 204 |

PUT dùng **body nhị phân của file**, không phải multipart. Header `Content-Type`: `image/jpeg`, `image/png` hoặc `image/webp`. Ví dụ frontend: `fetch(url, {method: 'PUT', body: file, headers: {'Content-Type': file.type}})` với phiên đăng nhập cùng nguồn. Tạo trạm trước, lấy id rồi tải ảnh tùy chọn; nếu tải ảnh thất bại, bản ghi trạm vẫn tồn tại và người dùng có thể thử lại.

Giới hạn đầu vào 20 MiB, tối đa 16 triệu pixel; không nhận SVG, dữ liệu giả định dạng hoặc ảnh hỏng; ảnh động WebP/PNG được lấy khung hình đầu làm ảnh đại diện tĩnh. Backend kiểm tra ảnh thực, xử lý chiều EXIF, bỏ metadata, mã hóa lại JPEG cho ảnh không trong suốt hoặc PNG cho ảnh trong suốt. Kết quả chuẩn hóa cũng không vượt 20 MiB. 413 khi body quá lớn, 415 với MIME không hỗ trợ, 422 khi ảnh không hợp lệ/không đáp ứng giới hạn sau chuẩn hóa. 401/403 vẫn theo cơ chế xác thực/phân quyền chung.

Ảnh được lưu trong PostgreSQL cùng bản ghi trạm, thay/xóa nguyên tử trong giao dịch. Không tạo đường dẫn filesystem từ tên file của người dùng. Cột dữ liệu ảnh được tải trì hoãn để danh sách trạm không kéo toàn bộ ảnh. `photo_url` có digest phiên bản và là đường dẫn cùng nguồn; chưa có ảnh thì null. GET kiểm tra quyền kể cả khi biết URL, trả `private, no-store` và `nosniff`. URL chưa được mở cho tài xế; thêm vào discovery sẽ thuộc phạm vi giao diện tài xế sau.

## 2. Metadata trụ và đầu nối

POST `/api/v1/stations/{id}/charge-points` vẫn nhận payload cũ `{code, connector_count}`. Bổ sung `name` tùy chọn và `connectors` tùy chọn:

```json
{
  "code": "CP-OWNER-01",
  "name": "Trụ sân trước",
  "connector_count": 2,
  "connectors": [
    {"connector_number": 1, "connector_type": "Type 2", "current_type": "AC", "max_power_kw": "22", "voltage": "400", "amperage": "32"},
    {"connector_number": 2, "connector_type": "CCS2", "current_type": "DC", "max_power_kw": "60"}
  ]
}
```

Nếu gửi cấu hình lúc tạo thì phải có đủ số đầu nối 1..connector_count, không trùng. Số đầu nối vẫn 1–4 theo S-05. Không tạo đầu nối mới khi sửa metadata.

PATCH `/api/v1/charge-points/{id}` nhận một hoặc nhiều trường `code`, `name`, `connectors`. Có thể sửa riêng tên/metadata sau khi mã đã khóa; nếu gửi trường code khi mã khóa vẫn trả 409 theo contract cũ. Các cấu hình gửi trong PATCH chỉ sửa đầu nối đã có. Đầu nối không tồn tại trả 422 và không cập nhật tên hay trường khác trong cùng request. Danh sách cấu hình không trùng số, không null/rỗng. Payload rỗng và code null không hợp lệ. Có thể gửi `name: null` để bỏ tên, hoặc null cho một thông số để bỏ giá trị đã khai; không gửi trường thì giữ nguyên.

Thông số được lưu trên các cột đã tồn tại: `connector_type` (chuỗi tối đa 50, không bắt buộc catalog), `current_type` AC/DC, `max_power_kw` >0 tối đa 8 chữ số/3 số thập phân, `voltage` và `amperage` >0 tối đa 8 chữ số/2 số thập phân. Đây là thông số danh định, không phải số đo và không gửi SetChargingProfile. Chưa áp đặt quan hệ vật lý giữa các trường vì số pha/loại thiết bị/catalog chưa được refine.

Response tạo/sửa/danh sách trả các thông số đầu nối. Response trụ bổ sung vendor/model/firmware_version nhận từ OCPP, chỉ đọc; người dùng không được giả mạo qua payload tạo/sửa. Tiếp tục giữ mã duy nhất không phân biệt hoa/thường, owner scope và trạng thái đầu nối mặc định unknown. Decimal trong JSON trả chuỗi, frontend có thể chuyển số để hiển thị theo đơn vị.

## 3. Triển khai và ranh giới

Dependency mới: Pillow trong pyproject.toml; Docker build cài tự động từ project dependencies. Migration `a4d901ce8207` sau `c60318a4d962` chỉ thêm ba cột ảnh. Chạy `python -m alembic upgrade head` trước khi chạy backend mới. Chưa áp dụng migration vào DB csms đang chạy; chưa rebuild/restart container, chưa commit/push.

Biểu giá/tính tiền (S-28–S-34), hạn mức/phân bổ công suất (S-42–S-45), báo cáo doanh thu (S-52), hoạt động/tạm ngừng (S-66) giữ nguyên phạm vi story sau. Không thêm tiền tạm tính giả vào API phiên hoặc API tài chính. Giao diện chủ trạm có thể bắt đầu nối các chức năng hiện có cộng API bổ sung này.

## 4. Kiểm chứng

Database thử riêng: `csms_owner_api_20261004`. Đã chạy migration từ schema trống tới head mới. Test mới kiểm tra lưu/đọc metadata, không sửa mã đã khóa nhưng cho sửa metadata, cập nhật nguyên tử khi số đầu nối sai, chặn chủ khác, không sửa vendor, validation số âm/0/độ chính xác/loại dòng điện/số đầu nối, vòng đời ảnh, thay/xóa, giới hạn dung lượng, nội dung giả, quyền đọc/sửa, giữ ảnh cũ khi upload lỗi và bỏ EXIF/GPS/giữ chiều ảnh điện thoại.

Kết quả kiểm tra cục bộ: toàn bộ backend **358 tests passed** (26,92 giây), Ruff không có lỗi, Mypy đạt trên 51 file nguồn và `git diff --check` đạt. Có 4 cảnh báo deprecation từ môi trường/thư viện kiểm thử. Lượt kiểm tra hoàn tất dùng thư mục tạm riêng trong `.local/test-tmp` để tránh lỗi thư mục tạm Windows ở các lượt trước. Bằng chứng cục bộ không thay trạng thái Jira, CI hoặc staging.
