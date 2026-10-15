# G3 / S-46 — SMTP dùng chung cho domain outbox

G3 cung cấp transport tại `src/platform/email.py`. S-59 dùng outbox riêng,
không thêm notification tài xế vào `alert_emails` hoặc tạo incident giả.
Không có API HTTP hay migration mới trong thay đổi này.

## Contract cho S-59

```python
import asyncio
from src.platform.email import send_email, smtp_enabled

# Worker: claim/commit lease trước, gửi ngoài transaction DB.
# Nếu smtp_enabled() là False: giữ pending, không tiêu hao attempts.
await asyncio.to_thread(
    send_email,
    recipient=driver_email,
    subject=subject,
    text_body=body,
    message_id=stable_message_id,
)
```

Hàm đồng bộ, keyword-only, trả `None` khi SMTP chấp nhận. Không bảo đảm thư
đến inbox. Khi lỗi, hàm ném `OSError`, `smtplib.SMTPException` hoặc `ValueError`;
`EmailDisabledError` kế thừa `ValueError` khi transport tắt. Worker lưu mã lỗi
đã lọc, không log exception SMTP thô hoặc credentials. Hàm không tự retry,
không ghi DB, không cấp quyền, không tạo template và không sinh Message-ID.

S-59 chịu trách nhiệm email tài xế lấy từ backend, template, ba mốc
stop/idle/invoice ready, enqueue cùng transaction với domain event/inbox,
unique `(driver,event_type,event_id)`, lease/retry và retention/privacy.
Message-ID phải được lưu hoặc suy ra ổn định từ outbox identity, giữ nguyên
qua retry/restart. Giao nhận là at-least-once, không phải exactly-once.
Không gọi transport trên OCPP handler hoặc trong transaction DB.

## Cấu hình

```dotenv
SMTP_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_FROM=csms@example.com
SMTP_USERNAME=replace-on-server
SMTP_PASSWORD=replace-on-server
SMTP_TIMEOUT_SECONDS=5

# Bật/tắt riêng email cảnh báo vận hành, không ảnh hưởng S-59.
ALERT_SMTP_ENABLED=false
ALERT_EMAIL_RECIPIENTS=[]
```

`SMTP_ENABLED=true` chọn toàn bộ profile `SMTP_*`, không trộn credentials
hay host từ profile cũ. Cần host và sender, username/password phải có cùng
nhau; không cần danh sách operator để gửi email domain. Security hỗ trợ
`starttls`, `ssl`, `plain`; chỉ dùng `plain` cho SMTP local test.

`SMTP_ENABLED=false` tắt toàn bộ transport, không fallback sang legacy;
G3 không claim/tiêu hao attempts, UI hiện chưa cấu hình. Intent đã enqueue
vẫn còn để gửi sau khi bật lại.

Để nguyên `SMTP_ENABLED` rỗng hoặc không khai báo sẽ dùng toàn bộ profile
`ALERT_SMTP_*` cũ, gồm cả công tắc bật/tắt cũ. Deployment hiện hữu không cần
đổi biến môi trường ngay. Muốn S-59 độc lập công tắc email cảnh báo phải
chuyển sang profile `SMTP_*` rõ ràng. `ALERT_EMAIL_RECIPIENTS` chỉ dùng G3;
`ALERT_EMAIL_MAX_ATTEMPTS` và lease/retry G3 không thay đổi.

Docker Compose đã forward cả profile mới và cũ. Việc áp dụng env trên staging
là bước vận hành riêng; không commit credentials vào repository.

## Coverage và kiểm chứng

| Phạm vi | Bằng chứng |
| --- | --- |
| Transport không phụ thuộc incident/operator | Test gửi payload tài xế qua SMTP TCP local khi alert tắt |
| TLS/SSL/auth, giữ Message-ID, lỗi và recipient refusal | `tests/test_shared_email.py` |
| Profile mới/cũ, bật domain khi alert tắt, global disable | `tests/test_shared_email.py` |
| G3 vẫn enqueue/lease/retry và gửi nội dung cảnh báo đúng | `tests/test_operational_alerts.py`, cả hai profile với SMTP local thật |
| S-59 inbox/outbox và quyền tài xế | Ngoài phạm vi PR nền SMTP; S-59 triển khai riêng |

Các test SMTP local không chứng minh nhà cung cấp thật, staging hoặc email
đến inbox người dùng. Test transport không chứng minh S-59 đã hoàn thành.
