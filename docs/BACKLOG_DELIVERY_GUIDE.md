# Hướng dẫn giao backlog end-to-end

Tài liệu này là quy trình chuẩn để phân tích, triển khai, kiểm thử và chuẩn bị
Pull Request cho một backlog item. Mỗi backlog item có một người chịu trách
nhiệm xuyên suốt; việc chia thành task nhỏ chỉ phục vụ triển khai và kiểm tra,
không thay thế Acceptance Criteria (AC) hoặc Non-functional Requirements (NFR).

## 1. Nguồn yêu cầu và thứ tự ưu tiên

1. `.local/project-inputs/Backlog CSMS.xlsx` là nguồn tối thiểu bắt buộc cho
   phạm vi, story, AC, dependency và NFR của backlog.
2. Phải đọc đủ các cột: ID, Type, Parent/Epic, Title, Tier, Priority, Story,
   Acceptance Criteria, Dependencies, NFR và Owner.
3. Không dùng danh sách task kỹ thuật để xác định hoặc thu hẹp phạm vi,
   dependency, AC, phần backend/frontend hay kết luận backlog hoàn thành. Mã
   branch và commit phải là đúng mã Story trong file backlog.
4. Jira, khi truy cập được, chỉ dùng để kiểm tra giao việc và tiến độ hiện tại.
5. Git và Pull Request chỉ chứng minh trạng thái code. Tài liệu kiến trúc, API
   contract và hướng dẫn kỹ thuật quy định cách triển khai nhưng không được làm
   giảm phạm vi trong backlog.
6. Nếu backlog mâu thuẫn với code hoặc tài liệu và mâu thuẫn làm thay đổi đáng
   kể nghiệp vụ/phạm vi, phải ghi rõ và xin quyết định trước khi tiếp tục.
7. Không tự triển khai chức năng của backlog tương lai chỉ vì có liên quan.

## 2. Phân tích trước khi sửa code

Trước tiên xác nhận repository, worktree và dependency:

```powershell
git status --short
git branch --show-current
git log -1 --oneline
git fetch origin
git rev-list --left-right --count origin/main...HEAD
```

Không tiếp tục nếu worktree có thay đổi không rõ nguồn, có conflict hoặc
dependency bắt buộc chưa sẵn sàng. Không rebase branch do người khác quản lý.

Sau đó lập Coverage Matrix:

| AC/NFR | Hành vi cần có | Backend | Frontend | DB/Migration | Test/Demo | Task nhỏ |
| --- | --- | --- | --- | --- | --- | --- |
| AC/NFR cụ thể | Kết quả quan sát được | Có/Không | Có/Không | Có/Không | Bằng chứng dự kiến | `<ID>.n` |

Mỗi AC/NFR phải có ít nhất một task nhỏ và một bằng chứng kiểm chứng. Trình bày
mục tiêu, phạm vi, ngoài phạm vi, dependency, thứ tự task nhỏ, kế hoạch test và
rủi ro. Không bắt đầu code nếu matrix chưa bao phủ đủ AC/NFR.

## 3. Thiết kế end-to-end

- Nghiệp vụ: xác định actor, điều kiện trước, luồng thành công/lỗi, role,
  ownership, retry/concurrency và phản hồi cần hiển thị trên UI.
- Database: xác định entity, quan hệ, foreign key, unique/check constraint,
  index, transaction và migration upgrade/downgrade. Constraint quan trọng phải
  được bảo vệ ở server/database, không chỉ ở frontend.
- API: chốt method/path, authentication, role, request/response, validation,
  error, ownership, idempotency, concurrency và business rules. OpenAPI phải
  khớp hành vi thật.
- Backend: theo luồng `route -> validate -> authenticate -> authorize ->
  service -> transaction -> repository -> response schema`; repository không
  tự commit và route thiếu policy phải bị từ chối mặc định.
- Frontend: dùng API thật và xử lý loading, empty, success, validation,
  permission/business/network error, double-submit, trạng thái sau submit,
  responsive layout và accessibility cơ bản.
- Tích hợp: xác minh URL, payload, response, cookie/session, refresh, dữ liệu đã
  lưu, quyền khi gọi API trực tiếp và từng luồng lỗi trong AC.

Frontend mock, giao diện tĩnh hoặc riêng backend không phải bằng chứng backlog
đã hoàn thành nếu AC yêu cầu luồng tích hợp.

## 4. Quy trình cho một task nhỏ

Trước task nhỏ, báo cáo:

```text
Backlog:
Task nhỏ:
AC/NFR được bao phủ:
Dependency:
Phạm vi file/module dự kiến:
Hành vi dự kiến:
Kiểm tra sẽ chạy:
Điều kiện dừng:
```

Thực hiện theo thứ tự:

```text
đọc yêu cầu -> kiểm tra dependency/worktree -> chốt phạm vi và contract
-> triển khai -> kiểm tra hẹp -> xem toàn bộ diff -> quality gate phù hợp
-> stage từng file -> xem staged diff -> commit nhỏ -> task nhỏ tiếp theo
```

Không triển khai hàng loạt rồi mới kiểm tra. Chỉ tự sửa lỗi thuần formatting;
dừng khi có lỗi hành vi, type, test, migration, build hoặc conflict ngoài phạm
vi. Không tự commit hoặc push nếu người dùng chưa yêu cầu/xác nhận.

Sau task nhỏ, báo cáo file đã đổi, hành vi, AC/NFR được chứng minh, lệnh và kết
quả kiểm tra, phần còn lại và trạng thái sẵn sàng commit. Cập nhật bảng:

| Task nhỏ | AC/NFR | Backend | Frontend | Test | Trạng thái | Bằng chứng |
| --- | --- | --- | --- | --- | --- | --- |

## 5. Branch và commit

Một backlog dùng một feature branch chính cho cả backend và frontend:

```text
<type>/<backlog-id>-<mo-ta-kebab-case>
```

Commit theo mẫu:

```text
<type>(<backlog-id>): <mô tả ngắn bằng tiếng Việt>
```

Trước commit phải chạy kiểm tra phù hợp, xem `git status --short` và `git diff`,
stage từng đường dẫn cụ thể, rồi xem `git diff --cached`. Không dùng `git add .`
mặc định; không commit `.env`, secret, cache, dữ liệu thật hoặc file IDE.

## 6. Kiểm thử và quality gate

Mỗi backlog cần bằng chứng cho happy path, input sai, authentication, role,
ownership, database constraint, duplicate/idempotency và concurrency khi liên
quan, error response, trạng thái frontend, tích hợp frontend-backend, từng AC và
từng NFR có thể kiểm chứng. Nếu không tự động hóa hợp lý, cung cấp demo lặp lại
được gồm dữ liệu chuẩn bị, thao tác, kết quả mong đợi và cách xác minh.

Trạng thái bằng chứng chỉ dùng:

- `PASS`: đã chạy và đạt.
- `FAIL`: đã chạy và không đạt.
- `BLOCKED`: không thể chạy do dependency hoặc môi trường.
- `NOT RUN`: chưa chạy.

Backend, chạy bằng virtual environment của dự án:

```powershell
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m ruff check .
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m ruff format --check .
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m mypy src
C:\Users\LENOVO\CSMS\.venv\Scripts\python.exe -m pytest -q
```

Nếu đổi migration, đọc lại `upgrade()`/`downgrade()` và chạy:

```powershell
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic check
```

Frontend, chạy từ `C:\Users\LENOVO\CSMS\frontend`:

```powershell
npm run lint
npm test
npm run build
```

Quality gate chung:

```powershell
git diff --check
```

## 7. Definition of Done

Task nhỏ chỉ hoàn thành khi phạm vi và AC/NFR đã rõ, dependency sẵn sàng, code
và test/demo đúng phạm vi, kiểm tra hẹp đạt, diff sạch, staged diff chỉ chứa
increment hiện tại và Coverage Matrix đã cập nhật. Hoàn thành task nhỏ không có
nghĩa backlog đã hoàn thành.

Backlog chỉ `READY FOR REVIEW` khi mọi AC/NFR có bằng chứng `PASS`, dependency
đã xử lý, database/backend/frontend và tích hợp API thật đã hoàn chỉnh khi cần,
quyền và constraint đúng, full gate liên quan cùng demo end-to-end đạt, branch
chỉ chứa phạm vi backlog, tài liệu/PR đầy đủ, CI xanh, có reviewer và không còn
review comment chưa xử lý. Nếu còn `BLOCKED` hoặc `NOT RUN`, kết luận phải là
`NOT READY` và nêu rõ lý do.

## 8. Điều kiện dừng

Dừng và báo cáo khi dependency chưa hoàn thành; AC không rõ hoặc mâu thuẫn;
worktree có thay đổi không rõ nguồn; merge/rebase conflict; test hành vi,
typecheck, migration hoặc build thất bại; cần đổi ngoài backlog; cần sửa migration
đã merge; cần thao tác phá huỷ dữ liệu; cần push/merge/force-push chưa được phép;
hoặc không thể chứng minh một AC. Không hiển thị `.env`, password, token, cookie,
secret hoặc connection string thật.
