# API contract CSMS

API quản trị tài khoản bổ sung ngày 05/10/2026: xem
[contract, quy tắc và kiểm chứng](ADMIN_ACCOUNT_API_DELIVERY.md).
Nhóm endpoint `/api/v1/admin/accounts` và `/api/v1/admin/roles` chỉ dành cho
admin. Nhóm tiếp theo bổ sung đọc nhật ký tài khoản và sức khỏe hệ thống:
[contract và định nghĩa chỉ số](ADMIN_MONITORING_API_DELIVERY.md).

Trạng thái: baseline cho frontend và backend, chốt ngày 26/09/2026.

Tài liệu này định nghĩa contract HTTP mà frontend có thể dùng để phát triển. OpenAPI của
backend phải phản ánh đúng contract khi endpoint được triển khai. Nếu thay đổi contract,
Pull Request phải nêu rõ ảnh hưởng và thông báo cho frontend.

## 1. Quy ước chung

- Base path: `/api/v1`.
- Request và response dùng `application/json`, trừ response `204 No Content`.
- ID truyền qua JSON là UUID dạng chuỗi.
- Tên field và giá trị enum dùng `snake_case`.
- Thời gian dùng ISO 8601 theo UTC, ví dụ `2026-09-26T08:30:00Z`.
- Tọa độ truyền qua JSON là number; database vẫn dùng kiểu numeric có độ chính xác phù hợp.
- Tiền tệ, nếu được bổ sung sau này, truyền dưới dạng chuỗi thập phân để tránh sai số.
- Frontend phải gửi cookie bằng `credentials: "include"`.
- Không trả SQLAlchemy model trực tiếp; mọi request/response dùng Pydantic schema.
- Field chưa có giá trị nhưng có ý nghĩa trong contract dùng `null`. Không tự ý bỏ field đã
  công bố khỏi response.

## 2. Error contract

Các API mới dùng một cấu trúc lỗi thống nhất:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Dữ liệu không hợp lệ",
    "fields": [
      {
        "field": "latitude",
        "code": "out_of_range",
        "message": "Vĩ độ phải nằm trong khoảng -90 đến 90"
      }
    ],
    "request_id": "req_01J8..."
  }
}
```

`fields` là mảng rỗng với lỗi không gắn vào ô nhập cụ thể. `request_id` có thể là `null`
cho đến khi hệ thống bổ sung correlation ID.

Các mã HTTP chính:

| HTTP | `error.code` | Ý nghĩa |
| --- | --- | --- |
| 400 | `bad_request` | Request sai định dạng hoặc không thể xử lý |
| 401 | `authentication_required` | Chưa đăng nhập, session sai hoặc hết hạn |
| 403 | `permission_denied` | Đã đăng nhập nhưng không đủ quyền |
| 404 | `resource_not_found` | Tài nguyên không tồn tại |
| 409 | `resource_conflict` | Trùng dữ liệu hoặc xung đột trạng thái |
| 422 | `validation_error` | Dữ liệu không đạt validation |
| 423 | `login_temporarily_locked` | Đăng nhập bị khóa tạm |
| 500 | `internal_error` | Lỗi không dự kiến; không trả stack trace cho client |

Login/logout hiện trên `main` vẫn dùng response lỗi mặc định `{"detail": "..."}`. Việc đưa
hai endpoint cũ về error contract chung nên thực hiện trong một task nhỏ riêng để tránh thay
đổi hành vi trong phạm vi T-06 đã được merge.

## 3. Phân trang

Sprint 1 dùng phân trang theo trang vì dễ triển khai và đủ cho màn hình quản trị hiện tại:

```text
GET /api/v1/stations?page=1&page_size=20
```

- `page`: mặc định `1`, nhỏ nhất `1`.
- `page_size`: mặc định `20`, nhỏ nhất `1`, lớn nhất `100`.
- `sort`: field cho phép sắp xếp, mặc định tùy tài nguyên.
- `order`: `asc` hoặc `desc`.

Response:

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0,
  "total_pages": 0
}
```

Chỉ chuyển sang cursor pagination khi dữ liệu hoặc tần suất cập nhật thực tế làm phân trang
theo trang không còn đáp ứng; chưa cần làm trong Sprint 1.

## 4. Authentication

### 4.1. Đăng nhập

```text
POST /api/v1/auth/login
```

Request:

```json
{
  "email": "owner@example.com",
  "password": "mat-khau"
}
```

Thành công `200 OK`:

```json
{
  "status": "authenticated"
}
```

Backend đặt cookie `session` với `HttpOnly`, `SameSite=Lax`, `Path=/`; staging và production
phải bật `Secure`.

Lỗi hiện có: `401`, `422`, `423`.

### 4.2. Đăng xuất

```text
POST /api/v1/auth/logout
```

Thành công: `204 No Content`. Endpoint có tính idempotent: gọi khi không có session vẫn trả
`204` và yêu cầu trình duyệt xóa cookie.

### 4.3. Người dùng hiện tại

Contract đề xuất cho một cải tiến độc lập sau T-06; endpoint chưa được triển khai:

```text
GET /api/v1/auth/me
```

Thành công `200 OK`:

```json
{
  "id": "8cc86d88-43a8-4d14-a32b-b7c49749694f",
  "email": "owner@example.com",
  "roles": ["station_owner"]
}
```

Quy tắc:

- `roles` luôn là mảng, sắp xếp tăng dần để response ổn định.
- Không trả session token, password hash hoặc thông tin khóa đăng nhập.
- Session thiếu, sai hoặc hết hạn trả `401 authentication_required`.
- Endpoint này chỉ yêu cầu đã đăng nhập; không áp một role cụ thể.

T-06 đã cung cấp cơ chế nội bộ `CurrentActor` gồm `user_id` và `roles`. Repository cần lấy
thêm email hoặc endpoint truy vấn user theo `user_id` để tạo response trên.

## 5. Station

### 5.1. Kiểu dữ liệu

```json
{
  "id": "93709a25-81df-4cef-8cdb-57f3b305713b",
  "owner_id": "8cc86d88-43a8-4d14-a32b-b7c49749694f",
  "name": "Trạm Quận 1",
  "address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
  "latitude": 10.7731,
  "longitude": 106.7032,
  "status": "inactive",
  "created_at": "2026-09-26T08:30:00Z",
  "updated_at": "2026-09-26T08:30:00Z"
}
```

`status` Sprint 1 gồm `inactive` và `active`. Khi OCPP được tích hợp có thể mở rộng enum qua
task có migration/contract rõ ràng; frontend phải có fallback hiển thị cho enum chưa biết.

### 5.2. Danh sách station

```text
GET /api/v1/stations?page=1&page_size=20&status=active&search=quan%201
```

Role: `station_owner`, `operator`, `admin`.

- `station_owner` chỉ nhận station thuộc chính mình.
- `operator` và `admin` nhận dữ liệu theo scope được backend quy định.
- `search` tìm theo tên và địa chỉ, tối đa 100 ký tự.
- Response dùng cấu trúc phân trang chung, `items` là mảng station.

### 5.3. Chi tiết station

```text
GET /api/v1/stations/{station_id}
```

Role: `station_owner`, `operator`, `admin`.

- `station_owner` chỉ đọc được station thuộc chính mình.
- `operator` và `admin` đọc theo global scope.
- Station không tồn tại trả `404 resource_not_found`.
- Station tồn tại nhưng nằm ngoài ownership scope trả `403 permission_denied` và ghi
  security log không chứa dữ liệu nhạy cảm.
- Response thành công dùng kiểu dữ liệu station tại mục 5.1.

### 5.4. Tạo station

```text
POST /api/v1/stations
Idempotency-Key: <UUID do frontend tạo cho mỗi lần submit logic>
```

Role: `station_owner`, `operator`, `admin` theo policy được chốt khi triển khai T-09.

Request:

```json
{
  "name": "Trạm Quận 1",
  "address": "123 Nguyễn Huệ, Quận 1, TP.HCM",
  "latitude": 10.7731,
  "longitude": 106.7032
}
```

- Không nhận `owner_id` từ frontend. Backend lấy owner từ actor/scope.
- `name`: sau khi trim dài 1–150 ký tự.
- `address`: sau khi trim dài 1–500 ký tự.
- `latitude`: từ -90 đến 90.
- `longitude`: từ -180 đến 180.
- Station mới có `status = inactive`.
- Thành công: `201 Created`, body là station đầy đủ.
- Gửi lại cùng `Idempotency-Key` và cùng payload trả cùng kết quả; cùng key nhưng payload khác
  trả `409 resource_conflict`.

### 5.5. Cập nhật station

```text
PATCH /api/v1/stations/{station_id}
```

Request có thể chứa một hoặc nhiều field:

```json
{
  "name": "Trạm trung tâm",
  "address": "125 Nguyễn Huệ, Quận 1, TP.HCM",
  "latitude": 10.7732,
  "longitude": 106.7033
}
```

- Không cho cập nhật `id`, `owner_id`, `created_at`, `updated_at` trực tiếp.
- Object rỗng trả `422 validation_error`.
- Thành công: `200 OK`, body là station sau cập nhật.
- Station không tồn tại trả `404 resource_not_found`.
- Station tồn tại nhưng nằm ngoài ownership scope trả `403 permission_denied` và ghi security
  log không chứa dữ liệu nhạy cảm.
- Chuyển trạng thái station nên dùng endpoint/action riêng khi có luật nghiệp vụ, không trộn vào
  PATCH thông tin cơ bản trong Sprint 1.

## 6. Charge point và connector

### 6.1. Kiểm tra code

```text
GET /api/v1/charge-points/code-availability?code=CP-Q1-001
```

Response `200 OK`:

```json
{
  "code": "CP-Q1-001",
  "available": true
}
```

Kết quả này chỉ hỗ trợ UX; backend vẫn phải kiểm tra unique constraint khi tạo.

### 6.2. Danh sách charge point theo station

```text
GET /api/v1/stations/{station_id}/charge-points?page=1&page_size=20
```

Quy tắc:

- `station_owner` chỉ xem được charge point thuộc station do mình sở hữu.
- `operator` và `admin` có phạm vi xem toàn cục.
- `page` bắt đầu từ 1; `page_size` từ 1 đến 100.
- Charge point được sắp theo thời gian tạo mới nhất; connector trong từng charge point
  được sắp theo `connector_number` tăng dần.
- Station không tồn tại trả `404 resource_not_found`.
- Station tồn tại nhưng nằm ngoài ownership scope trả `403 permission_denied` và ghi
  security log.

Response `200 OK`:

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0,
  "total_pages": 0
}
```

Mỗi phần tử trong `items` dùng schema charge point và connector như response tạo mới
bên dưới, bao gồm `code_locked_at`.

### 6.3. Tạo charge point và connector

```text
POST /api/v1/stations/{station_id}/charge-points
Idempotency-Key: <UUID>
```

Request:

```json
{
  "code": "CP-Q1-001",
  "name": "Trụ số 1",
  "connectors": [
    {"connector_number": 1},
    {"connector_number": 2}
  ]
}
```

Quy tắc:

- `code`: trim, 1–64 ký tự, unique toàn hệ thống; backend chuẩn hóa theo quy tắc được chốt
  trong T-10 trước khi kiểm tra unique.
- Có từ 1 đến 4 connector.
- `connector_number` là số nguyên từ 1 đến 4 và không trùng trong cùng charge point.
- Backend kiểm tra station thuộc scope của actor.
- Toàn bộ charge point và connector được tạo trong một transaction.
- Thành công: `201 Created`.
- Code trùng trả `409 resource_conflict`, field `code`.

Response:

```json
{
  "id": "8568da19-4626-48ae-8851-427b381cdaba",
  "station_id": "93709a25-81df-4cef-8cdb-57f3b305713b",
  "code": "CP-Q1-001",
  "name": "Trụ số 1",
  "status": "offline",
  "connectors": [
    {
      "id": "ada2f612-aa2e-45f4-ad18-847c2e44a01e",
      "connector_number": 1,
      "status": "unavailable"
    },
    {
      "id": "b668e08d-d134-410f-937a-87dfc925f37c",
      "connector_number": 2,
      "status": "unavailable"
    }
  ],
  "created_at": "2026-09-26T08:30:00Z",
  "updated_at": "2026-09-26T08:30:00Z"
}
```

### 6.4. Sửa mã charge point

```text
PATCH /api/v1/charge-points/{charge_point_id}
```

Request:

```json
{
  "code": "CP-Q1-002"
}
```

Quy tắc:

- Chỉ `station_owner` sở hữu station chứa charge point được sửa mã.
- Mã được trim và kiểm tra unique toàn hệ thống, không phân biệt hoa thường.
- Trước phiên sạc đầu tiên, sửa thành công trả `200 OK`.
- Khi phiên sạc đầu tiên bắt đầu, backend phải đặt `code_locked_at` trong cùng
  transaction tạo phiên. Từ thời điểm đó mã và chính mốc khóa là bất biến.
- Mã đã được dùng trả `409 charge_point_code_already_exists`.
- Mã đã khóa trả `409 charge_point_code_locked_after_charging`.
- Database trigger vẫn chặn thay đổi mã đã khóa nếu bỏ qua API.

## 7. CORS và môi trường frontend

- Development ưu tiên Vite proxy `/api` đến `http://localhost:8001` để giữ request cùng origin.
- Nếu frontend gọi backend khác origin, backend phải cấu hình danh sách origin cụ thể và bật
  `allow_credentials`; không dùng origin `*` với cookie.
- Staging/production ưu tiên reverse proxy cùng site và HTTPS.
- `VITE_API_BASE_URL` không chứa secret.

## 8. Trạng thái triển khai

| Contract | Trạng thái ngày 27/09/2026 |
| --- | --- |
| Login/logout | Đã triển khai trên `main`; error shape chưa theo chuẩn chung |
| Session lookup + RBAC | Đã triển khai trên `main` qua T-06 |
| `GET /auth/me` | Đã chốt contract đề xuất; chưa triển khai |
| Station list/create/update | Đã chốt baseline, chờ T-07/T-08/T-09 |
| Charge point/code availability | Đã chốt baseline, chờ T-10/T-11 |
| Error contract chung | Đã chốt baseline, chưa triển khai exception handler |


## Kết nối OCPP và màn hình vận hành

WebSocket: /ocpp/{charge_point_code}, subprotocol ocpp1.6.
GET /api/v1/ocpp/connections?page=1&page_size=50 dành cho owner/operator/admin;
owner chỉ thấy trụ thuộc trạm của mình, driver nhận 403. page >= 1, page_size
từ 1 đến 100. Trả items/total/page/total_pages và dữ liệu kết nối/Boot;
xem [hợp đồng chi tiết](OCPP_FOUNDATION_DELIVERY.md).
Các action OCPP ngoài BootNotification hiện trả NotImplemented sau Boot.

Boot replay: nếu phản hồi đã lưu là `Accepted` nhưng trạm hiện đã bị khóa
hoặc lưu trữ, trả `CALLRESULT` với `status=Rejected`, `currentTime` hiện tại
và `interval` cấu hình. Socket không được chấp nhận Boot; không ghi đè cache
cũ. Khi trạm khả dụng trở lại, replay có thể nhận phản hồi cũ. Phản hồi Boot
đã lưu là `Rejected` giữ nguyên; muốn xin chấp nhận lại cần message ID mới.
Xem quy tắc S-08/S-14 trong hợp đồng chi tiết ở trên.


## Bản đồ vị trí trạm — điều chỉnh 02/10/2026

Chủ trạm chọn vị trí trên bản đồ thay cho nhập kinh độ/vĩ độ. POST/PATCH trạm vẫn gửi `latitude`/`longitude` dưới dạng number, giữ nguyên ràng buộc và DB; UI không hiện tọa độ thô.

`GET /api/v1/driver/stations?page=1&page_size=100&search=...` cần phiên đăng nhập có role `driver`. Chỉ trả trạm `active` và `archived_at IS NULL`. Các field item: `id`, `name`, `address`, `latitude`, `longitude`; không trả `owner_id`, dữ liệu quản lý hay tài chính. Response gồm `items`, `page`, `total`, `total_pages`. Page >= 1, page_size 1..100, search tối đa 100 ký tự, tìm tên/địa chỉ không phân biệt hoa thường. 401/403/422 theo hành vi hiện tại. Tài xế vẫn không có quyền gọi API quản lý trạm.

Đây là phần vị trí được làm sớm của S-47, chưa trả giá hoặc số đầu nối rảnh. API đang dùng DB CSMS, không lấy danh sách trạm ngoài hệ thống.

## Nhóm giám sát S-09–S-12

Nhóm 2 bổ sung Heartbeat, trạng thái/lỗi đầu nối, offline theo lần liên lạc cuối
và màn hình SSE tự nối lại. Xem [phạm vi, API và kiểm chứng](OCPP_MONITORING_DELIVERY.md).
Cần nâng migration a721093e4f62 trước khi chạy. Bằng chứng hiện là kiểm thử
cục bộ; trạng thái Jira/CI và nghiệm thu được kiểm tra riêng.

## Nhóm 3: phiên sạc OCPP

S-15, S-17, S-18, S-19, S-20 bổ sung xác thực thẻ, phiên sạc, số đo và kiểm tra dữ liệu; có màn hình quản lý phiên/thẻ/chờ đối chiếu dùng API thật. Nâng migration d830a62f194b trước khi chạy. Xem [Coverage Matrix, API, kiểm chứng và demo thủ công](OCPP_CHARGING_DELIVERY.md). Đối chiếu/xử lý pending, đóng tay và điều khiển từ xa thuộc các nhóm tiếp theo. Bằng chứng local không thay thế Jira/CI.


## Nhóm 4: phục hồi phiên sạc

S-21 và S-25 bổ sung giữ phiên khi nối lại, nhận tin/số đo muộn theo transactionId, đánh dấu bất thường khi offline quá ngưỡng (mặc định 6 giờ), đóng tay có lý do và lịch sử. Giao diện có bộ lọc bất thường, xác nhận đóng tay và quyền đọc cho kế toán. Nâng migration e41b9027c6a8 trước khi chạy. Xem [AC, API, cấu hình và kiểm thử thủ công](OCPP_RECOVERY_DELIVERY.md). Đóng tay hồ sơ không gửi lệnh dừng tới trụ; pending không khớp vẫn không tự gán phiên. Bằng chứng local không thay Jira/CI.

## Nhóm 5: điều khiển từ xa

S-16, S-23, S-27 thêm Reset, dừng phiên từ xa và nhật ký bất biến. Operator/admin gửi lệnh; admin lọc nhật ký. Accepted không tự đóng phiên; chờ StopTransaction thật, sau 2 phút thiếu tin kết thúc thì cần kiểm tra. Nâng migration f52c813d7a09. Xem [AC, API và test thủ công](OCPP_CONTROL_DELIVERY.md). Bằng chứng local không thay Jira/CI.

## Nhóm 6: tài xế theo dõi và bắt đầu sạc

S-22 và S-24 thêm phiên hiện tại theo tài khoản đăng nhập, cập nhật kWh/thời gian và bắt đầu bằng thẻ ảo qua RemoteStartTransaction. Accepted chờ StartTransaction thật; thiếu xác nhận sau 60 giây cho thử lại. Đầu nối bận/Reserved bị chặn; quyền sở hữu đặt chỗ thuộc phần đặt chỗ sau. Nâng migration c60318a4d962. Xem [AC, API và kiểm thử thủ công](DRIVER_CHARGING_DELIVERY.md). Bằng chứng local không thay Jira/CI.


## Bổ sung API phục vụ thiết kế chủ trạm

Ảnh đại diện trạm, tên trụ và cấu hình danh định đầu nối được mô tả trong [OWNER_UI_API_DELIVERY.md](OWNER_UI_API_DELIVERY.md). Migration `a4d901ce8207` bổ sung ảnh trạm. Đây là mở rộng API cho thiết kế đã chốt, chưa triển khai giao diện và không thay các story biểu giá/phân bổ công suất/doanh thu/đổi trạng thái trạm.
