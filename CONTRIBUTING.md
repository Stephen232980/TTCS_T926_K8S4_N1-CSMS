# Quy tắc đóng góp cho CSMS

Mọi thành viên backend tuân thủ tài liệu này để branch, commit, code, migration
và Pull Request nhất quán. Phân công cụ thể sẽ được nhóm chốt riêng.

## 1. Quy trình một task

```text
đọc task -> kiểm tra dependency -> nhận task -> cập nhật main -> tạo branch
-> chốt API/database -> code và test -> tự kiểm tra -> commit -> push
-> Pull Request -> review -> merge
```

Không bắt đầu nếu dependency bắt buộc chưa merge. Khi nhận task, báo theo mẫu:

```text
Task: T-05 — Đăng nhập, session và khoá tạm
Branch: feature/T-05-login
Phạm vi: src/modules/identity và migration sessions
API dự kiến: POST /api/v1/auth/login, POST /api/v1/auth/logout
Dependency: T-04 đã merge
Dự kiến mở PR: <ngày/giờ>
```

## 2. Branch

### Cú pháp

```text
<loại>/T-<số>-<mô-tả-kebab-case>
```

Biểu thức tham khảo:

```text
^(feature|fix|test|refactor|chore|ci|docs)/T-[0-9]+-[a-z0-9-]+$
```

Ví dụ hợp lệ:

```text
feature/T-05-login
fix/T-05-session-expiry
test/T-07-owner-scope
refactor/T-09-station-service
ci/T-02-quality-checks
docs/T-05-auth-contract
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
git switch -c feature/T-05-login
```

Không commit trực tiếp lên `main`, không gộp nhiều task không liên quan và không
dùng lại branch đã merge.

## 3. Commit

### Cú pháp

```text
<loại>(T-<số>): <mô tả ngắn bằng tiếng Việt>
```

Tài liệu chung không thuộc task có thể dùng `docs: <mô tả>`.

```text
feat(T-05): thêm đăng nhập bằng email và mật khẩu
test(T-05): kiểm tra khoá sau năm lần đăng nhập sai
fix(T-07): áp dụng ownership scope khi lấy danh sách trạm
ci(T-02): chạy Ruff, mypy và pytest trên pull request
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
git commit -m "feat(T-05): thêm đăng nhập bằng email và mật khẩu"
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

## 9. Kiểm tra trước khi push

```powershell
ruff check .
mypy src
pytest
```

Nếu đổi migration, chạy tiến/lùi. Nếu đổi Docker, chạy:

```powershell
docker compose up --build -d
docker compose ps
```

Nếu đổi API, kiểm tra `/docs`, luồng thành công và luồng lỗi.

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
[T-<số>] <mô tả ngắn bằng tiếng Việt>
```

Ví dụ: `[T-05] Thêm đăng nhập, session và khoá tạm`.

PR phải điền template, mô tả cách kiểm tra, nêu migration/API/biến môi trường
mới, có ít nhất một reviewer và CI xanh. Không merge khi còn conflict hoặc nhận
xét chưa giải quyết.

## 12. Definition of Done

```text
[ ] Dependency đã merge
[ ] Code đúng phạm vi task
[ ] Acceptance criteria có test hoặc demo lặp lại được
[ ] Ruff, mypy và Pytest thành công
[ ] Migration tiến/lùi thành công nếu có
[ ] OpenAPI đúng nếu API thay đổi
[ ] Không có secret hoặc dữ liệu nhạy cảm trong code/log
[ ] Tài liệu được cập nhật nếu cách chạy thay đổi
[ ] PR đã review và CI xanh
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
