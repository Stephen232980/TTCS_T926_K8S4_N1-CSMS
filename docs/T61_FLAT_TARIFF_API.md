# S-28 / T-61 — API tạo biểu giá một khung

T-66 mở rộng cùng endpoint để nhận nhiều khung; xem
[contract nhiều khung](T66_MULTI_BAND_TARIFF_API.md). Request một khung dưới
đây vẫn được hỗ trợ. T-66 không đổi quy tắc quyền hoặc ngày hiệu lực.

`POST /api/v1/owner/stations/{station_id}/tariffs`

Chỉ `station_owner`, quyền `owner.tariff.manage`, scope `owned`.
Đăng nhập bằng cookie session. Chủ trạm khác gọi cho trạm có thật nhận 403;
trạm không tồn tại nhận 404. Không có endpoint ghi cho admin/operator.

## Request

```json
{
  "effective_from": "2026-10-08",
  "energy_rate_vnd_per_kwh": 2500,
  "idle_rate_vnd_per_minute": 1000,
  "grace_minutes": 5,
  "label": "Cả ngày"
}
```

Ngày minh họa phải thay theo ngày địa phương thực tế của trạm. Phiên bản đầu
phải bắt đầu hôm nay; phiên bản tiếp theo từ ngày mai trở đi, dùng helper
`kiem_ngay_hieu_luc` của T-68. Không nhận `now`, owner_id hoặc trường lạ.
Giá là JSON integer không âm trong BIGINT; ân hạn là integer không âm trong
INTEGER. Từ chối bool, chuỗi số, số thập phân. `label` mặc định Cả ngày,
1–100 ký tự sau bỏ khoảng trắng đầu/cuối. Ngày chỉ nhận YYYY-MM-DD.

201 trả id biểu giá/trạm, ngày hiệu lực, phí chiếm trụ, ân hạn, created_at
và `bands` gồm đúng một khung start_min=0, end_min=1440, đơn giá/nhãn.
Giá trị 0 hợp lệ. API chỉ lưu cấu hình phí, chưa bật tính phí chiếm trụ.

## Lỗi

- 401: chưa đăng nhập; 403: sai vai trò hoặc sở hữu trạm.
- 404: trạm không tồn tại.
- 422: dữ liệu không hợp lệ, có vị trí trường; ngày sai quy tắc T-68.
- 409: trùng ngày phiên bản tương lai (`tariff_duplicate_date`).

Lặp tạo hôm nay sau khi phiên bản đầu đã được lưu nhận 422 vì ngày không
còn hợp lệ cho phiên bản tiếp theo; không tạo thêm bản ghi. Endpoint này
không cam kết trả lại cùng response khi retry.

## Giao dịch và phần dùng chung

`creation.tao_bieu_gia` khóa trạm với bộ lọc sở hữu T-07, kiểm khung bằng
T-65, gọi guard ngày T-68 và flush biểu giá/các khung trong cùng giao dịch.
Hàm không commit; route commit trước trả 201, dependency rollback khi lỗi.
Khóa trạm được giữ đến commit để hai yêu cầu đầu không tạo hai phiên bản.
T-66 có thể dùng cùng hàm với danh sách khung, sau khi bổ sung request/API.
Không sửa biểu giá cũ và không thêm migration.

## Kiểm chứng

`pytest tests/test_flat_tariff_api.py tests/test_tariff_bands.py
tests/test_endpoint_policy_inventory.py tests/test_effective_tariffs.py -q`

Test API tích hợp tạo database t68_<uuid> riêng qua fixture T-68, migrate
đến head rồi xóa đúng database đó khi xong; cần quyền CREATEDB trên máy
chủ PostgreSQL test. Không trỏ test vào staging hoặc dữ liệu thật.

Các ca bao phủ: 201 và khung 0–1440; 401/403/404; tên trường lỗi 422;
ngày địa phương hai múi giờ; phiên bản đầu/sau; ngày trùng; hai yêu cầu
đồng thời; ngày sai không lưu bản ghi. Inventory và OpenAPI khai rõ policy.
T-62/T-66 và tính phí chiếm trụ chưa thuộc phạm vi T-61.

Kết quả local ngày 08/10/2026: 87 test API T-61, khung giờ T-65,
inventory/phân quyền và helper T-68 đạt trên PostgreSQL 16 riêng.
Bao gồm 6 ca tích hợp trước đó chưa chạy: lưu phiên bản đầu/sau, chủ khác
và trạm không tồn tại, hai múi giờ, tạo đồng thời, rollback khi ghi khung lỗi.
Migration đến head, Ruff lint/format và kiểm tra diff đạt. Đây là bằng chứng
local, chưa xác nhận CI của PR hoặc staging.
