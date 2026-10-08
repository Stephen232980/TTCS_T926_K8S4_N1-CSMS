# S-29 / T-66 — API biểu giá nhiều khung

Mở rộng `POST /api/v1/owner/stations/{station_id}/tariffs` của T-61.
Giữ nguyên quyền `owner.tariff.manage`, scope `owned`, cookie đăng nhập,
response 201 và quy tắc ngày hiệu lực T-68. Request một khung cũ vẫn dùng
`energy_rate_vnd_per_kwh`/`label` ở cấp biểu giá.

## Request nhiều khung

```json
{
  "effective_from": "2026-10-08",
  "idle_rate_vnd_per_minute": 1000,
  "grace_minutes": 5,
  "bands": [
    {"start_min": 0, "end_min": 360, "energy_rate_vnd_per_kwh": 2000, "label": "Đêm"},
    {"start_min": 360, "end_min": 1320, "energy_rate_vnd_per_kwh": 4000, "label": "Ngày"},
    {"start_min": 1320, "end_min": 1440, "energy_rate_vnd_per_kwh": 2000, "label": "Đêm"}
  ]
}
```

Ngày minh họa phải thay theo ngày địa phương của trạm. Phiên bản đầu hôm nay,
phiên bản sau từ ngày mai. Khi dùng `bands`, không gửi đơn giá/nhãn cấp biểu
giá; các trường đó nằm trong từng khung. Không nhận trường lạ.

`start_min`/`end_min` là phút trong ngày địa phương; 1440 chỉ dùng làm mốc
kết thúc 24:00. Các số là JSON integer, không nhận bool, float hoặc chuỗi số.
Đơn giá không âm trong BIGINT. Nhãn khung tối đa 100 ký tự, mặc định rỗng.
Danh sách 1–1440 khung (mỗi khung hợp lệ có ít nhất một phút).

T-65 kiểm chính xác phủ kín 24 giờ, chồng/hở và mốc bằng nhau. Khung vắt đêm
1320–120 tách thành 0–120 và 1320–1440, giữ giá/nhãn. 1320–0 không sinh
khung rỗng. Response trả các khung đã chuẩn hóa, theo giờ bắt đầu.

## Lỗi và tính nguyên tử

Các lỗi 401/403/404/409 và ngày hiệu lực 422 giữ như T-61.
Lỗi trường từng khung có loc `['body', 'bands', index, field]`.
Lỗi phủ kín trả 422 với detail gồm tất cả khoảng lỗi:

```json
{
  "detail": [{
    "loc": ["body", "bands"],
    "type": "gap",
    "msg": "Khoảng hở 06:00–07:00",
    "input_indices": [],
    "start_min": 360,
    "end_min": 420
  }]
}
```

Khoảng chồng có `type: overlap` và chỉ số dòng đầu vào liên quan (từ 0).
`input_indices` của khoảng hở rỗng vì không có khung phủ khoảng đó.
Khung giờ sai bị từ chối trước khi INSERT. Hàm tạo T-61 giữ khóa trạm, gọi
guard T-68, flush biểu giá và toàn bộ khung trong cùng giao dịch; lỗi ghi
thì rollback toàn bộ. Biểu giá một và nhiều khung dùng chung khóa/giao dịch.
Không thay đổi biểu giá đã lưu, không thêm migration và không bật tính phí.

## Phạm vi và kiểm chứng

T-66 hoàn thành backend nhiều khung; form T-67 và phần S-29 còn lại chưa thuộc PR.
Chạy `pytest tests/test_multi_band_tariff_api.py tests/test_flat_tariff_api.py
tests/test_tariff_bands.py tests/test_endpoint_policy_inventory.py
tests/test_effective_tariffs.py -q` trên PostgreSQL test riêng.
Test bao phủ lưu/tách khung, lỗi và không ghi dữ liệu, vai trò/sở hữu,
ngày địa phương, tương thích T-61 và tranh tạo phiên bản giữa hai dạng request.

Kết quả local 08/10/2026: 114 test đạt (27 test T-66 mới và 87 test liên quan
T-61/T-65/T-68/inventory). PostgreSQL 16 riêng, migration đến head, Ruff
lint/format, mypy và kiểm tra diff đạt. Chưa xác nhận CI PR hoặc staging.
