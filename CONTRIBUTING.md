# Đóng góp cho CSMS

CSMS có nhiều luồng liên quan chặt chẽ đến thiết bị, số đo và dữ liệu tài chính. Một thay đổi chỉ được xem là hoàn chỉnh khi hành vi từ giao diện hoặc bản tin OCPP đến dữ liệu lưu trữ được kiểm tra trong phạm vi đã thống nhất. Tài liệu này hướng dẫn cách chuẩn bị công việc, triển khai, kiểm chứng và gửi Pull Request để người review có thể đánh giá thay đổi một cách độc lập.

Nếu mới tham gia, bắt đầu bằng [README](README.md) để hiểu kiến trúc và khởi chạy local. Dùng tài liệu này trong quá trình phát triển; các runbook trong `docs/` cung cấp chi tiết cho từng nghiệp vụ hoặc môi trường vận hành.

## Nội dung

- [Xác định phạm vi](#xác-định-phạm-vi-trước-khi-triển-khai)
- [Nhánh, commit và đồng bộ mã nguồn](#nhánh-commit-và-đồng-bộ-mã-nguồn)
- [Nguyên tắc triển khai](#nguyên-tắc-triển-khai)
- [Schema và migration](#schema-và-migration)
- [Kiểm thử và bằng chứng](#kiểm-thử-và-bằng-chứng)
- [Chuẩn bị và review Pull Request](#chuẩn-bị-và-review-pull-request)
- [Môi trường dùng chung](#làm-việc-với-môi-trường-dùng-chung)
- [Báo lỗi và hỗ trợ](#báo-lỗi-và-nhờ-hỗ-trợ)

## Xác định phạm vi trước khi triển khai

Phạm vi Story, Acceptance Criteria (AC), dependency và Non-functional Requirements (NFR) được đối chiếu với `Backlog CSMS.xlsx` do nhóm quản lý. Bản sao local, khi có, nằm ở `.local/project-inputs/` và không được đưa vào Git. Jira là nơi kiểm tra giao việc, tiến độ hiện tại; commit, PR và CI là bằng chứng về mã nguồn và kiểm tra, không tự thay thế trạng thái nghiệm thu.

Trước khi code, đọc đủ AC/NFR, xác nhận dependency và thống nhất phần tích hợp cần có. Với Story nghiệp vụ, lập Coverage Matrix theo [hướng dẫn giao backlog](docs/BACKLOG_DELIVERY_GUIDE.md): mỗi tiêu chí cần gắn với hành vi quan sát được, phần backend/frontend/database liên quan và bằng chứng dự kiến. Không thu hẹp tiêu chí chỉ để khớp phần mình đã viết, cũng không tự mở rộng sang chức năng khác khi chưa thống nhất.

Với sửa lỗi hoặc tài liệu chung không có Story riêng, mô tả rõ vấn đề, phạm vi và kết quả mong đợi trong PR; không tự đặt mã Story. Khi yêu cầu hoặc tài liệu cũ mâu thuẫn làm thay đổi nghiệp vụ, cần làm rõ quyết định trước khi thực hiện phần phụ thuộc vào quyết định đó.

## Nhánh, commit và đồng bộ mã nguồn

### Luồng nhánh

`develop` là nhánh tích hợp công việc. Tạo nhánh chức năng, sửa lỗi hoặc tài liệu từ `origin/develop` và mở PR trở lại `develop`. `main` dùng cho luồng phát hành theo quyết định của nhóm; không tự chuyển PR công việc sang `main`, tạo nhánh tích hợp theo sprint hoặc thay ruleset để vượt điều kiện merge.

Một số tài liệu bàn giao theo sprint còn dùng ví dụ từ `main`; với công việc mới, áp dụng luồng `develop` được mô tả ở đây. Không commit trực tiếp lên hai nhánh dùng chung.

```powershell
git status --short
git fetch origin
git switch -c docs/cap-nhat-huong-dan origin/develop
```

Chỉ tạo hoặc chuyển nhánh sau khi đã hiểu các thay đổi đang có trong working tree. Không reset, stash hay xóa công việc của người khác để làm sạch môi trường. Khi cần xử lý nhiều việc song song, dùng checkout/worktree riêng thay vì trộn các thay đổi không liên quan.

Tên nhánh sử dụng tiền tố `feature/`, `fix/`, `test/`, `refactor/`, `chore/`, `ci/` hoặc `docs/`, tiếp theo là mô tả ngắn dạng kebab-case. Khi công việc gắn với Story/Spike, ghi đúng mã đó:

```text
feature/S-24-driver-start
fix/S-03-owner-scope
test/S-37-concurrent-settlement
docs/cap-nhat-readme-contributing
```

Giữ nhánh và PR đủ gọn để review. Các sửa đổi riêng cho admin, tài xế hoặc kế toán nên được tách khi độc lập; nếu thay thành phần dùng chung, nêu rõ mọi nơi sử dụng và kiểm tra chúng thay vì chỉ kiểm tra màn hình đang mở.

### Commit

Commit mô tả kết quả cụ thể, ví dụ `fix(S-03): chặn đọc trạm ngoài phạm vi sở hữu` hoặc `docs: cập nhật cách chạy frontend và database local`. Các loại thường dùng là `feat`, `fix`, `test`, `refactor`, `chore`, `ci`, `docs`. Không dùng tiêu đề như `update`, `done` hoặc `fix bug`.

```powershell
git diff
git add <cac-file-thuoc-pham-vi>
git diff --cached
git diff --cached --check
git commit -m "docs: cập nhật hướng dẫn phát triển"
```

Chọn file có chủ đích; không dùng `git add .` trước khi xem danh sách thay đổi. Không commit `.env`, mật khẩu, token, cookie, dữ liệu tài xế, backup, fixture môi trường thật hoặc file build/cache. Các thư mục như `.local/`, `.venv/`, `node_modules/` và `dist/` có quy tắc bỏ qua trong repository.

### Đồng bộ trước PR

```powershell
git fetch origin
git merge origin/develop
git push -u origin <ten-nhanh>
```

Giải quyết conflict dựa trên cả hai thay đổi và chạy lại kiểm tra bị ảnh hưởng. Rebase chỉ phù hợp khi bạn quản lý nhánh đó và đã thống nhất với người cùng dùng; không force-push lịch sử dùng chung để tránh một merge conflict. Sau khi cập nhật nhánh, không dùng kết quả test của SHA cũ để xác nhận SHA mới.

## Nguyên tắc triển khai

### Backend và API

Ứng dụng được lắp ghép trong `src/entrypoints/`; nghiệp vụ thuộc `src/modules/`; cấu hình và hạ tầng dùng chung ở `src/config.py` và `src/platform/`. Trong một module, router tiếp nhận HTTP/WS, schema kiểm tra contract, service xử lý nghiệp vụ, còn repository hoặc lớp truy vấn làm việc với database. Chỉ tạo lớp/file khi cần, không ép mọi module thành cùng một khuôn.

Giữ tên Python theo quy ước của dự án: module, biến và hàm dùng `snake_case`, lớp dùng `PascalCase`, hằng dùng `UPPER_SNAKE_CASE`. Áp dụng type hint, Ruff và mypy hiện có; tránh bỏ kiểm tra bằng `Any`, `type: ignore` hoặc tắt rule nếu chưa giải thích lý do. Không đưa logic nghiệp vụ vào entrypoint hoặc lặp lại cùng logic trong nhiều router.

API công khai dùng tiền tố `/api/v1`. Trước khi thay contract, làm rõ method/path, vai trò/quyền sở hữu, cookie/header, tham số, request/response, validation, lỗi và idempotency nếu có. Dùng schema phù hợp, không trả SQLAlchemy model trực tiếp. Endpoint HTTP mới phải khai policy qua cơ chế đang dùng trong `identity`; thiếu policy bị từ chối mặc định. Cả route đọc chi tiết và route liệt kê đều cần kiểm tra ownership, không tin ID hoặc vai trò do client tự gửi.

Cookie đăng nhập được backend quản lý với `HttpOnly`; không ghi cookie vào log hoặc lưu lại trong tài liệu. Giữ các bước validation/phân quyền tại backend ngay cả khi frontend đã ẩn thao tác không được phép. Khi thay API, cập nhật OpenAPI và tài liệu chuyên đề liên quan, nêu ảnh hưởng tới các caller trong PR.

### Giao dịch, số đo và dữ liệu tài chính

Thay đổi liên quan đến ví, phí, hóa đơn hoặc đối soát cần bảo toàn transaction, khóa và các ràng buộc chống trùng hiện có. Làm tròn tiền, đơn vị đo và thời gian phải theo contract nghiệp vụ, không thay đổi vì tiện cho giao diện. Service xác định ranh giới giao dịch; hàm truy vấn không tự commit khiến caller mất khả năng rollback toàn bộ thao tác.

Không suy ra phiên sạc đã kết thúc chỉ từ phản hồi `Accepted`, không tự dùng thời điểm server thay cho bằng chứng của trụ, và không sửa ledger hoặc hóa đơn đã chốt để làm số liệu khớp một bản demo. Các luồng cần tuân thủ tài liệu [MeterValues](docs/T40_METER_CONTRACT.md), [chiếm trụ đến khi rút súng](docs/S28_OCCUPATION_LIFECYCLE.md), [hóa đơn bất biến](docs/T83_INVOICE_IMMUTABILITY.md) và [chốt phiên, trừ ví](docs/T102_CLOSURE_SETTLEMENT.md).

### Frontend

Giao diện nằm trong `frontend/src/features/`, khung dùng chung trong `src/app/` và thành phần tái sử dụng trong `src/components/` của frontend. Giữ API helper, kiểu dữ liệu và trạng thái loading/error/empty nhất quán với feature. Một thao tác đang chờ hoặc chưa rõ kết quả không được tự biến thành thành công sau khi đóng hộp thoại, chuyển trang hay remount component.

Chỉ hiển thị hành động khi vai trò hiện tại có quyền sử dụng. Kiểm tra keyboard, focus, tên truy cập của control và thứ tự nội dung; không dựa riêng vào màu để truyền đạt trạng thái. Với thay đổi CSS dùng chung, rà mọi consumer và chú ý selector rộng có thể làm hiện/ẩn nhãn, nút hoặc nội dung ở vai trò khác.

Thay đổi responsive phải được xem ở **mobile, tablet và desktop**, gồm cả các điểm sát breakpoint của vùng được sửa. Với khu vực tài xế hiện tại, dùng ít nhất390×844, 820×1180, 1440×900, bổ sung320px và quanh700/1100px khi liên quan. Chụp ảnh cùng trạng thái để đối chiếu, kiểm tra tràn ngang, nội dung dài, focus và vùng thao tác bị thanh cố định che. Đây là các mẫu kiểm tra của dự án, không thay cho thử trên thiết bị thật hoặc bảo đảm mọi viewport đều đạt.

### OCPP và tác vụ nền

Socket registry đang ở trong tiến trình ứng dụng. Không tự bật nhiều Uvicorn worker hoặc triển khai thêm instance rồi giả định lệnh vẫn đến đúng kết nối. Thay handler OCPP cần xem xét frame lỗi, bản tin trùng/muộn, ngắt kết nối, nối lại và dữ liệu đã commit trước khi phản hồi.

Các loop nền được khởi tạo và dừng trong lifespan. Khi bổ sung tác vụ, phải xử lý hủy task, lỗi database, retry và idempotency theo luồng hiện có; không thêm worker trùng vào startup riêng khiến một nghiệp vụ chạy hai lần. Simulator là bằng chứng phần mềm, không thay thế kiểm chứng giao thức và trạng thái vật lý trên trụ thật.

## Schema và migration

Migration nằm trong `migrations/versions/`. Trước khi tạo revision, đồng bộ `develop`, kiểm tra chuỗi revision và cập nhật database phát triển đến head. Nếu thêm model, kiểm tra model đó đã được metadata của Alembic nạp qua `migrations/env.py`.

```powershell
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
```

Autogenerate là bản nháp. Đọc lại kiểu cột, nullable/default, foreign key, unique/index và ý nghĩa dữ liệu. Không sửa revision đã được merge hoặc đã áp dụng trên môi trường dùng chung; tạo migration tiếp theo. Không để xuất hiện nhiều head ngoài kế hoạch; giải quyết quan hệ revision rõ ràng trước khi gửi PR.

Trên database kiểm thử riêng, xác minh upgrade, downgrade và upgrade lại; với revision có chuyển đổi dữ liệu, đối chiếu dữ liệu trước/sau và giới hạn khôi phục thay vì chỉ nhìn exit code. Có thể dùng `alembic check` khi metadata đã được đồng bộ.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade -1
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

Không chạy downgrade trên staging để thử migration. Migration legacy settlement yêu cầu `LEGACY_SETTLEMENT_CUTOFF` được phê duyệt; mốc 1970 trong CI chỉ dành cho database kiểm thử rỗng. Tách tài khoản migration/runtime theo [hướng dẫn database staging](docs/STAGING_RUNTIME_DATABASE.md), và chuẩn bị backup cùng kế hoạch khôi phục trước thay đổi dữ liệu có rủi ro.

## Kiểm thử và bằng chứng

### Môi trường kiểm thử

Backend test hiện chủ yếu nằm trực tiếp trong `tests/test_*.py`; frontend đặt test cạnh feature/component dưới `frontend/src/`. Chọn test theo hành vi thay đổi và các miền liên quan; mock không thay thế được test PostgreSQL khi lỗi có thể nằm ở constraint, isolation hoặc concurrency.

Tạo database riêng có thể hủy, nâng migration rồi mới chạy bộ test database. Ví dụ dưới đây giả định Compose local dùng role `csms` và publish cổng `5433`; thay mật khẩu và role cho đúng cấu hình của bạn. Thực hiện trong terminal kiểm thử riêng để không làm môi trường server local vô tình dùng URL test.

```powershell
docker compose up -d db
docker compose exec db createdb -U csms csms_test
$env:DATABASE_URL = 'postgresql+psycopg://csms:<mat-khau-local>@localhost:5433/csms_test'
$env:LEGACY_SETTLEMENT_CUTOFF = '1970-01-01T00:00:00+00:00'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Chỉ chạy `createdb` khi database test chưa có. Không dùng database staging, production hoặc dữ liệu demo đang được sử dụng; một số test chủ động tạo/xóa bản ghi và kiểm tra chuyển đổi dữ liệu. `tests/conftest.py` tắt một số worker tự động và đặt cutoff mặc định cho test, nhưng điều đó không biến một database đang có dữ liệu thật thành môi trường an toàn.

### Các kiểm tra trước PR

Sau khi cài `.[dev,acceptance]` như README và chuẩn bị database kiểm thử:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Thay đổi frontend cần chạy từ `frontend/`:

```powershell
npm ci
npm run lint
npm test
npm run build
```

Chạy test tập trung khi phát triển để xác định lỗi nhanh, rồi chạy các kiểm tra đủ cho phạm vi PR. Với thay đổi chỉ có tài liệu, đối chiếu link, đường dẫn, biến cấu hình và lệnh với mã nguồn hiện tại; không cần tạo test lặp lại nội dung Markdown. Nếu chưa chạy được kiểm tra nào, ghi rõ lý do thay vì đánh dấu đã đạt.

Các test nên bao phủ thành công, input sai, phân quyền/ownership, lỗi phụ thuộc, retry và chống trùng khi liên quan. Với UI, thêm trạng thái loading, empty, lỗi và thay đổi dữ liệu khi màn hình vẫn mở; không chỉ chụp trạng thái cuối. Với dữ liệu tài chính, kiểm tra bất biến qua transaction và retry thật thay vì chỉ gọi service một lần với fixture thuận lợi.

### Bám sát pipeline

[`ci.yml`](.github/workflows/ci.yml) là nơi tra cứu lệnh CI thực tế. Hai gate độ trễ OCPP/MeterValues được chạy trong các tiến trình Pytest riêng trước suite chức năng để tránh ảnh hưởng cache/tải database. Khi sửa luồng này hoặc điều tra lỗi CI, tái hiện cùng thứ tự và tách tiến trình:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_charging_sessions.py::test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms -q -s
.\.venv\Scripts\python.exe -m pytest tests/test_s19_meter_latency.py::test_twenty_real_sockets_periodic_meter_replies_under_200ms -q -s
.\.venv\Scripts\python.exe -m pytest --deselect=tests/test_charging_sessions.py::test_committed_replay_and_twenty_concurrent_meter_replies_under_200ms --deselect=tests/test_s19_meter_latency.py::test_twenty_real_sockets_periodic_meter_replies_under_200ms
```

Sửa OCPP/simulator cần xem thêm [kịch bản 20 trụ](docs/S26_SIMULATOR_DELIVERY.md); sửa backup cần kiểm tra [workflow restore](.github/workflows/s62-backup.yml) và [runbook backup](docs/S62_BACKUP_RUNBOOK.md). Thành công của một phần suite không thay cho toàn bộ required checks của PR; điều kiện merge thực tế còn phụ thuộc ruleset/review đang áp dụng trên GitHub.

## Chuẩn bị và review Pull Request

Mở PR vào `develop` và điền [template](.github/PULL_REQUEST_TEMPLATE.md). Tiêu đề cần nêu vấn đề hoặc hành vi sau thay đổi; kèm mã Story nếu có. Mô tả dành cho người chưa đọc cuộc trao đổi triển khai: giải thích mục đích, phạm vi, tác động và cách tự kiểm tra.

PR cần cung cấp:

- Các thay đổi nghiệp vụ/API/schema/cấu hình có ảnh hưởng và dependency liên quan.
- Lệnh đã chạy, kết quả, môi trường và SHA tương ứng; tách phần chưa chạy hoặc chưa xác minh.
- Ảnh mobile/tablet/desktop nếu sửa giao diện; log hoặc dữ liệu đối chiếu đã bỏ thông tin nhạy cảm nếu sửa luồng nền/tài chính.
- Kế hoạch migration/khôi phục khi cần, giới hạn còn biết và hướng dẫn cho reviewer.

Không điền đạt cho backend test khi chỉ chạy frontend test, hoặc suy ra staging đã có thay đổi chỉ vì PR được merge. Mọi checkbox trong template phải phản ánh bằng chứng thật; ghi “không áp dụng” kèm lý do cho phần ngoài phạm vi.

Mời reviewer phù hợp với miền bị ảnh hưởng. Trước merge, kiểm tra base branch, conflict, CI của head hiện tại, review và các nhận xét chưa giải quyết. Sau một commit sửa review, chạy lại các kiểm tra liên quan. Không bỏ qua kiểm tra hoặc đổi ruleset để làm PR xanh.

### Điều kiện hoàn tất

Một thay đổi sẵn sàng để tích hợp khi phạm vi/AC/NFR đã được đối chiếu, luồng tích hợp và các trường hợp lỗi liên quan có bằng chứng, migration/API/cấu hình được mô tả đúng và kiểm tra yêu cầu đã đạt. Với Story cần nghiệm thu trên staging hoặc thiết bị thật, hoàn thành code/PR không tự hoàn thành phần nghiệm thu đó; cập nhật Jira theo quy trình của nhóm.

## Làm việc với môi trường dùng chung

Việc push/merge vào `develop` có thể kích hoạt triển khai staging theo workflow. Không dùng merge như thao tác “lưu tạm” hoặc triển khai khi chưa được giao quyền. Xem lại cấu hình và tình trạng dịch vụ trước thay đổi vận hành; bảo toàn volume, phiên đang mở, ledger và backup.

Không chạy các script seed, dọn dẹp hoặc demo lên môi trường dùng chung chỉ vì chúng có trong repository. Script local có tài khoản mẫu; script staging/manifest có phạm vi dữ liệu và tiền điều kiện riêng. Đọc đúng hướng dẫn, xác nhận namespace và tránh reset dữ liệu để che một lỗi tích hợp. Các runbook quan trọng gồm [manifest T-107/T-108](docs/T107_T108_MANIFEST.md), [runtime database](docs/STAGING_RUNTIME_DATABASE.md), [VNPAY sandbox](docs/S35_VNPAY_SANDBOX.md), [SMTP](docs/SHARED_SMTP.md) và [backup/restore](docs/S62_BACKUP_RUNBOOK.md).

Thông tin dùng trong PR, log và ảnh phải được loại bỏ mật khẩu, token, cookie, connection string thật và dữ liệu cá nhân không cần thiết. Nếu cần trao đổi cấu hình nhạy cảm, sử dụng kênh quản lý secret của nhóm; `.env.example` chỉ chứa cấu hình mẫu.

## Báo lỗi và nhờ hỗ trợ

Một báo cáo lỗi hữu ích cần đủ để người khác tái hiện mà không truy cập dữ liệu nhạy cảm. Ghi nhánh/SHA, môi trường, bước thực hiện, kết quả mong đợi, kết quả thực tế, lệnh/log đã lược bỏ secret và những cách đã thử. Với giao diện, thêm vai trò, kích thước màn hình và ảnh; với OCPP, thêm action, trạng thái kết nối và thời điểm liên quan; với tài chính, dùng mã định danh đã xử lý phù hợp và mô tả bất biến bị vi phạm.

Nêu rõ bằng chứng đang thuộc local, CI, staging hay thiết bị thật. Cách phân biệt này giúp nhóm sửa đúng nguyên nhân và tránh kết luận hoàn tất từ một lớp kiểm tra chưa đủ.
