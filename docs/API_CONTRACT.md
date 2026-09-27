# API contract CSMS

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
| 404 | `resource_not_found` | Tài nguyên không tồn tại trong phạm vi người dùng được phép thấy |
| 409 | `resource_conflict` | Trùng dữ liệu hoặc xung đột trạng thái |
| 422 | `validation_error` | Dữ liệu không đạt validation |
| 423 | `login_temporarily_locked` | Đăng nhập bị khóa tạm |
| 500 | `internal_error` | Lỗi không dự kiến; không trả stack trace cho client |

Login/logout hiện trên `main` vẫn dùng response lỗi mặc định `{"detail": "..."}`. Việc đưa
hai endpoint cũ về error contract chung nên thực hiện trong một task nhỏ riêng để tránh thay
đổi hành vi ngay trong PR T-06 đang chờ review.

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

Endpoint cần bổ sung ngay sau khi T-06 được merge:

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

T-06 hiện cung cấp cơ chế nội bộ `CurrentActor` gồm `user_id` và `roles`. Repository cần lấy
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

### 5.3. Tạo station

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

### 5.4. Cập nhật station

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
- Không tồn tại hoặc nằm ngoài ownership scope trả `404 resource_not_found` để hạn chế lộ dữ liệu.
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

### 6.2. Tạo charge point và connector

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

## 7. CORS và môi trường frontend

- Development ưu tiên Vite proxy `/api` đến `http://localhost:8001` để giữ request cùng origin.
- Nếu frontend gọi backend khác origin, backend phải cấu hình danh sách origin cụ thể và bật
  `allow_credentials`; không dùng origin `*` với cookie.
- Staging/production ưu tiên reverse proxy cùng site và HTTPS.
- `VITE_API_BASE_URL` không chứa secret.

## 8. Trạng thái triển khai

| Contract | Trạng thái ngày 26/09/2026 |
| --- | --- |
| Login/logout | Đã triển khai trên `main`; error shape chưa theo chuẩn chung |
| Session lookup + RBAC | Đã có trong PR T-06, chờ review và merge |
| `GET /auth/me` | Đã chốt contract, chưa triển khai |
| Station list/create/update | Đã chốt baseline, chờ T-07/T-08/T-09 |
| Charge point/code availability | Đã chốt baseline, chờ T-10/T-11 |
| Error contract chung | Đã chốt baseline, chưa triển khai exception handler |

