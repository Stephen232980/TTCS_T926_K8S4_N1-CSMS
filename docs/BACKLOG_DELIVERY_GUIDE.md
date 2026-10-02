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

## Nền tảng OCPP Sprint 2–3

Nhóm kết nối OCPP (S-06/07/08/13/14) được giao cùng màn hình Kết nối trụ.
Xem [phạm vi, Coverage Matrix và cách kiểm thử](OCPP_FOUNDATION_DELIVERY.md). Registry hiện chạy
một process; nâng migration trước khi khởi động. Kiểm tra trạng thái Jira riêng
trước nghiệm thu. Phần bản đồ tài xế đã được tích hợp cùng trên nhánh cục bộ.


## Điều chỉnh Sprint 2–3 (02/10/2026)

Theo quyết định của người dùng, Sprint 2–3 triển khai theo chức năng với đầu ra DB/API/giao diện chạy thật. Quy tắc một story một nhánh và không làm sớm backlog tương lai được điều chỉnh trong phạm vi [kế hoạch chức năng](SPRINT_2_3_FUNCTION_PLAN.md); AC/NFR của story vẫn được giữ để đối chiếu. Bản đồ vị trí trạm cho tài xế được làm sớm theo yêu cầu mentor.

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
