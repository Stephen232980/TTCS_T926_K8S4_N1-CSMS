# T-97 / S-39 — webhook lỗi và cảnh báo

PR #122 tiếp nối đóng góp ở PR #120. Giữ luồng T-95/T-96 tại
`payments/webhook_router.py` và `wallet/topup_webhook_service.py`; chỉ có một
`POST /api/v1/payments/webhook`. Không thay đổi admission của `PolicyRoute`.

## Contract cho T-98

Xác thực chữ ký trên raw body trước khi đọc đơn; kiểm tra số tiền trước khi
áp dụng bảng `TRANSITIONS` 5 trạng thái × 3 sự kiện.

| Callback | HTTP | Trạng thái cuối | Ví/sổ cái | Cảnh báo |
| --- | --- | --- | --- | --- |
| Thiếu/sai chữ ký | 401 | Giữ nguyên | Giữ nguyên | Log IP; không ghi payload/chữ ký |
| Đơn không tồn tại | 404 | Không có đơn | Giữ nguyên | `unknown_order` |
| Số tiền lệch | 400 | `needs_review`, trừ `succeeded` giữ nguyên | Giữ nguyên | `amount_mismatch` |
| Thành công sau thất bại/hủy | 200 | `needs_review` | Giữ nguyên | `late_success` |
| Thất bại/hủy sau thành công | 200 | `succeeded` | Giữ nguyên | `late_non_success` |
| Callback hợp lệ cho đơn `needs_review` | 200 | `needs_review` | Giữ nguyên | `review_callback`, hoặc bằng chứng bất thường đã ghi |
| Mã giao dịch khác mã đã ghi ở đơn | 200 | `needs_review`, trừ `succeeded` giữ nguyên | Giữ nguyên | `gateway_conflict` |
| Xung đột ví hoặc mã giao dịch đã dùng ở đơn khác | 200 | `needs_review` | Không ghi thêm | `settlement_conflict` |

Response giữ contract T-95: `status` và `received`; `received=true` chỉ với
HTTP 200. Callback không tự đưa đơn ra khỏi `needs_review`.

## Gom cảnh báo và bảo vệ dữ liệu

- Tái sử dụng `audit_logs`, không thêm schema/migration. Khóa gom gồm đơn và
  loại bất thường, không gồm mã callback do bên ngoài gửi. Bất thường khác vẫn
  có bằng chứng riêng; `failed`/`cancelled` sau thành công dùng chung một loại.
- Đơn có thật dùng UUID nội bộ và khóa dòng hiện có. Đơn không tồn tại dùng
  SHA-256 của `order_id` và transaction advisory lock trước khi tìm/ghi audit.
  Các request đồng thời và process mới cùng đọc dấu trong PostgreSQL.
- Callback lặp sau khi `late_success`/`settlement_conflict` đưa đơn vào review
  dùng lại bằng chứng đã có, không phát thêm `review_callback`.
- Audit và thay đổi nghiệp vụ cùng commit/rollback. Router phát log sau commit;
  rollback không lưu dấu và lần thử lại vẫn có thể ghi cảnh báo.
- Cảnh báo chỉ chứa tham chiếu nội bộ/hash, mã loại và lý do cố định. Không ghi
  raw body, chữ ký, secret, mã giao dịch bên ngoài hoặc reason của cổng vào
  log/audit cảnh báo. Lý do thất bại trong đơn giữ hành vi T-95 hiện có.
- Đây là gom cảnh báo nghiệp vụ cho callback đã xác thực; log IP khi chữ ký
  sai vẫn ghi theo lần bị từ chối để phục vụ theo dõi truy cập.
- Nếu process dừng sau commit nhưng trước khi phát log, bằng chứng audit vẫn
  còn; callback gửi lại không phát lại log. Nhật ký DB là bằng chứng bền vững.

## Coverage và kiểm tra

| Yêu cầu | Bằng chứng |
| --- | --- |
| Một endpoint, OpenAPI đúng | `test_only_one_payment_webhook_and_documented_http_contract` |
| Đủ 15 tổ hợp, HTTP/trạng thái/ví/sổ cái/cảnh báo | `test_all_fifteen_transitions_and_warning_contract` |
| Chữ ký/số tiền trước mọi trạng thái | `test_authentication_and_amount_precede_every_state` |
| Cả failed/cancelled và cảnh báo không lặp | `test_concurrent_retries_group_warnings_across_sessions` |
| Đơn không tồn tại, request đồng thời, dữ liệu an toàn | `test_unknown_order_retries_are_grouped_without_external_data` |
| Bất thường khác nhau có bằng chứng riêng, không hạ succeeded | `test_distinct_anomalies_keep_safe_evidence_and_preserve_success` |
| Rollback không nuốt cảnh báo lần thử lại | `test_warning_marker_rolls_back_and_retry_can_emit_after_commit` |
| Cộng tiền đúng một lần, xử lý đồng thời | Bộ T-95/T-96/T-98 hiện có |

Chạy trên PostgreSQL thử nghiệm đã nâng migration; không dùng DB demo/staging:

```text
alembic upgrade head
ruff check .
ruff format --check .
mypy src
pytest tests/test_t95_webhook_settlement.py tests/test_t96_webhook_idempotency.py tests/test_t97_webhook_errors.py tests/test_t98_webhook_tests.py -q
pytest -q
```

## Bằng chứng local ngày 11/10/2026

- Ruff lint/format và mypy: PASS cả Windows/Python 3.14 và Linux/Python 3.12.
- T-95/T-96/T-97/T-98 và endpoint policy inventory: 84 PASS trên PostgreSQL 16.
- Lifespan backend khởi động/tắt được; readiness HTTP 200.
- `alembic upgrade head` trên DB mới và `alembic check`: PASS; không thêm migration.
- Hồi quy chức năng lần đầu: 1.379 PASS, một test ví thất bại do đếm toàn bộ
  audit bằng 0. Đổi assertion thành số audit không tăng sau thao tác bị từ chối;
  kiểm tra lại toàn bộ `test_wallet_administration.py`: 34 PASS khi DB đã có
  cảnh báo webhook. Không sửa nghiệp vụ quản trị ví.
- Gate MeterValues nội bộ: PASS. Gate 20 socket thật vượt 200 ms trên Windows
  cả ở bản sửa (380 ms) và develop chưa sửa (364 ms); Linux/Python 3.12: PASS.
- Test dữ liệu nhạy cảm được kiểm tra lại với cả raw body và chữ ký thực tế: PASS.

CI của PR phải kiểm tra riêng trên commit đã push. Các kết quả trên không
xác nhận Jira Done hoặc đã triển khai staging.
