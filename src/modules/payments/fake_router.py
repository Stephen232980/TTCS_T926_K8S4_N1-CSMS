"""Fake payment gateway routes and simulation UI (T-92)."""

import html
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.config import get_settings
from src.modules.identity.authorization import AccessPolicy, access_policy
from src.modules.payments.contracts import (
    AmountVnd,
    PaymentGatewayUnavailable,
    PaymentRequest,
)
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
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(min_length=1, max_length=128)
    amount_vnd: AmountVnd
    return_url: HttpUrl
    expires: int = Field(strict=True, gt=0)
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["succeeded", "failed", "cancelled"]
    reason: str | None = Field(default=None, max_length=500)
    repeat_count: int = Field(default=1, strict=True, ge=1, le=10)
    delay_seconds: float = Field(default=0.0, ge=0.0, le=10.0)


def validate_payment_link(
    order_id: str, amount_vnd: int, return_url: HttpUrl, expires: int, token: str
) -> None:
    settings = get_settings()
    try:
        payment = PaymentRequest(
            order_id=order_id, amount_vnd=amount_vnd, return_url=return_url
        )
    except ValueError as error:
        raise HTTPException(422, "Thông tin thanh toán không hợp lệ") from error
    if not FakeGateway(secret=settings.payment_webhook_secret).verify_payment_token(
        payment, expires, token
    ):
        raise HTTPException(403, "Liên kết thanh toán không hợp lệ hoặc đã hết hạn")


@router.get("/pay", response_class=HTMLResponse)
@access_policy(AccessPolicy("public", note="Fake payment gateway web page"))
async def fake_payment_page(
    return_url: Annotated[HttpUrl, Query()],
    order_id: str = Query(..., min_length=1, max_length=128),
    amount_vnd: int = Query(..., gt=0, le=2**63 - 1),
    expires: int = Query(..., gt=0),
    token: str = Query(..., pattern=r"^[a-f0-9]{64}$"),
    _: None = Depends(require_fake_gateway),
) -> HTMLResponse:
    """Render interactive simulation payment page with action buttons."""
    validate_payment_link(order_id, amount_vnd, return_url, expires, token)
    redirect_target = build_return_url(return_url, order_id)

    safe_order_id = html.escape(order_id)
    safe_amount = f"{amount_vnd:,}".replace(",", ".")
    safe_redirect_target = html.escape(redirect_target)
    safe_return_url = html.escape(str(return_url), quote=True)

    html_content = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cổng thanh toán giả lập - CSMS FakeGateway</title>
  <style>
    :root {{
      --bg: #f2f6f7;
      --card: #ffffff;
      --border: #b9cdd6;
      --text: #193d4b;
      --text-muted: #526e7b;
      --success: #14795e;
      --danger: #a32d35;
      --warning: #805c16;
      --info: #245d73;
      --purple: #526e7b;
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
      background: #f2f6f7;
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
      gap: 1rem;
    }}
    .row span.label {{ color: var(--text-muted); }}
    .row span.value {{ font-weight: 600; overflow-wrap: anywhere; min-width: 0; text-align: right; }}
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
    .alert-info {{ background: #eaf2f5; border: 1px solid var(--info); color: var(--text); }}
    .alert-success {{ background: #e9f5ef; border: 1px solid var(--success); color: var(--success); }}
    .alert-error {{ background: #fff0f0; border: 1px solid var(--danger); color: var(--danger); }}
    :focus-visible {{ outline: 3px solid var(--info); outline-offset: 3px; }}
    @media (max-width: 480px) {{ body {{ padding: 1rem; }} .container {{ padding: 1.25rem; }} }}
  </style>
</head>
<body>
  <div class="container">
    <div class="badge">SANDBOX SIMULATOR (T-92)</div>
    <h1>Cổng thanh toán giả lập</h1>
    <p class="subtitle">Chỉ dùng dữ liệu thử nghiệm. Gửi webhook không đồng nghĩa ví đã được cộng tiền.</p>

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

    <div id="status-box" role="status" aria-live="polite"></div>

    <a href="{safe_redirect_target}" data-return-url="{safe_return_url}" class="btn-return" id="link-return">
      ← Quay về ứng dụng tài xế
    </a>
  </div>

  <script>
    const orderId = document.getElementById('disp-order-id').textContent;
    const amountVnd = {amount_vnd};
    const returnTarget = document.getElementById('link-return').href;
    const returnUrl = document.getElementById('link-return').dataset.returnUrl;

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
            return_url: returnUrl,
            expires: {expires},
            token: "{token}",
            status: status,
            reason: reason,
            repeat_count: repeatCount,
            delay_seconds: delaySeconds
          }})
        }});

        const data = await res.json();
        if (res.ok) {{
          statusBox.className = 'alert-success';
          statusBox.textContent = `Endpoint đã nhận webhook (Mã GD: ${{data.gateway_transaction_id}}, trạng thái: ${{status}}). Kiểm tra trạng thái đơn nạp khi quay về ứng dụng.`;
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
    return HTMLResponse(
        content=html_content,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/dispatch")
@access_policy(AccessPolicy("public", note="Fake payment webhook trigger endpoint"))
async def fake_dispatch_webhook(
    request: Request,
    action: FakeDispatchAction,
    _: None = Depends(require_fake_gateway),
) -> dict[str, Any]:
    """Trigger HMAC-signed webhook dispatch from the simulator to CSMS webhook endpoint."""
    validate_payment_link(
        action.order_id,
        action.amount_vnd,
        action.return_url,
        action.expires,
        action.token,
    )
    settings = get_settings()
    gateway = FakeGateway(secret=settings.payment_webhook_secret)
    # Dispatch to the registered receiver on this application in every environment.
    # Neither the browser nor Host headers select an outbound destination.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url="http://fake-gateway.internal",
        timeout=15.0,
    ) as client:
        try:
            result = await gateway.dispatch_webhook(
                order_id=action.order_id,
                amount_vnd=action.amount_vnd,
                status=action.status,
                reason=action.reason,
                webhook_url="/api/v1/payments/webhook",
                repeat_count=action.repeat_count,
                delay_seconds=action.delay_seconds,
                client=client,
            )
        except PaymentGatewayUnavailable as error:
            raise HTTPException(
                502,
                "Endpoint webhook từ chối hoặc chưa khả dụng; chưa xác nhận nạp tiền",
            ) from error
    return {
        "status": "ok",
        "gateway_transaction_id": result["gateway_transaction_id"],
        "repeat_count": result["repeat_count"],
        "statuses": result["statuses"],
    }
