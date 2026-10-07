# S-28 / T-59 — dữ liệu biểu giá

Migration `f070008a2026` nối sau `e030007a2026`. Module: `src.modules.pricing.models`.

| Bảng / cột | Ý nghĩa |
| --- | --- |
| `tariffs.id`, `station_id` | UUID biểu giá và trạm; FK trạm, không tự xoá dây chuyền |
| `effective_from` | DATE theo múi giờ trạm; không chuyển thành ngày UTC |
| `idle_rate_vnd_per_minute` | BIGINT, đồng/phút, không âm |
| `grace_minutes` | INTEGER, số phút ân hạn, không âm |
| `created_at` | Thời điểm tạo có múi giờ, mặc định giờ database |
| `tariff_bands.id`, `tariff_id` | UUID khung và biểu giá; FK biểu giá |
| `start_min`, `end_min` | INTEGER, khoảng nửa mở [bắt đầu, kết thúc), 0 ≤ bắt đầu < kết thúc ≤ 1440 |
| `energy_rate_vnd_per_kwh` | BIGINT, đồng/kWh, không âm |
| `label` | Nhãn khung, VARCHAR(100), bắt buộc |

Biểu giá phẳng: một khung `start_min=0`, `end_min=1440`. Khung qua nửa đêm phải được tách trước khi lưu (T-65). Database kiểm ranh từng khung; kiểm phủ kín ngày và chồng lấn giữa các khung thuộc T-65/T-66.

Unique `(station_id, effective_from)` đồng thời tạo chỉ mục B-tree phục vụ tra cứu phiên bản theo trạm/ngày. Có chỉ mục `tariff_bands(tariff_id)` để đọc các khung của biểu giá. Đơn giá và phí dùng số nguyên đồng, không dùng float. UUID được model cấp khi chèn qua ORM; bên chèn SQL trực tiếp phải cấp UUID.

T-59 chỉ làm schema/model. API và quyền chủ trạm thuộc T-61/T-66; quy tắc ngày hiệu lực và bất biến thuộc T-68. Chưa thay đổi cách tính phí chiếm trụ của phiên. Các task sau nên dùng đúng tên cột trên, đọc timezone từ trạm và thực hiện thao tác nhiều bảng trong cùng giao dịch.

Kiểm chứng: migration upgrade/downgrade trên database riêng; `alembic check`; `pytest tests/test_tariff_schema.py`. Không chạy test hoặc downgrade trên database demo/staging.
