# Nền phân quyền theo endpoint — 05/10/2026

## Phạm vi và quyết định

Theo yêu cầu người dùng, làm backend trước, giao diện admin trong PR tiếp theo.
Giữ `users`, `roles`, `user_roles`; cho phép nhiều vai trò. Không chọn vai trò thắng
để quyết định phạm vi dữ liệu. Chưa thêm vai trò mặc định, chưa áp đặt cặp cấm,
chưa triển khai khóa trạm quản trị hoặc nghiệp vụ tài chính mới.

Nguồn AC/NFR: `.local/project-inputs/Backlog CSMS.xlsx` ở checkout chính.
S-03 phụ thuộc S-02, S-11 phụ thuộc S-10, S-27 phụ thuộc S-23;
các nền đăng nhập, giám sát, điều khiển và API tài khoản đã có trên main 925642e.
S-61 được làm sớm theo nhóm chức năng đã được người dùng cho phép; backlog
chưa tự quyết định nhiều vai trò hay cặp vai trò loại trừ nhau.

| Căn cứ | Hành vi backend | Bằng chứng |
| --- | --- | --- |
| S-03 AC1 + NFR | Trạm/phiên/thẻ/trụ của chủ trạm được lọc trong truy vấn SQL, kể cả tài khoản có thêm admin/operator/accountant/driver | `test_explicit_scope_integration.py`, test ownership có sẵn |
| S-03 AC2 | Truy cập trạm người khác trả 403, log security; không sửa ảnh/trụ/trạm qua tài khoản nhiều vai trò | Test HTTP chéo sở hữu và test security log có sẵn |
| S-03 AC3 | Tài xế không có quyền gọi endpoint vận hành | Ma trận mọi tổ hợp vai trò và test điều khiển có sẵn |
| S-03 AC4 | Thiếu chính sách bị từ chối; CI kiểm tất cả route HTTP/WebSocket | `PolicyRoute`, guard chung, `test_endpoint_policy_inventory.py` |
| S-11 backend | Chủ trạm owned, operator all qua route riêng; SSE kiểm lại quyền từng snapshot; một truy vấn cho 20 trụ | Test giám sát/SSE/performance và ma trận sở hữu |
| S-27 mở rộng | Mã quyền endpoint và tập vai trò thời điểm request lưu cùng actor/action/result; không tin nhãn client | Test Reset audit và API tài khoản |
| S-61 backend | Vai trò đọc lại từ DB từng request; thêm/gỡ quyền dùng cùng cookie có hiệu lực ngay lần kế tiếp | Test phiên thật, không override actor |

Đây là bằng chứng nền backend, không tuyên bố hoàn tất AC giao diện của S-11
hay nghiệm thu toàn bộ S-61. Jira, CI remote và staging chưa được kiểm chứng ở bước này.

## Chính sách và thực thi

Mỗi endpoint thuộc đúng một loại `user`, `public`, `device`, `webhook`.
`user_policy(permission, scope, *roles)` khai báo mã quyền, phạm vi và vai trò
được cấp mã quyền ấy. Quyền là hợp các vai trò; phạm vi không suy ra từ hợp đó.

- `owned`: owner_id = user đang đăng nhập. Thẻ lọc issuer_id; phiên/trụ lọc
  owner_id của trạm. Tham số client không được chọn scope.
- `own`: dữ liệu/thao tác theo chính tài khoản, kiểm driver_id/actor_id trong handler.
  Danh mục trạm khả dụng cho tài xế chỉ là phép chiếu công khai của trạm active,
  không phải quyền đọc hồ sơ quản lý trạm.
- `own_wallet`: dành sẵn cho các endpoint ví sau này; chưa thêm API ví.
- `all`: chỉ những endpoint khai quyền toàn nền tảng cụ thể. Admin không tự có
  `ops.connector.reset`, `ops.session.stop` hoặc `ops.sessions.close`.

`PolicyRoute` tự gắn dependency kiểm quyền cho mọi route user; thiếu policy trả 403.
Guard ứng dụng kiểm khai báo cả HTTP và WebSocket. HTTP public gồm đăng nhập,
logout idempotent, root/liveness/readiness và tài liệu API sinh tự động.
OCPP là `device`, giữ nguyên kiểm tra mã trụ đã đăng ký/subprotocol S-06 và
ủy quyền Boot S-08; không kiểm vai trò người dùng. `webhook` là phân loại dành
cho tương lai: chưa có endpoint thanh toán hiện tại. Khi thêm phải có kiểm chữ
ký riêng, chữ ký sai trả 401; không gắn phân quyền người dùng. `PolicyRoute`
không cho endpoint webhook chạy chỉ nhờ nhãn khai báo.

Mã quyền và scope xuất hiện trong OpenAPI qua `x-access-policy`. Handler dùng
chung nhận `ActorScope` đã được dependency lấy từ policy của route hiện tại.
SSE giữ scope của route ban đầu và nạp lại session/roles ở mỗi snapshot; gỡ quyền
của route đang dùng sẽ gửi `access-denied` rồi kết thúc stream.

## Contract route và chuyển client

Cookie `session` vẫn giữ nguyên. Request/response, lọc, phân trang, validation,
idempotency của các handler hiện có không đổi, trừ phân quyền và trường audit bổ sung.

| Nhóm | Đường dẫn | Vai trò / phạm vi |
| --- | --- | --- |
| Chủ trạm | `/api/v1/owner/stations`, `/owner/charge-points`, `/owner/charging`, `/owner/ocpp/connections` | station_owner / owned |
| Alias chủ trạm hiện có | `/api/v1/stations`, `/charge-points`, `/charging` đọc/quản lý thẻ, `/ocpp/connections` | station_owner / owned |
| Vận hành đọc toàn mạng | `/api/v1/ops/stations`, `/ops/charging`, `/ops/ocpp/connections` | operator / all |
| Vận hành quản lý thẻ | POST/PATCH `/api/v1/ops/charging/cards...` | operator / all |
| Quản trị đọc toàn mạng | GET `/api/v1/admin/stations...`, `/admin/charging...`, `/admin/ocpp/connections...` | admin / all |
| Kế toán đọc phiên/số đo/lịch sử | GET `/api/v1/accounting/charging/sessions...` | accountant / all |
| Reset/RemoteStop | POST `/api/v1/ocpp/charge-points/{id}/reset`, `/ocpp/sessions/{id}/stop` | operator / all; admin đơn thuần 403 |
| Đọc yêu cầu lệnh | GET `/api/v1/ocpp/commands/{id}` | operator / own actor_id |
| Đóng hồ sơ bất thường | POST `/api/v1/charging/sessions/{id}/close` | operator / all; không gửi lệnh dừng trụ |
| Tài khoản, nhật ký, sức khỏe | Các endpoint quản trị hiện có | admin; contract cũ giữ nguyên |

Danh sách đầy đủ method/path/quyền/scope nằm trong [ROUTE_ACCESS_INVENTORY.csv](ROUTE_ACCESS_INVENTORY.csv).
Không tự tạo global grant cho mọi GET mới: global read/card write được allowlist
rõ trong `scoped_routes.py`. Owner route mới không tự được mở cho admin/operator.
Đường dẫn ảnh trả trong response dùng đúng namespace đã đọc trạm.

Thiếu cookie/phiên hết hạn trả 401; sai vai trò trả 403; trạm/trụ ngoài sở hữu
trả 403 + security log; phiên/thẻ ngoài phạm vi giữ 404 như contract hiện có.
Query scope không được hỗ trợ; query model trạm trả 422 nếu client thêm `scope`.

Không sửa frontend trong nhánh này. Chủ trạm vẫn dùng alias cũ với scope đúng.
Client vận hành/kế toán đang dùng route chủ trạm phải chuyển sang namespace mới
trước khi phát hành toàn bộ UI. Simulator verifier đã chuyển sang `/ops/ocpp/connections`.

## Gán vai trò và audit

`assign_user_roles` là đường gán chung cho API tạo/sửa tài khoản và seed simulator.
Khóa dòng user, kiểm tập vai trò cuối cùng (kể cả thêm vào vai trò đã có), rồi
thay assignment trong cùng transaction của caller. `FORBIDDEN_ROLE_PAIRS` để trống.
Test cấu hình cặp admin/accountant chỉ kiểm cơ chế, không áp đặt chính sách đó.
SQL thủ công có thể bỏ qua lớp ứng dụng; công cụ quản trị mới phải dùng hàm chung.

`AuditEvidence` lấy permission từ endpoint và roles từ actor đã đọc DB.
API account/control audit bổ sung `permission: string | null`,
`actor_roles: string[] | null`. Bản ghi trước migration giữ NULL, không suy đoán
tư cách lịch sử. Reset/Stop/RemoteStart HTTP lưu trong bảng control; đóng tay
lưu cùng details của sự kiện; thao tác tài khoản lưu cùng AccountAudit.
Idempotent replay giữ nguyên bằng chứng của thao tác ban đầu.

Migration `d030006a2026` nối `c630005a2026`, chỉ thêm cột nullable vào hai bảng audit.
Nâng migration trước khi chạy backend nhánh mới. Hạ migration làm mất các trường
bằng chứng mới, không xóa bản ghi audit cũ; chỉ kiểm hạ trên database thử nghiệm.

## Kiểm chứng cục bộ

- Ruff check/format, mypy strict và `git diff --check`.
- 401 tests đạt, gồm phục hồi thực 20 trụ qua WebSocket, snapshot dưới 2 giây,
  quyền theo tổ hợp, truy cập chéo sở hữu, thêm/gỡ vai trò với cùng phiên và audit.
- Migration upgrade/downgrade/upgrade và `alembic check` đạt trên DB thử nghiệm riêng.
- PR #53 kiểm kê 100 mục method/path, bao gồm HTTP, WebSocket và tài liệu API.
  Bổ sung lựa chọn mặc định nâng inventory hiện tại lên 101 mục;
  xem [DEFAULT_ROLE_DELIVERY.md](DEFAULT_ROLE_DELIVERY.md).

Sinh bảng (chạy tại root):

```powershell
python -m scripts.route_inventory --output docs/ROUTE_ACCESS_INVENTORY.csv
```

Khai policy trong router là nguồn chính; không điền quyền độc lập trong CSV rồi
để lệch với code. Test inventory bắt route chưa khai và kiểm snapshot CSV.
