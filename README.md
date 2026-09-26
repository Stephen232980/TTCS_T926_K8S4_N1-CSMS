# CSMS Backend

CSMS là hệ thống quản lý trạm, trụ và phiên sạc. Repository này chứa backend
FastAPI. Frontend và bảng phân công sẽ được nhóm chốt riêng.

Tài liệu này dành cho người mới. Hãy làm đúng thứ tự và chỉ chuyển bước khi
bước hiện tại thành công.

## 1. Công nghệ

- Python 3.12+, FastAPI, Uvicorn
- SQLAlchemy 2 async, Psycopg 3, PostgreSQL 16
- Alembic
- Pytest, Ruff, mypy
- Docker Compose

## 2. Chuẩn bị máy

Cài Git, Python 3.12+ và Docker Desktop, sau đó kiểm tra trong PowerShell:

```powershell
git --version
python --version
docker --version
docker compose version
```

Nếu Docker báo lỗi kết nối, hãy mở Docker Desktop và chờ Docker Engine chạy.

### 2.1. Tạo SSH key để clone và push repository

Nếu repository dùng SSH, mỗi thành viên cần đăng ký public key với tài khoản
GitHub. Việc này chỉ thực hiện một lần trên mỗi máy.

#### Bước 1: Kiểm tra key hiện có

```powershell
Get-ChildItem $env:USERPROFILE\.ssh
```

Nếu đã có `id_ed25519` và `id_ed25519.pub`, có thể dùng lại sau khi xác nhận đó
là key của bạn. Không ghi đè key đang dùng nếu chưa biết mục đích của nó.

#### Bước 2: Tạo key mới

```powershell
ssh-keygen -t ed25519 -C "email-github-cua-ban@example.com"
```

Khi được hỏi nơi lưu, nhấn `Enter` để dùng đường dẫn mặc định. Nên đặt
passphrase để bảo vệ key nếu máy bị truy cập trái phép.

Hai file được tạo:

```text
~/.ssh/id_ed25519       # private key, tuyệt đối không chia sẻ
~/.ssh/id_ed25519.pub   # public key, dùng để đăng ký với GitHub
```

#### Bước 3: Bật SSH agent và nạp key

Mở PowerShell bằng quyền Administrator một lần để cấu hình service:

```powershell
Get-Service ssh-agent | Set-Service -StartupType Automatic
Start-Service ssh-agent
```

Sau đó, trong PowerShell thông thường:

```powershell
ssh-add $env:USERPROFILE\.ssh\id_ed25519
```

#### Bước 4: Sao chép public key

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | Set-Clipboard
```

Trên GitHub, mở **Settings → SSH and GPG keys → New SSH key**, đặt tên nhận biết
máy, dán public key rồi lưu. Không dán nội dung file không có đuôi `.pub`.

#### Bước 5: Kiểm tra kết nối

```powershell
ssh -T git@github.com
```

Lần đầu, kiểm tra hostname rồi nhập `yes` để lưu host key. Khi thành công,
GitHub sẽ xác nhận đã xác thực tài khoản; GitHub không cung cấp shell nên thông
báo không có shell access là bình thường.

Nếu nhóm dùng GitLab, đăng ký public key trong phần SSH Keys của GitLab và kiểm
tra bằng `ssh -T git@gitlab.com`.

#### Bước 6: Dùng remote SSH

Kiểm tra remote hiện tại:

```powershell
git remote -v
```

Nếu remote đang dùng HTTPS, đổi sang URL SSH do repository cung cấp:

```powershell
git remote set-url origin git@github.com:<organization>/<repository>.git
git remote -v
```

Thay `<organization>` và `<repository>` bằng giá trị thật. Sau đó có thể push:

```powershell
git push -u origin <tên-branch>
```

Nếu vẫn bị từ chối, kiểm tra bạn đã được thêm quyền vào repository; SSH key chỉ
xác thực danh tính, không tự cấp quyền truy cập dự án.

## 3. Lấy mã nguồn

```powershell
git clone <repository-url>
Set-Location CSMS
Get-ChildItem
```

Thay `<repository-url>` bằng URL nhóm cung cấp. Bạn phải nhìn thấy
`pyproject.toml`, `Dockerfile` và `docker-compose.yml`.

## 4. Tạo cấu hình local

```powershell
Copy-Item .env.example .env
```

Mở `.env` và thay `change_me` bằng mật khẩu riêng:

```env
POSTGRES_DB=csms
POSTGRES_USER=csms
POSTGRES_PASSWORD=change_me
DATABASE_URL=postgresql+psycopg://csms:change_me@localhost:5432/csms

AUTH_MAX_FAILED_ATTEMPTS=5
AUTH_LOCK_SECONDS=900
AUTH_SESSION_TTL_SECONDS=86400
AUTH_COOKIE_SECURE=false
```

Không commit `.env` và không dùng secret production. Khi backend chạy trên máy,
database host là `localhost`; khi backend chạy trong Compose, host là `db` và
Compose tự truyền URL phù hợp. `AUTH_COOKIE_SECURE=false` chỉ phù hợp với HTTP
local; môi trường chạy HTTPS phải đặt thành `true`.

## 5. Chạy toàn bộ bằng Docker (khuyến nghị)

### Bước 1: Build và khởi động

```powershell
docker compose up --build -d
```

### Bước 2: Chờ service sẵn sàng

```powershell
docker compose ps
```

Phải có `db` và `app`, cả hai ở trạng thái `healthy`. `app` tự chạy migration
trước khi khởi động Uvicorn.

### Bước 3: Kiểm tra API

- <http://localhost:8001/health/live>: tiến trình còn sống.
- <http://localhost:8001/health/ready>: kết nối database thành công.
- <http://localhost:8001/docs>: OpenAPI tương tác.

Hai health endpoint phải trả HTTP `200`.

Không chỉ dựa vào trạng thái `healthy` của container. Kiểm tra thêm từ máy
Windows để xác nhận cổng publish có thể truy cập:

```powershell
curl.exe -i http://127.0.0.1:8001/health/live
curl.exe -i http://127.0.0.1:8001/health/ready
```

### Bước 4: Xem log khi lỗi

```powershell
docker compose logs app
docker compose logs db
docker compose logs -f app
```

### Bước 5: Dừng

```powershell
docker compose down
```

Lệnh trên giữ dữ liệu. `docker compose down -v` xoá volume database, chỉ dùng
khi chủ động muốn mất toàn bộ dữ liệu local.

## 6. Chạy backend trên máy, database trong Docker

Cách này tiện khi phát triển vì Uvicorn tự reload.

### Bước 1: Tạo môi trường ảo

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Bước 2: Cài project

```powershell
python -c "import sys; print(sys.executable)"
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Đường dẫn do lệnh đầu tiên in ra phải trỏ tới
`CSMS\.venv\Scripts\python.exe`. Nếu không, cửa sổ PowerShell hiện tại đang dùng
nhầm Python hệ thống hoặc Anaconda. Các lệnh tường minh bên dưới vẫn bảo đảm
dùng đúng môi trường ảo. `-e` cho phép sửa source mà không cài lại; `[dev]` cài
công cụ kiểm tra.

### Bước 3: Chạy database

```powershell
docker compose up -d db
docker compose ps
```

Chờ `db` thành `healthy`.

### Bước 4: Chạy migration

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

### Bước 5: Chạy API

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.entrypoints.http:app --reload --port 8001
```

Kiểm tra các URL ở mục 5. Dừng bằng `Ctrl+C`.

Không chạy đồng thời API local và container `app` trên cùng cổng:

| Chế độ | Container cần chạy | API được phục vụ bởi |
| --- | --- | --- |
| Toàn bộ bằng Docker | `app`, `db` | Container tại `localhost:8001` |
| Phát triển trên máy | Chỉ `db` | Uvicorn local tại `localhost:8001` |

Khi chuyển sang chế độ phát triển trên máy:

```powershell
docker compose stop app
docker compose up -d db
.\.venv\Scripts\python.exe -m uvicorn src.entrypoints.http:app --reload --port 8001
```

## 7. Kiểm tra chất lượng

Bảo đảm database đang chạy, rồi thực hiện bằng đúng Python trong `.venv`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
```

- Ruff kiểm tra lỗi và quy ước code.
- Ruff format kiểm tra định dạng nhưng không tự sửa file.
- mypy kiểm tra kiểu dữ liệu.
- Pytest chạy test tự động.

Cả bốn lệnh phải thành công trước khi push.

Không chạy `docker compose exec app pytest`: image ứng dụng chỉ chứa dependency
runtime và không chứa thư mục `tests`. Chạy test trên máy bằng `.venv`; dùng
Docker để kiểm tra runtime của ứng dụng và PostgreSQL.

## 8. Migration

Sau khi thay đổi model, tạo migration:

```powershell
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "mo ta thay doi"
```

Đọc file vừa sinh, rồi kiểm tra cả chiều tiến và lùi:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Không tạo/sửa bảng bằng tay. Mọi thay đổi schema phải qua Alembic.

## 9. Cấu trúc repository

```text
CSMS/
├── src/
│   ├── entrypoints/       # Điểm vào HTTP, OCPP, worker
│   ├── modules/           # Module nghiệp vụ
│   ├── platform/          # Database, auth, event, log, job dùng chung
│   └── config.py          # Cấu hình môi trường
├── tests/                 # Test tự động
├── migrations/            # Alembic migration
├── docs/                  # Kiến trúc và hướng dẫn task
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

Chiều phụ thuộc bắt buộc:

```text
entrypoints -> modules -> platform
```

## 10. Lỗi thường gặp

### Cổng 8001 bị chiếm

Đổi mapping thành `8002:8000`, hoặc chạy Uvicorn với `--port 8002`.

### Cổng 5432 bị chiếm

Đổi mapping thành `5433:5432` và đổi cổng trong `DATABASE_URL` local thành
`5433`.

### `/health/ready` trả 503

```powershell
docker compose ps
docker compose logs db
alembic current
```

Kiểm tra database đang healthy và URL dùng đúng host (`localhost` ngoài
container, `db` trong Compose).

### Không kích hoạt được `.venv` trong PowerShell

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Bạn cũng có thể không kích hoạt môi trường mà gọi trực tiếp
`.\.venv\Scripts\python.exe` như các lệnh trong tài liệu này.

### Có `ModuleNotFoundError` dù đã cài dependency

Kiểm tra Python thực sự đang được sử dụng:

```powershell
python -c "import sys; print(sys.executable)"
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

Nếu hai đường dẫn khác nhau, hãy chạy lệnh bằng
`.\.venv\Scripts\python.exe -m <module>` thay vì `python` hoặc executable toàn
cục.

### Docker báo không tìm thấy Alembic revision

Ví dụ: `Can't locate revision identified by '<revision>'`. Trường hợp thường
gặp là image `app` được build từ source cũ trong khi database đã ở migration
mới hơn. Rebuild image và xem log:

```powershell
docker compose up --build -d
docker compose logs app
```

Không dùng `docker compose down -v` để sửa lỗi image cũ. Lệnh đó xóa toàn bộ dữ
liệu PostgreSQL local nhưng không cập nhật source trong image.

### Container healthy nhưng không truy cập được API từ Windows

Trạng thái `healthy` có thể chỉ chứng minh endpoint truy cập được từ bên trong
container. Kiểm tra URL từ host và cấu hình thực tế:

```powershell
curl.exe -i http://127.0.0.1:8001/health/live
docker compose config
docker compose logs app
docker inspect csms-app --format '{{json .Config.Cmd}}'
```

Trong log, Uvicorn trong container phải lắng nghe tại `0.0.0.0:8000`, không
phải `127.0.0.1:8000`.

### Script async dùng Psycopg lỗi event loop trên Windows

Với script Python độc lập truy cập database, dùng selector event loop:

```python
import asyncio
import selectors

asyncio.run(
    main(),
    loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
)
```

Ứng dụng, migration và test đã có cấu hình riêng; chỉ áp dụng đoạn trên cho
script độc lập gặp lỗi Proactor event loop.

### Không nhìn thấy session cookie sau khi đăng nhập

Swagger UI không hiển thị giá trị `Set-Cookie` qua JavaScript. Kiểm tra trong
Browser DevTools tại **Network** hoặc **Application/Storage**, hoặc dùng curl:

```powershell
curl.exe -i `
  -H "Content-Type: application/json" `
  -d '{"email":"email-cua-ban@example.com","password":"mat-khau-local"}' `
  http://localhost:8001/api/v1/auth/login
```

Response thành công phải có header `Set-Cookie` với `HttpOnly`. Không gửi mật
khẩu, token hoặc cookie thật khi nhờ người khác hỗ trợ.

## 11. Tài liệu cần đọc

1. [Kiến trúc hệ thống](docs/SYSTEM_ARCHITECTURE.md)
2. [Kế hoạch Sprint 1](docs/SPRINT_1_EXECUTION.md)
3. [Hướng dẫn task backend](docs/BACKEND_TASK_GUIDE.md)
4. [Quy tắc đóng góp](CONTRIBUTING.md)

Trước mỗi task, đọc dependency và tiêu chí hoàn thành. Nếu tài liệu khác
acceptance criteria trong backlog, acceptance criteria là nguồn kiểm tra cuối.
