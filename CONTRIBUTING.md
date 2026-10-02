# Quy tắc đóng góp cho CSMS

Mọi thành viên tuân thủ tài liệu này để branch, commit, code, migration và Pull
Request nhất quán. Mỗi backlog item được giao end-to-end, không chia trách nhiệm
hoàn thành theo riêng backend/frontend. Quy trình phân tích AC/NFR, Coverage
Matrix và bằng chứng hoàn thành nằm tại
[`docs/BACKLOG_DELIVERY_GUIDE.md`](docs/BACKLOG_DELIVERY_GUIDE.md).

## 1. Nguồn yêu cầu và quy trình một backlog

`.local/project-inputs/Backlog CSMS.xlsx` là nguồn duy nhất cho phạm vi, AC,
dependency và NFR. Mã branch, commit và Pull Request phải dùng đúng mã Story
`S-xx` (hoặc `K-xx` với Spike) trong backlog; không suy mã Story từ task kỹ thuật.
Jira chỉ phản ánh giao việc/tiến độ hiện tại; Git/PR chỉ phản ánh trạng thái code.

```text
đọc backlog -> lập Coverage Matrix -> kiểm tra dependency -> cập nhật main
-> tạo branch -> chia task nhỏ -> chốt API/database -> triển khai end-to-end
-> kiểm tra từng increment -> full gate -> chuẩn bị Pull Request -> review
```

Không bắt đầu nếu dependency bắt buộc chưa sẵn sàng hoặc AC/NFR chưa được bao
phủ đầy đủ. Khi nhận backlog, báo theo mẫu:

```text
Backlog: S-05 — <tên backlog>
Branch: feature/S-05-<mo-ta-ngan>
AC/NFR: <các tiêu chí được bao phủ>
Phạm vi: backend, frontend, database, test và tài liệu liên quan
API dự kiến: <method/path hoặc không có>
Dependency: <backlog phụ thuộc và trạng thái>
Kiểm tra dự kiến: <test/demo/quality gate>
```

## 2. Branch

### Cú pháp

```text
<loại>/<backlog-id>-<mô-tả-kebab-case>
```

Biểu thức tham khảo:

```text
^(feature|fix|test|refactor|chore|ci|docs)/(S|K)-[0-9]+-[a-z0-9-]+$
```

Ví dụ hợp lệ:

```text
feature/S-02-login
fix/S-02-session-expiry
test/S-03-owner-scope
refactor/S-04-station-service
ci/S-01-quality-checks
docs/S-02-auth-contract
```

| Loại | Mục đích |
| --- | --- |
| `feature` | Thêm chức năng |
| `fix` | Sửa lỗi |
| `test` | Chỉ thay đổi test |
| `refactor` | Đổi cấu trúc, không đổi hành vi |
| `chore` | Cấu hình, dependency, bảo trì |
| `ci` | CI/CD |
| `docs` | Tài liệu |

Tạo branch:

```powershell
git switch main
git pull --ff-only
git switch -c feature/S-02-login
```

Không commit trực tiếp lên `main`, không gộp nhiều task không liên quan và không
dùng lại branch đã merge.

## 3. Commit

### Cú pháp

```text
<loại>(<backlog-id>): <mô tả ngắn bằng tiếng Việt>
```

Tài liệu chung không thuộc task có thể dùng `docs: <mô tả>`.

```text
feat(S-02): thêm đăng nhập bằng email và mật khẩu
test(S-02): kiểm tra khoá sau năm lần đăng nhập sai
fix(S-03): áp dụng ownership scope khi lấy danh sách trạm
ci(S-01): chạy Ruff, mypy và pytest trên pull request
docs: bổ sung hướng dẫn chạy dự án
```

Loại commit: `feat`, `fix`, `test`, `refactor`, `chore`, `ci`, `docs`.

Mỗi commit phải là một thay đổi hoàn chỉnh, dễ review. Không dùng mô tả mơ hồ
như `update`, `fix bug`, `done`. Không commit `.env`, secret, cache hay file IDE.

```powershell
git status
git diff
git add <các-file-liên-quan>
git diff --cached
git commit -m "feat(S-02): thêm đăng nhập bằng email và mật khẩu"
```

Không dùng `git add .` mà chưa xem danh sách file.

## 4. Cấu trúc module

```text
src/modules/<module>/
├── router.py       # Route, dependency, chuyển lỗi HTTP
├── schemas.py      # Pydantic request/response
├── service.py      # Nghiệp vụ và transaction
├── repository.py   # Truy vấn database
└── models.py       # SQLAlchemy models
```

Chỉ tạo file khi cần. Chiều phụ thuộc:

```text
entrypoints -> modules -> platform
```

Được phép:

```text
entrypoint import public router của module
service import repository cùng module
repository import database từ platform
```

Không được phép:

```text
module import entrypoint
platform import module nghiệp vụ
module A import repository nội bộ module B
router chứa toàn bộ nghiệp vụ
repository tự commit
```

Luồng chuẩn:

```text
route -> validate -> authenticate -> authorize role/ownership
-> service -> transaction -> repository -> response schema
```

Service quyết định commit/rollback. Mỗi request hoặc tác vụ đồng thời dùng một
`AsyncSession` riêng.

## 5. Quy ước Python

- File, hàm, biến: `snake_case`.
- Class: `PascalCase`.
- Hằng số: `UPPER_SNAKE_CASE`.
- Hàm public phải có type annotation.
- Database/network/WebSocket dùng async; không gọi thư viện blocking trong
  event loop.
- Không dùng `print()` làm log ứng dụng.
- Không log password, token, `DATABASE_URL` hoặc toàn bộ id tag.
- Ruff, mypy strict và Pytest là bắt buộc.

## 6. API

Route nghiệp vụ dùng version:

```text
/api/v1/<resource>
```

Ví dụ:

```text
POST  /api/v1/auth/login
GET   /api/v1/stations
POST  /api/v1/stations
PATCH /api/v1/stations/{station_id}
```

Trước khi code API dùng bởi frontend, contract phải ghi:

```text
method/path; role; headers/cookie; path/query parameters; request JSON;
response thành công; response lỗi; validation; idempotency nếu có
```

Request/response dùng Pydantic schema. Không trả SQLAlchemy model trực tiếp.
Route mới phải khai policy; thiếu policy bị từ chối mặc định. Thay đổi contract
phải báo frontend và ghi trong PR. OpenAPI phải đúng với hành vi thực tế.

## 7. Database và migration

- Bảng/cột dùng `snake_case`; khoá chính là `id`.
- Khoá ngoại: `<entity>_id`, ví dụ `owner_id`.
- Thời gian dùng `timestamptz`; bảng mutable có `created_at`, `updated_at`.
- Unique constraint/index quan trọng phải nằm trong database.
- Repository không tự commit.

Trước khi tạo migration:

```powershell
git fetch origin
git rebase origin/main
alembic upgrade head
alembic revision --autogenerate -m "create users roles and user_roles"
```

Đọc `upgrade()` và `downgrade()`, kiểm tra kiểu cột, nullable, foreign key,
unique và index. Sau đó:

```powershell
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

Không sửa migration đã merge; tạo migration mới để sửa tiếp.

## 8. Test

```text
tests/
├── unit/          # Không cần database/network thật
├── integration/   # Dùng database hoặc nhiều lớp
└── fixtures/      # Dữ liệu/helper dùng chung
```

Cú pháp:

```text
test_<chức_năng>.py
test_<hành_vi>_<kết_quả_mong_đợi>()
```

Ví dụ:

```text
test_login_returns_session_for_valid_credentials
test_login_locks_account_after_five_failures
test_owner_cannot_read_another_owners_station
```

Mỗi task kiểm tra luồng thành công, input sai, quyền/ownership, constraint và
idempotency nếu liên quan. Test phải độc lập và không phụ thuộc thứ tự chạy.

## 9. Kiểm tra trước khi commit hoặc push

```powershell
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m ruff check .
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m ruff format --check .
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m mypy src
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m pytest -q
```

Nếu đổi migration, đọc lại `upgrade()`/`downgrade()`, chạy
`alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` và
`alembic check`. Nếu đổi Docker, chạy:

```powershell
docker compose up --build -d
docker compose ps
```

Nếu đổi API, kiểm tra `/docs`, luồng thành công và luồng lỗi. Nếu có frontend,
chạy `npm run lint`, `npm test`, `npm run build` từ thư mục `frontend`. Luôn chạy
`git diff --check`.

## 10. Đồng bộ và push

```powershell
git fetch origin
git rebase origin/main
ruff check .
mypy src
pytest
git push -u origin <tên-branch>
```

Chỉ rebase branch do bạn quản lý. Không force-push branch có người khác dùng nếu
chưa thống nhất.

## 11. Pull Request

Tiêu đề:

```text
[S-<số>] <mô tả ngắn bằng tiếng Việt>
```

Ví dụ: `[S-02] Thêm đăng nhập, session và khoá tạm`.

PR phải điền template, mô tả cách kiểm tra, nêu migration/API/biến môi trường
mới, có ít nhất một reviewer và CI xanh. Không merge khi còn conflict hoặc nhận
xét chưa giải quyết.

## 12. Definition of Done

```text
[ ] Đã đọc đủ Story và AC/NFR tương ứng trong Backlog CSMS.xlsx
[ ] Dependency bắt buộc đã sẵn sàng
[ ] Mọi AC/NFR có task nhỏ và bằng chứng PASS
[ ] Code đúng phạm vi backlog, bao gồm tích hợp frontend-backend nếu cần
[ ] Ruff check/format, mypy và Pytest thành công
[ ] Frontend lint, test và build thành công nếu có frontend
[ ] Migration tiến/lùi thành công nếu có
[ ] OpenAPI đúng nếu API thay đổi
[ ] Không có secret hoặc dữ liệu nhạy cảm trong code/log
[ ] Tài liệu được cập nhật nếu cách chạy thay đổi
[ ] Demo end-to-end thành công
[ ] PR đã review, không còn comment chưa xử lý và CI xanh
```

## 13. Khi bị kẹt

```text
Task và branch:
Commit hiện tại:
Lệnh đã chạy:
Kết quả mong đợi:
Kết quả thực tế/error:
Những cách đã thử:
File/module liên quan:
```

Không gửi `.env`, mật khẩu, token, cookie hoặc connection string thật.

## Nền tảng OCPP Sprint 2–3

Nhóm kết nối OCPP (S-06/07/08/13/14) được giao cùng màn hình Kết nối trụ.
Xem [phạm vi, Coverage Matrix và cách kiểm thử](docs/OCPP_FOUNDATION_DELIVERY.md). Registry hiện chạy
một process; nâng migration trước khi khởi động. Kiểm tra trạng thái Jira riêng
trước nghiệm thu. Phần bản đồ tài xế đã được tích hợp cùng trên nhánh cục bộ.


## Điều chỉnh Sprint 2–3 (02/10/2026)

Theo quyết định của người dùng, Sprint 2–3 triển khai theo chức năng với đầu ra DB/API/giao diện chạy thật. Quy tắc một story một nhánh và không làm sớm backlog tương lai được điều chỉnh trong phạm vi [kế hoạch chức năng](docs/SPRINT_2_3_FUNCTION_PLAN.md); AC/NFR của story vẫn được giữ để đối chiếu. Bản đồ vị trí trạm cho tài xế được làm sớm theo yêu cầu mentor.

## Nhóm giám sát S-09–S-12

Nhóm 2 bổ sung Heartbeat, trạng thái/lỗi đầu nối, offline theo lần liên lạc cuối
và màn hình SSE tự nối lại. Xem [phạm vi, API và kiểm chứng](docs/OCPP_MONITORING_DELIVERY.md).
Cần nâng migration a721093e4f62 trước khi chạy. Bằng chứng hiện là kiểm thử
cục bộ; trạng thái Jira/CI và nghiệm thu được kiểm tra riêng.

## Nhóm 3: phiên sạc OCPP

S-15, S-17, S-18, S-19, S-20 bổ sung xác thực thẻ, phiên sạc, số đo và kiểm tra dữ liệu; có màn hình quản lý phiên/thẻ/chờ đối chiếu dùng API thật. Nâng migration d830a62f194b trước khi chạy. Xem [Coverage Matrix, API, kiểm chứng và demo thủ công](docs/OCPP_CHARGING_DELIVERY.md). Đối chiếu/xử lý pending, đóng tay và điều khiển từ xa thuộc các nhóm tiếp theo. Bằng chứng local không thay thế Jira/CI.


## Nhóm 4: phục hồi phiên sạc

S-21 và S-25 bổ sung giữ phiên khi nối lại, nhận tin/số đo muộn theo transactionId, đánh dấu bất thường khi offline quá ngưỡng (mặc định 6 giờ), đóng tay có lý do và lịch sử. Giao diện có bộ lọc bất thường, xác nhận đóng tay và quyền đọc cho kế toán. Nâng migration e41b9027c6a8 trước khi chạy. Xem [AC, API, cấu hình và kiểm thử thủ công](docs/OCPP_RECOVERY_DELIVERY.md). Đóng tay hồ sơ không gửi lệnh dừng tới trụ; pending không khớp vẫn không tự gán phiên. Bằng chứng local không thay Jira/CI.

## Nhóm 5: điều khiển từ xa

S-16, S-23, S-27 thêm Reset, dừng phiên từ xa và nhật ký bất biến. Operator/admin gửi lệnh; admin lọc nhật ký. Accepted không tự đóng phiên; chờ StopTransaction thật, sau 2 phút thiếu tin kết thúc thì cần kiểm tra. Nâng migration f52c813d7a09. Xem [AC, API và test thủ công](docs/OCPP_CONTROL_DELIVERY.md). Bằng chứng local không thay Jira/CI.
