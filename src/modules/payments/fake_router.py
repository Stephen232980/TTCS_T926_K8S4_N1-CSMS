"""Fake payment gateway routes and simulation UI (T-92)."""

import html
from typing import Any, Literal
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from src.config import get_settings
from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.payments.fake_gateway import FakeGateway, build_return_url

router = APIRouter(prefix="/api/v1/payments/fake", tags=["payments"])


def require_fake_gateway() -> None:
    """Guard ensuring fake gateway endpoints are only enabled in 'fake' mode."""
    settings = get_settings()
    if settings.payment_gateway != "fake":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cổng thanh toán giả lập không khả dụng",
        )


class FakeDispatchAction(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    amount_vnd: int = Field(gt=0)
    status: Literal["succeeded", "failed", "cancelled"]
    reason: str | None = Field(default=None, max_length=500)
    gateway_transaction_id: str | None = Field(default=None, max_length=128)
    repeat_count: int = Field(default=1, ge=1, le=10)
    delay_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    webhook_url: str | None = None


@router.get("/pay", response_class=HTMLResponse)
@access_policy(AccessPolicy("public", note="Fake payment gateway web page"))
async def fake_payment_page(
    order_id: str = Query(..., min_length=1),
    amount_vnd: int = Query(..., gt=0),
    return_url: str | None = Query(default=None),
    _: None = Depends(require_fake_gateway),
) -> HTMLResponse:
    """Render interactive simulation payment page with action buttons."""
    settings = get_settings()
    effective_return_url = return_url or str(settings.payment_return_url)
    decoded_return_url = unquote(effective_return_url)
    redirect_target = build_return_url(decoded_return_url, order_id)

    safe_order_id = html.escape(order_id)
    safe_amount = f"{amount_vnd:,}".replace(",", ".")
    safe_redirect_target = html.escape(redirect_target)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cổng thanh toán giả lập - CSMS FakeGateway</title>
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
      --info: #3b82f6;
      --purple: #8b5cf6;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 1.5rem;
    }}
    .container {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 1rem;
      padding: 2rem;
      max-width: 520px;
      width: 100%;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
    }}
    .badge {{
      display: inline-block;
      background: rgba(59, 130, 246, 0.2);
      color: var(--info);
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.25rem 0.6rem;
      border-radius: 9999px;
      margin-bottom: 0.75rem;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.5rem; }}
    p.subtitle {{ color: var(--text-muted); font-size: 0.875rem; margin-bottom: 1.5rem; }}
    .order-info {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      padding: 1rem;
      margin-bottom: 1.5rem;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      padding: 0.4rem 0;
      font-size: 0.875rem;
    }}
    .row span.label {{ color: var(--text-muted); }}
    .row span.value {{ font-weight: 600; font-family: monospace; }}
    .row.total span.value {{ font-size: 1.125rem; color: var(--success); font-family: inherit; }}
    .button-group {{ display: flex; flex-direction: column; gap: 0.75rem; }}
    button {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      padding: 0.75rem 1rem;
      border: none;
      border-radius: 0.5rem;
      font-weight: 600;
      font-size: 0.925rem;
      cursor: pointer;
      transition: all 0.2s ease;
      color: #ffffff;
    }}
    button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    .btn-success {{ background: var(--success); }}
    .btn-success:hover:not(:disabled) {{ background: #059669; }}
    .btn-danger {{ background: var(--danger); }}
    .btn-danger:hover:not(:disabled) {{ background: #dc2626; }}
    .btn-warning {{ background: var(--warning); }}
    .btn-warning:hover:not(:disabled) {{ background: #d97706; }}
    .btn-repeat {{ background: var(--info); }}
    .btn-repeat:hover:not(:disabled) {{ background: #2563eb; }}
    .btn-delay {{ background: var(--purple); }}
    .btn-delay:hover:not(:disabled) {{ background: #7c3aed; }}
    .btn-return {{
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text-muted);
      margin-top: 1rem;
      text-decoration: none;
      text-align: center;
      display: block;
      padding: 0.75rem;
      border-radius: 0.5rem;
      font-size: 0.875rem;
    }}
    .btn-return:hover {{ color: var(--text); border-color: var(--text-muted); }}
    #status-box {{
      margin-top: 1rem;
      padding: 0.75rem;
      border-radius: 0.5rem;
      font-size: 0.85rem;
      display: none;
    }}
    .alert-info {{ background: rgba(59, 130, 246, 0.15); border: 1px solid var(--info); color: #93c5fd; }}
    .alert-success {{ background: rgba(16, 185, 129, 0.15); border: 1px solid var(--success); color: #6ee7b7; }}
    .alert-error {{ background: rgba(239, 68, 68, 0.15); border: 1px solid var(--danger); color: #fca5a5; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">SANDBOX SIMULATOR (T-92)</div>
    <h1>Cổng thanh toán giả lập</h1>
    <p class="subtitle">Mô phỏng phản hồi từ đối tác thanh toán CSMS</p>

    <div class="order-info">
      <div class="row">
        <span class="label">Mã đơn hàng:</span>
        <span class="value" id="disp-order-id">{safe_order_id}</span>
      </div>
      <div class="row total">
        <span class="label">Số tiền nạp:</span>
        <span class="value">{safe_amount} đ</span>
      </div>
    </div>

    <div class="button-group">
      <button id="btn-success" class="btn-success" onclick="handleAction('succeeded')">
        ✓ Thành công
      </button>
      <button id="btn-failed" class="btn-danger" onclick="handleAction('failed', 'Giao dịch bị từ chối bởi ngân hàng')">
        ✕ Thất bại
      </button>
      <button id="btn-cancelled" class="btn-warning" onclick="handleAction('cancelled', 'Khách hàng chủ động hủy')">
        ⊘ Hủy
      </button>
      <button id="btn-repeat" class="btn-repeat" onclick="handleAction('succeeded', null, 5, 0)">
        ⟳ Gửi lại webhook 5 lần (Idempotency)
      </button>
      <button id="btn-delay" class="btn-delay" onclick="handleAction('succeeded', null, 1, 10)">
        ⏱ Trễ webhook 10 giây (Timeout/Pending)
      </button>
    </div>

    <div id="status-box"></div>

    <a href="{safe_redirect_target}" class="btn-return" id="link-return">
      ← Quay về ứng dụng tài xế
    </a>
  </div>

  <script>
    const orderId = "{safe_order_id}";
    const amountVnd = {amount_vnd};
    const returnTarget = "{safe_redirect_target}";

    async function handleAction(status, reason = null, repeatCount = 1, delaySeconds = 0) {{
      const buttons = document.querySelectorAll('.button-group button');
      buttons.forEach(b => b.disabled = true);

      const statusBox = document.getElementById('status-box');
      statusBox.style.display = 'block';
      statusBox.className = 'alert-info';
      if (delaySeconds > 0) {{
        statusBox.textContent = `Đang đợi ${{delaySeconds}} giây trước khi gửi webhook...`;
      }} else if (repeatCount > 1) {{
        statusBox.textContent = `Đang gửi lặp ${{repeatCount}} lần cùng một giao dịch...`;
      }} else {{
        statusBox.textContent = 'Đang ký HMAC và gửi webhook tới backend...';
      }}

      try {{
        const res = await fetch('/api/v1/payments/fake/dispatch', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            order_id: orderId,
            amount_vnd: amountVnd,
            status: status,
            reason: reason,
            repeat_count: repeatCount,
            delay_seconds: delaySeconds
          }})
        }});

        const data = await res.json();
        if (res.ok) {{
          statusBox.className = 'alert-success';
          statusBox.textContent = `Webhook gửi thành công! (Mã GD: ${{data.gateway_transaction_id}}, trạng thái: ${{status}}). Đang quay về ứng dụng...`;
          setTimeout(() => {{ window.location.href = returnTarget; }}, 1500);
        }} else {{
          statusBox.className = 'alert-error';
          statusBox.textContent = `Lỗi gửi webhook: ${{data.detail || 'Không xác định'}}`;
          buttons.forEach(b => b.disabled = false);
        }}
      }} catch (err) {{
        statusBox.className = 'alert-error';
        statusBox.textContent = `Lỗi mạng khi kích hoạt webhook: ${{err.message}}`;
        buttons.forEach(b => b.disabled = false);
      }}
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.post("/dispatch")
@access_policy(AccessPolicy("public", note="Fake payment webhook trigger endpoint"))
async def fake_dispatch_webhook(
    request: Request,
    action: FakeDispatchAction,
    _: None = Depends(require_fake_gateway),
) -> dict[str, Any]:
    """Trigger HMAC-signed webhook dispatch from the simulator to CSMS webhook endpoint."""
    settings = get_settings()
    target_webhook_url = (
        action.webhook_url or "http://localhost:8000/api/v1/payments/webhook"
    )

    gateway = FakeGateway(
        base_url=str(settings.payment_return_url).rsplit("/", 3)[0]
        if "/wallet/" in str(settings.payment_return_url)
        else "http://localhost:8000",
        webhook_url=target_webhook_url,
        secret=settings.payment_webhook_secret,
    )

    test_client = None
    if request.base_url.hostname in (
        "test",
        "testserver",
    ) or target_webhook_url.startswith("http://test"):
        test_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=request.app),
            base_url=str(request.base_url).rstrip("/"),
        )

    try:
        result = await gateway.dispatch_webhook(
            order_id=action.order_id,
            amount_vnd=action.amount_vnd,
            status=action.status,
            reason=action.reason,
            gateway_transaction_id=action.gateway_transaction_id,
            webhook_url=target_webhook_url,
            repeat_count=action.repeat_count,
            delay_seconds=action.delay_seconds,
            client=test_client,
        )
    finally:
        if test_client is not None:
            await test_client.aclose()

    return {
        "status": "ok",
        "gateway_transaction_id": result["gateway_transaction_id"],
        "repeat_count": result["repeat_count"],
        "signature": result["signature"],
        "statuses": result["statuses"],
    }
