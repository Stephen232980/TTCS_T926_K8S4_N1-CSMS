# Hướng dẫn thực hiện từng task backend CSMS

Tài liệu này dành cho backend developer mới bắt đầu. Nội dung được diễn giải từ `Tasks.xlsx`, `Backlog CSMS.xlsx` và kiến trúc đã chốt. Khi nội dung trong tài liệu này khác acceptance criteria trong backlog, acceptance criteria là nguồn để kiểm tra kết quả cuối cùng.

## 1. Những từ cần biết

| Từ | Ý nghĩa đơn giản |
| --- | --- |
| Task | Một đầu việc có mã như T-01 hoặc T-05 |
| Dependency | Task phải hoàn thành trước |
| Branch | Nhánh riêng để làm một task |
| Commit | Một lần lưu code kèm lời mô tả |
| Pull Request (PR) | Đề nghị đưa code từ branch vào `main` |
| Review | Người còn lại đọc và kiểm tra code |
| CI | GitHub tự chạy lint, kiểm tra kiểu, test và build |
| Migration | File tạo hoặc thay đổi cấu trúc database |
| Seed | Dữ liệu mẫu được tạo tự động |
| API contract | Quy định API nhận gì, trả gì và có thể báo lỗi gì |
| Handler | Hàm xử lý một API hoặc một OCPP message |
| Job | Công việc chạy nền theo lịch |

## 2. Quy trình chung cho mọi task

### Bước 1: Đọc task

Ghi ra bốn điều trước khi code:

```text
Task cần tạo ra kết quả gì?
Task phụ thuộc task nào?
Acceptance criteria kiểm tra điều gì?
Task sẽ sửa module, API và bảng nào?
```

Không bắt đầu nếu dependency chưa được merge vào `main`.

### Bước 2: Báo cho người còn lại

Ví dụ:

```text
Mình bắt đầu T-05.
Mình sẽ sửa module identity và thêm bảng sessions.
Mình sẽ tạo POST /api/v1/auth/login.
Mình dự kiến mở PR trong hôm nay.
```

### Bước 3: Lấy code mới nhất và tạo branch

```bash
git switch main
git pull --ff-only
git switch -c feature/T-05-login
```

Tên branch đề xuất:

```text
feature/T-<mã>-<tên-ngắn>
fix/T-<mã>-<tên-lỗi>
```

### Bước 4: Chốt API và database

Nếu task có API, ghi trước:

```text
Method + đường dẫn
Ai được gọi
Dữ liệu gửi lên
Dữ liệu trả về
Các mã lỗi
```

Nếu task có database, ghi trước:

```text
Bảng/cột mới
Kiểu dữ liệu
Khoá ngoại
Unique/index
Cách downgrade migration
```

Gửi nội dung này cho người còn lại xem nhanh trước khi viết nhiều code.

### Bước 5: Viết code theo lớp

Thứ tự thông thường:

```text
models.py      cấu trúc database
schemas.py     dữ liệu nhận/trả
repository.py  câu truy vấn database
service.py     quy tắc nghiệp vụ
router.py      endpoint HTTP
tests/         kiểm tra tự động
```

Router không chứa câu SQL. Repository không tự quyết định quyền. Service điều phối nghiệp vụ và transaction.

### Bước 6: Tự kiểm tra

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

Nếu có migration:

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Luôn thử migration trên database trống trước khi mở PR.

### Bước 7: Commit

```bash
git add <các-file-liên-quan>
git commit -m "feat(T-05): add login and temporary lock"
```

Một commit chỉ nên chứa một thay đổi dễ hiểu. Không đưa secret, `.env`, mật khẩu hoặc file tạm vào commit.

### Bước 8: Đồng bộ và push

```bash
git fetch origin
git rebase origin/main
pytest
git push -u origin feature/T-05-login
```

### Bước 9: Tạo Pull Request

PR phải ghi:

```text
Task nào?
Đã thay đổi gì?
Cách chạy thử?
Migration nào được thêm?
API nào được thêm hoặc thay đổi?
Acceptance criteria nào đã kiểm tra?
```

### Bước 10: Review và merge

Người còn lại kiểm tra code, migration, Swagger và test. Chỉ merge khi CI xanh và mọi nhận xét đã được xử lý.

## 3. Quy tắc khi hai người cùng làm

- Mỗi task có một người làm chính và người còn lại review.
- Không cùng sửa một migration.
- Migration đã merge không được sửa; cần thay đổi thì tạo migration mới.
- Báo trước khi sửa file dùng chung như `config.py`, database session hoặc middleware auth.
- Pull Request nên hoàn thành trong một ngày hoặc chia nhỏ task.
- Luôn cập nhật `main` trước khi tạo migration mới.
- Route hoặc OCPP handler mới phải khai quyền; thiếu quyền thì bị từ chối mặc định.

## 4. Sprint 1 — Nền tảng, tài khoản và trạm

### T-01 — Dựng khung dự án và kết nối database

Phụ thuộc: không có.

Các bước:

1. Tạo `pyproject.toml` với Python 3.12+, FastAPI, Uvicorn, SQLAlchemy, Psycopg, Alembic và Pydantic.
2. Tạo cấu trúc `src/entrypoints`, `src/modules`, `src/platform` và `tests`.
3. Tạo FastAPI app và hai endpoint `/health/live`, `/health/ready`.
4. Tạo cấu hình đọc `DATABASE_URL` từ biến môi trường.
5. Tạo async engine và một `AsyncSession` cho mỗi request.
6. Khởi tạo Alembic và migration mẫu.
7. Tạo `Dockerfile`, `docker-compose.yml` gồm `app` và `db`.
8. Viết `.env.example`, không commit `.env` thật.
9. Viết test health và kiểm tra migration tiến/lùi.

Hoàn thành khi: Compose chạy được app và PostgreSQL; `/health/ready` báo sẵn sàng; migration tiến/lùi sạch.

Ghi chú: không in `DATABASE_URL` ra log. Đây là task nên hai backend cùng review kỹ vì mọi task sau dựa vào nó.

### T-02 — CI chạy lint, typecheck và test

Phụ thuộc: T-01.

Các bước:

1. Thêm Ruff, mypy và Pytest vào dependency phát triển.
2. Cấu hình các lệnh giống hệt lệnh chạy trên máy cá nhân.
3. Tạo GitHub Actions chạy khi push và mở PR.
4. Khởi động PostgreSQL service trong CI.
5. Chạy migration trước test tích hợp.
6. Cố ý tạo lỗi lint để xác nhận CI đỏ, sau đó sửa và xác nhận CI xanh.

Hoàn thành khi: lint, typecheck, test và build chạy dưới 5 phút; bước lỗi chặn merge.

Ghi chú: không dùng secret production trong CI; tạo thông tin database riêng cho test.

### T-03 — Triển khai staging bằng Docker

Phụ thuộc: T-02; cần máy chủ staging và GitHub secrets.

Các bước:

1. Build image theo commit SHA.
2. Đẩy image vào container registry.
3. Trên staging, khởi động container candidate bên cạnh bản đang chạy.
4. Chạy migration theo quy trình đã chốt.
5. Gọi `/health/ready` của candidate.
6. Chỉ chuyển traffic khi health check thành công.
7. Nếu thất bại, dừng candidate và giữ container cũ.
8. Ghi hướng dẫn rollback và thử rollback ít nhất một lần.

Hoàn thành khi: merge vào `main` tự triển khai trong 10 phút; triển khai lỗi không làm mất phiên bản cũ.

Ghi chú: chưa thể hoàn tất khi chưa có repository từ xa, registry, domain và máy chủ staging.

### T-04 — Bảng users, roles và seed năm vai trò

Phụ thuộc: T-01.

Các bước:

1. Thiết kế `users`, `roles`, `user_roles` và `sessions` nếu T-05 dùng ngay.
2. Đặt `users.email` lowercase và unique.
3. Dùng cột đủ dài cho Argon2id password hash.
4. Thêm `failed_login_count`, `locked_until`, `created_at`, `updated_at`.
5. Tạo khoá ngoại và index cần thiết.
6. Viết migration up/down.
7. Seed đúng năm role: driver, station_owner, operator, accountant, admin.
8. Viết test unique email và số lượng role.

Hoàn thành khi: migration tiến/lùi được; email trùng bị từ chối; seed có đúng năm role.

Ghi chú: không seed mật khẩu dạng rõ. Tên role là mã dùng trong code nên không đổi tuỳ ý.

### T-05 — Đăng nhập, session và khoá tạm

Phụ thuộc: T-04.

Các bước:

1. Chốt contract `POST /api/v1/auth/login` và `POST /api/v1/auth/logout`.
2. Hash mật khẩu bằng Argon2id.
3. Với email không tồn tại, vẫn thực hiện kiểm tra hash giả để giảm lộ thông tin qua thời gian phản hồi.
4. Nếu sai, tăng bộ đếm theo tài khoản và IP trong database.
5. Sau 5 lần sai liên tiếp, lần tiếp theo bị khoá 15 phút.
6. Nếu đúng, đặt lại bộ đếm và tạo session token ngẫu nhiên.
7. Chỉ lưu hash của session token trong database.
8. Gửi token qua cookie `HttpOnly`, `SameSite=Lax`; bật `Secure` ở staging/production.
9. Viết test đúng, sai, khoá, hết khoá, restart ứng dụng và session hết hạn.

Hoàn thành khi: đúng thì đăng nhập được; sai nhiều lần bị khoá bền qua restart; lỗi không tiết lộ email tồn tại.

Ghi chú: không log password hoặc session token. Đếm theo IP cần bảng/bản ghi riêng, không chỉ có cột trên user.

### T-06 — Middleware kiểm vai trò, mặc định từ chối

Phụ thuộc: T-05.

Các bước:

1. Viết dependency đọc cookie, tìm session và current user.
2. Tạo kiểu `CurrentActor` gồm user id và roles.
3. Tạo khai báo ngắn cho danh sách role được phép ở mỗi route.
4. Nếu route bảo vệ không có policy, trả 403 kể cả admin.
5. Phân biệt 401 chưa đăng nhập và 403 đã đăng nhập nhưng thiếu quyền.
6. Viết route test chưa khai policy và các test theo bảng role.

Hoàn thành khi: route thiếu policy trả 403; chỉ role đã khai mới đi qua.

Ghi chú: không rải `if role == ...` trong từng handler.

### T-07 — Lọc dữ liệu theo chủ sở hữu

Phụ thuộc: T-06.

Các bước:

1. Định nghĩa `ActorScope` cho admin, operator và station owner.
2. Viết repository station luôn nhận scope.
3. Với station owner, thêm điều kiện `owner_id = current_user.id` ngay trong query.
4. Với thao tác theo id, không trả dữ liệu của owner khác.
5. Ghi security log khi có truy cập chéo.
6. Viết test hai chủ trạm A và B; A gọi station của B phải nhận 403.
7. Thêm ví dụ curl vào tài liệu demo.

Hoàn thành khi: không có dữ liệu của owner khác lọt ra; test 403 và security log đều đạt.

Ghi chú: không lấy toàn bộ dữ liệu rồi lọc ở Python hoặc frontend.

### T-08 — Bảng stations

Phụ thuộc: T-04.

Các bước:

1. Chốt các cột: owner, name, address, latitude, longitude, status và timestamps.
2. Dùng numeric đủ chính xác cho toạ độ.
3. Thêm check latitude từ -90 đến 90, longitude từ -180 đến 180.
4. Thêm index `owner_id`.
5. Khoá ngoại phải chặn xoá owner khi còn station.
6. Tạo migration và test up/down, constraint và index.

Hoàn thành khi: schema đúng; xoá owner còn station bị chặn.

Ghi chú: station mới mặc định `inactive`.

### T-09 — API tạo, sửa và danh sách station

Phụ thuộc: T-08 và nên dùng T-07.

Các bước:

1. Chốt `GET /stations`, `POST /stations`, `PATCH /stations/{id}`.
2. Chỉ `station_owner` hoặc role được xác định mới gọi được.
3. Gắn `owner_id` từ current user, không nhận owner id từ client.
4. Kiểm tra tên, địa chỉ và toạ độ bằng Pydantic.
5. Danh sách và cập nhật dùng repository đã lọc ownership.
6. Chống tạo trùng do nhấn nút hai lần bằng idempotency key hoặc cơ chế đã chốt.
7. Viết test tạo, sửa, validation, truy cập chéo và gửi hai lần.

Hoàn thành khi: các API phục vụ màn hình T-09 chạy đúng và Swagger mô tả đủ.

Ghi chú: lỗi từng trường nên dùng cấu trúc mà frontend có thể ánh xạ về đúng ô nhập.

### T-10 — Bảng charge_points và connectors

Phụ thuộc: T-08.

Các bước:

1. Tạo `charge_points` có khoá ngoại tới station và `code` unique toàn hệ thống.
2. Tạo index theo `code` vì OCPP sẽ tra bằng mã này.
3. Tạo `connectors` có `charge_point_id`, `connector_number`, status và timestamps.
4. Unique cặp `(charge_point_id, connector_number)`.
5. Check connector number bắt đầu từ 1.
6. Viết migration up/down.
7. Test hai charge point cùng code và connector trùng số.

Hoàn thành khi: database tự chặn code trùng và connector trùng số.

Ghi chú: unique phải nằm ở database, không chỉ kiểm bằng Python.

### T-11 — API thêm trụ và đầu nối

Phụ thuộc: T-10 và T-07.

Các bước:

1. Chốt API kiểm tra code và API tạo charge point.
2. Kiểm tra station thuộc current owner.
3. Kiểm tra `connector_count` từ 1 đến 4.
4. Trong một transaction, tạo charge point và đúng số connector.
5. Bắt lỗi unique và trả 409 với lỗi gắn vào trường `code`.
6. Có thể cung cấp endpoint kiểm tra code sớm cho frontend nhưng vẫn phải kiểm lại khi lưu.
7. Viết test thành công, code trùng, số connector sai và owner khác.

Hoàn thành khi: tạo một trụ sinh đúng số connector; lách frontend vẫn không tạo được code trùng.

Ghi chú: không commit từng connector riêng lẻ; lỗi giữa chừng phải rollback toàn bộ.

## 5. Sprint 2 — OCPP và theo dõi trạng thái

### T-12 — WebSocket endpoint cho trụ đã đăng ký

Phụ thuộc: T-10.

1. Tạo `/ocpp/{charge_point_code}` và yêu cầu subprotocol `ocpp1.6`.
2. Lấy code từ path, tra `charge_points`, rồi mới accept.
3. Tách lifecycle kết nối khỏi nghiệp vụ handler.
4. Test trụ hợp lệ giữ kết nối và nhiều kết nối đồng thời.

Xong khi: trụ hợp lệ giữ kết nối ít nhất 10 phút và staging chịu ít nhất 50 kết nối.

Ghi chú: mỗi connection/task có database session riêng.

### T-13 — Từ chối trụ lạ

Phụ thuộc: T-12.

1. Đóng handshake/kết nối của code không tồn tại.
2. Ghi code lạ, IP, thời gian và correlation id.
3. Không ghi secret hoặc toàn bộ dữ liệu không cần thiết.
4. Test code lạ và sai subprotocol.

Xong khi: trụ lạ bị đóng ngay và có log tra cứu được.

### T-14 — Đọc và ghi ba loại OCPP frame

Phụ thuộc: T-13.

1. Định nghĩa model `CALL`, `CALLRESULT`, `CALLERROR`.
2. Kiểm tra độ dài mảng, kiểu message id, action và payload.
3. Tạo registry action → handler.
4. Tạo pending-call map cho message gửi xuống trụ.
5. Test serialize/parse hai chiều.

Xong khi: frame hợp lệ được định tuyến; action lạ trả `NotImplemented`.

### T-15 — Test frame sai định dạng

Phụ thuộc: T-14.

1. Lập bảng ca: JSON lỗi, sai loại frame, thiếu id/action/payload, action lạ.
2. Gửi từng frame qua WebSocket thật.
3. Kiểm tra `CALLERROR` và connection vẫn hoạt động khi phù hợp.

Xong khi: mọi ca trả đúng mã lỗi và không làm process crash.

### T-16 — Handler BootNotification

Phụ thuộc: T-15.

1. Tạo handler qua registry T-14.
2. Lưu vendor, model và firmware vào charge point hiện có.
3. Cập nhật bản ghi thay vì tạo charge point mới.
4. Test boot lần đầu và boot lại.

Xong khi: thông tin thiết bị được lưu đúng một charge point.

### T-17 — Phản hồi BootNotification

Phụ thuộc: T-16.

1. Đọc heartbeat interval từ config.
2. Trả `Accepted` hoặc `Rejected` theo trạng thái station.
3. Trả giờ UTC của server.
4. Chặn message nghiệp vụ trước khi boot được accepted.

Xong khi: response đúng OCPP và không hard-code interval.

### T-18 — Handler Heartbeat

Phụ thuộc: T-17.

1. Cập nhật trực tiếp `last_seen_at` bằng một câu SQL.
2. Dùng giờ database/server, không dùng giờ của trụ.
3. Trả current time UTC.
4. Dùng chung cập nhật last seen cho mọi message hợp lệ.

Xong khi: chỉ cột cần thiết được cập nhật và response đúng giờ server.

### T-19 — Test heartbeat với đồng hồ trụ sai

Phụ thuộc: T-18.

1. Cấu hình simulator lệch giờ.
2. Gửi heartbeat và message khác.
3. Kiểm tra `last_seen_at` vẫn theo server.

Xong khi: test tự động chứng minh giờ trụ không ảnh hưởng.

### T-20 — Ánh xạ trạng thái connector

Phụ thuộc: T-19.

1. Định nghĩa enum trạng thái nội bộ.
2. Lập bảng ánh xạ từ trạng thái OCPP.
3. Xử lý `connectorId=0` như trạng thái charge point.
4. Update connector bằng câu SQL ngắn.
5. Test từng trạng thái.

Xong khi: connector và charge point cập nhật đúng nghĩa OCPP.

### T-21 — Lưu lỗi connector

Phụ thuộc: T-20.

1. Tạo `connector_errors` với connector, error code, vendor code và thời gian.
2. Lưu lỗi khi StatusNotification báo lỗi.
3. Giữ lịch sử thay vì ghi đè bản ghi cũ.
4. Test migration và handler.

Xong khi: lỗi có thể tra theo connector và thời gian.

### T-22 — Bỏ qua connector chưa khai báo

Phụ thuộc: T-21.

1. Tra connector theo charge point và number.
2. Nếu không có, ghi warning và trả response phù hợp.
3. Không tự tạo connector.
4. Test database không phát sinh dòng mới.

Xong khi: message lạ không thay đổi cấu hình hệ thống.

### T-23 — Truy vấn cây station–charge point–connector

Phụ thuộc: T-22 và T-07.

1. Viết một truy vấn có ownership scope.
2. Trả cấu trúc ba tầng mà không query trong vòng lặp.
3. Seed 50 charge point và 200 connector để đo.
4. Test operator thấy toàn mạng, owner chỉ thấy của mình.

Xong khi: đúng quyền và dưới 200 ms với dữ liệu yêu cầu.

### T-24 — API hỗ trợ màn hình theo dõi

Phụ thuộc: T-23.

1. Chốt response trạng thái gồm nhãn, thời điểm last seen và connector errors cần thiết.
2. Tạo endpoint snapshot cho màn hình.
3. Không để frontend tự suy luận offline từ dữ liệu thiếu.
4. Test 20 charge point và role owner/operator.

Xong khi: frontend có thể vẽ toàn màn hình từ một response.

### T-25 — Kênh SSE cập nhật trạng thái

Phụ thuộc: T-24.

1. Phát event nội bộ sau khi transaction trạng thái commit.
2. Tạo SSE endpoint có xác thực và ownership filter.
3. Mỗi event có id và loại sự kiện.
4. Khi reconnect, client tải snapshot T-23 lại.
5. Test không rò event giữa hai owner.

Xong khi: trạng thái tới trình duyệt trong một giây và tự khôi phục sau restart.

### T-26 — Job đánh dấu offline

Phụ thuộc: T-25.

1. Job chạy mỗi phút và dùng giờ PostgreSQL.
2. Tìm charge point quá hai heartbeat interval.
3. Đánh dấu offline và connector unknown trong transaction.
4. Viết job idempotent và dùng lock để tránh chạy trùng.

Xong khi: chạy job hai lần không gây thay đổi thừa.

### T-27 — Test offline rồi online lại

Phụ thuộc: T-26.

1. Dùng heartbeat interval 5 giây trong test.
2. Bật simulator, chờ online, dừng, chờ offline rồi bật lại.
3. Kiểm tra connector chỉ có trạng thái thật sau StatusNotification.

Xong khi: kịch bản xanh ba lần liên tiếp.

### T-28 — Registry kết nối đang mở

Phụ thuộc: T-13.

1. Tạo map code → connection có lock bảo vệ.
2. Connection mới cùng code đóng connection cũ rồi thay thế.
3. Gỡ map chỉ khi chính connection hiện tại đóng.
4. Lệnh server xuống trụ phải tra qua registry.

Xong khi: mỗi code chỉ có một connection sống.

### T-29 — Test hai kết nối cùng code

Phụ thuộc: T-28.

1. Mở hai simulator cùng code theo thứ tự.
2. Kiểm tra connection đầu nhận close frame chuẩn.
3. Kiểm tra connection thứ hai vẫn xử lý message.

Xong khi: test độc lập thứ tự và chạy xanh trong CI.

### T-30 — Lưu OCPP message để chống trùng

Phụ thuộc: T-17.

1. Tạo `ocpp_messages` unique theo charge point + message id.
2. Lưu action, request fingerprint, response và thời gian.
3. Tra trước khi gọi handler.
4. Handler và bản ghi response nằm trong cùng transaction.
5. Message lặp trả response cũ.

Xong khi: gửi năm lần chỉ xử lý nghiệp vụ một lần.

### T-31 — Dọn message cũ và test gửi lại

Phụ thuộc: T-30.

1. Đọc số ngày giữ từ config.
2. Job xoá theo batch các dòng quá hạn.
3. Test gửi lại năm lần và restart giữa hai lần.
4. Test job không xoá dữ liệu còn hạn.

Xong khi: dữ liệu quá 7 ngày được dọn và idempotency vẫn qua restart.

### T-32 — Bảng id_tags

Phụ thuộc: T-04.

1. Tạo id tag unique, user driver, status và expiry.
2. Thêm index theo tag code.
3. Seed mỗi driver test một tag.
4. Không ghi nguyên tag vào log.

Xong khi: migration up/down và unique constraint hoạt động.

### T-33 — Handler Authorize

Phụ thuộc: T-32.

1. Viết hàm kiểm tag dùng lại được.
2. Xét tag tồn tại, blocked, expired và station active.
3. Trả đúng `Accepted`, `Blocked`, `Expired`, `Invalid`.
4. Log chỉ bốn ký tự cuối.

Xong khi: năm ca trong story đều qua simulator/test.

### T-34 — Gửi CALL xuống trụ

Phụ thuộc: T-28.

1. Sinh message id duy nhất.
2. Tạo future theo message id trước khi gửi.
3. Gửi qua connection từ registry.
4. Ghép CALLRESULT/CALLERROR vào đúng future.
5. Timeout theo config và luôn dọn future.

Xong khi: Reset nhận đúng response; timeout đúng thời gian; message khác vẫn được xử lý.

### T-35 — API Reset charge point

Phụ thuộc: T-34.

1. Tạo endpoint chỉ operator/admin được gọi.
2. Kiểm tra online trước khi gửi.
3. Gửi Soft/Hard Reset qua T-34.
4. Phân biệt offline, rejected và timeout.
5. Ghi log thao tác tạm thời.

Xong khi: simulator reset được và lỗi hiển thị rõ cho frontend.

## 6. Sprint 3 — Phiên sạc và điều khiển

### T-36 — Bảng charging_sessions

Phụ thuộc: T-32.

1. Tạo transaction id, connector, tag, driver, meter start/end, thời gian, status và stop reason.
2. Dùng Wh dạng số nguyên.
3. Tạo partial unique index: một connector chỉ có một phiên mở.
4. Tạo enum trạng thái rõ ràng và migration up/down.

Xong khi: database tự chặn hai phiên mở trên cùng connector.

### T-37 — Handler StartTransaction

Phụ thuộc: T-36.

1. Dùng lại kiểm tag của T-33.
2. Kiểm tra connector và phiên đang mở.
3. Tạo session trong một transaction.
4. Trả transaction id do database/hệ thống cấp.
5. Test tất cả acceptance criteria.

Xong khi: simulator bắt đầu phiên tạo đúng một dòng với meter start.

### T-38 — Handler StopTransaction

Phụ thuộc: T-37.

1. Tìm phiên theo transaction id.
2. Cập nhật meter end, thời gian, reason và status.
3. Nếu transaction lạ, lưu `orphan_messages`.
4. Nếu phiên đã đóng, không thay đổi lần nữa.

Xong khi: phiên đóng đúng; message lạ có thể tra cứu.

### T-39 — Tính kWh

Phụ thuộc: T-38.

1. Viết hàm thuần nhận meter start/end Wh.
2. Trả chênh lệch quy đổi kWh mà chưa làm tròn tiền.
3. Meter lùi trả `None`/kết quả không hợp lệ, không trả số âm.
4. Test phiên thường, meter lùi và bằng nhau.

Xong khi: ba ca khớp kết quả tính tay.

### T-40 — Bảng meter_values

Phụ thuộc: T-36.

1. Tạo session, timestamp, measurand, value và unit.
2. Index ghép session + timestamp.
3. Giữ nguyên đơn vị gốc từ OCPP.
4. Kiểm tra query số đo mới nhất dùng index.

Xong khi: migration up/down và query plan đúng index.

### T-41 — Handler MeterValues

Phụ thuộc: T-40.

1. Parse hai tầng `meterValue[].sampledValue[]`.
2. Chỉ giữ ba measurand được yêu cầu.
3. Chuẩn hoá giá trị khi đọc nhưng giữ unit gốc.
4. Insert hàng loạt.
5. Message cho connector rảnh đưa vào orphan messages.

Xong khi: simulator gửi mỗi 10 giây tạo dữ liệu đúng nhịp.

### T-42 — Chặn meter value cũ/trùng

Phụ thuộc: T-41.

1. Đọc số đo mới nhất bằng index.
2. Viết hàm thuần áp quy tắc mới, cũ và trùng.
3. Đọc và ghi trong cùng transaction.
4. Test đồng thời để tránh hai message cùng lọt.

Xong khi: ba quy tắc có unit test và response dưới 200 ms.

### T-43 — Test meter value lùi/trùng

Phụ thuộc: T-42.

1. Gửi mốc mới → cũ → trùng qua WebSocket.
2. Kiểm tra chỉ dữ liệu mới được lưu.
3. Kiểm tra log: một warning cho mốc lùi, không warning cho trùng.

Xong khi: test tích hợp chạy trong CI.

### T-44 — Khôi phục phiên khi trụ nối lại

Phụ thuộc: T-42.

1. Khi reconnect, đọc phiên mở theo connector.
2. Charging thì giữ phiên; Available thì đánh dấu cần xem xét.
3. Không tạo phiên mới chỉ vì reconnect.
4. Test ngắt giữa phiên rồi nối lại.

Xong khi: transaction id và phiên cũ được giữ nguyên.

### T-45 — StopTransaction tới muộn

Phụ thuộc: T-44.

1. Cho phép stop của phiên mở sau khi charge point reconnect.
2. Lưu transactionData dồn qua cùng logic meter value.
3. Dùng timestamp trong message làm thời điểm kết thúc.
4. Giữ idempotency nếu message gửi lại.

Xong khi: phiên đóng đúng và kWh khớp simulator.

### T-46 — Kịch bản 20 trụ ngắt–nối

Phụ thuộc: T-45.

1. Viết script nhận số trụ và số lần ngắt.
2. Mỗi trụ chạy một phiên và ngắt ngẫu nhiên.
3. Cuối cùng so transaction id, meter và kWh.
4. In bảng mong đợi/thực tế và exit code khác 0 khi sai.

Xong khi: 20/20 phiên đúng trong ba lần chạy staging.

### T-47 — API phiên hiện tại của tài xế

Phụ thuộc: T-42.

1. Lấy driver từ current user, không nhận driver id từ client.
2. Join id tag, session và meter mới nhất trong một truy vấn.
3. Không có phiên trả 204.
4. Phiên của người khác trả 403.

Xong khi: chỉ trả đúng phiên của tài xế đang đăng nhập.

### T-48 — Realtime cho phiên tài xế

Phụ thuộc: T-47 và kênh T-25.

1. Phát event khi meter value mới commit.
2. Lọc event theo driver/session.
3. Cung cấp snapshot để phục hồi sau reconnect.
4. Test cập nhật dưới 2 giây.

Xong khi: frontend không phải tải lại trang và không nhận dữ liệu người khác.

### T-49 — RemoteStopTransaction

Phụ thuộc: T-38 và T-34.

1. Kiểm tra role, session đang mở và charge point online.
2. Gửi command qua T-34.
3. `Accepted` chỉ nghĩa là trụ nhận lệnh; không tự đóng session.
4. Đặt deadline chờ StopTransaction thật.
5. Ghi audit log qua interface dự kiến của T-57.

Xong khi: session chỉ đóng bằng StopTransaction thật và kWh đúng.

### T-50 — API hỗ trợ nút dừng phiên

Phụ thuộc: T-49.

1. Trả trạng thái chờ và deadline rõ ràng.
2. Phân biệt rejected, offline và timeout.
3. Chỉ operator/admin thấy và gọi được.
4. Phát event khi session đổi trạng thái.

Xong khi: frontend có đủ dữ liệu cho ba thông báo lỗi khác nhau.

### T-51 — RemoteStartTransaction

Phụ thuộc: T-37 và T-34.

1. Kiểm connector available và station active trong transaction.
2. Lấy id tag ảo của tài xế từ backend.
3. Tạo pending-start có hạn 60 giây.
4. Gửi command; connector bận trả 409 trước khi gửi.
5. Chống gửi hai yêu cầu đồng thời.

Xong khi: simulator bắt đầu được; connector bận không nhận command.

### T-52 — API trạng thái bắt đầu sạc

Phụ thuộc: T-51 và T-48.

1. Cho frontend hỏi/nhận trạng thái pending-start.
2. Phân biệt rejected, busy và timeout.
3. Thành công trả session để chuyển màn hình.
4. Idempotency cho nút bấm hai lần.

Xong khi: bốn ca của story có kết quả rõ ràng.

### T-53 — Job phát hiện phiên bất thường

Phụ thuộc: T-46.

1. Tìm phiên đang chạy có charge point offline quá ngưỡng.
2. Tìm phiên chờ remote stop quá 2 phút.
3. Chỉ đánh dấu abnormal/review, không tự đóng.
4. Job idempotent và dùng database time.

Xong khi: phiên test xuất hiện trong danh sách bất thường đúng thời hạn.

### T-54 — API phiên bất thường và đóng tay

Phụ thuộc: T-53.

1. Danh sách có phân trang và dữ liệu trụ, thời gian, meter cuối.
2. Chỉ operator/accountant truy cập.
3. API đóng tay bắt buộc có lý do.
4. Ghi audit log và giữ lịch sử trạng thái.

Xong khi: thiếu lý do bị từ chối; đóng hợp lệ truy vết được.

### T-55 — Simulator trong Docker Compose

Phụ thuộc: T-46.

1. Chọn/pin đúng phiên bản simulator từ K-01.
2. Nhận số trụ và URL server từ biến môi trường.
3. Seed code có tiền tố riêng cho simulator.
4. Thêm health/dependency để simulator chờ app sẵn sàng.

Xong khi: cấu hình 20 tạo đúng 20 trụ online trong một phút.

### T-56 — CI chạy 20 simulator

Phụ thuộc: T-55.

1. Chạy sau unit/integration test.
2. Dựng app, database và simulators.
3. Gọi script T-46 và thu log/artifact.
4. Thất bại phải ghi rõ session và kWh lệch.

Xong khi: cố ý phá logic phục hồi làm CI đỏ với thông tin hữu ích.

### T-57 — Audit log chỉ ghi thêm

Phụ thuộc: T-50.

1. Tạo `audit_logs`: actor, action, object type/id, metadata JSON và time.
2. Viết một service dùng chung để insert.
3. Không cung cấp update/delete trong ứng dụng.
4. Giới hạn quyền database của tài khoản app nếu môi trường cho phép.
5. Không ghi id tag hoặc dữ liệu cá nhân nhạy cảm.
6. Thay log tạm ở Reset/RemoteStop/manual close.

Xong khi: các thao tác sinh đúng log và update/delete bị chặn.

### T-58 — API tra audit log

Phụ thuộc: T-57.

1. Chỉ admin/operator truy cập.
2. Lọc theo charge point, actor và khoảng thời gian.
3. Phân trang 50 dòng, thứ tự mới nhất trước.
4. Tạo index theo thời gian và các filter phổ biến.

Xong khi: tìm đúng log Reset và phân trang ổn định.

## 7. Checklist trước khi báo “xong task”

```text
[ ] Dependency đã merge trước khi bắt đầu
[ ] Đã thống nhất API/database với người còn lại
[ ] Chỉ sửa phạm vi của task
[ ] Không có secret hoặc dữ liệu nhạy cảm trong code/log
[ ] Migration chạy tiến và lùi
[ ] Test chứng minh acceptance criteria
[ ] Ruff, mypy và pytest đều xanh
[ ] Swagger cập nhật đúng với API HTTP
[ ] Đã tự chạy luồng thành công và luồng lỗi
[ ] PR có hướng dẫn kiểm tra
[ ] Người còn lại đã review
[ ] CI xanh trước khi merge
```

## 8. Khi bị kẹt

Đừng chỉ nhắn “task bị lỗi”. Hãy gửi:

```text
Mình đang làm task nào?
Mình đã chạy lệnh nào?
Kết quả mong đợi là gì?
Kết quả thực tế/error là gì?
Mình đã thử những gì?
Commit hoặc branch hiện tại là gì?
```

Ví dụ:

```text
Mình đang làm T-04 trên feature/T-04-users-roles.
`alembic downgrade -1` lỗi vì bảng roles còn được user_roles tham chiếu.
Mình mong migration rollback sạch.
Mình đã thử đổi thứ tự drop nhưng chưa đúng.
Commit hiện tại: abc1234.
```

Thông tin cụ thể giúp người còn lại hỗ trợ nhanh và không phải đoán.

