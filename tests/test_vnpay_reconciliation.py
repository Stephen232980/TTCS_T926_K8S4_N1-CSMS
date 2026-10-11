"""QueryDR authenticated provider results, RBAC and shared ledger arbitration."""
# ruff: noqa: F811

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.payments import vnpay_query
from src.modules.wallet.topup_models import WalletTopup
from src.platform.audit.models import AuditLog
from src.platform.database.session import SessionFactory
from tests.test_vnpay_sandbox import IPN, SECRET, callback, flow, state  # noqa: F401

PATH = "/api/v1/admin/payments/vnpay/topups/{}/reconcile"


def signed_result(order, **changes):
    data = {
        "vnp_ResponseId": "queryResponse1",
        "vnp_Command": "querydr",
        "vnp_ResponseCode": "00",
        "vnp_Message": "Success",
        "vnp_TmnCode": "TEST1234",
        "vnp_TxnRef": order,
        "vnp_Amount": "5000000",
        "vnp_BankCode": "NCB",
        "vnp_PayDate": "20261011151000",
        "vnp_TransactionNo": dict(callback(order))["vnp_TransactionNo"],
        "vnp_TransactionType": "01",
        "vnp_TransactionStatus": "00",
        "vnp_OrderInfo": "Nap vi CSMS",
        "vnp_PromotionCode": "",
        "vnp_PromotionAmount": "",
    }
    data.update(changes)
    # Independent protocol field order, not the production helper/constants.
    keys = [
        "ResponseId",
        "Command",
        "ResponseCode",
        "Message",
        "TmnCode",
        "TxnRef",
        "Amount",
        "BankCode",
        "PayDate",
        "TransactionNo",
        "TransactionType",
        "TransactionStatus",
        "OrderInfo",
        "PromotionCode",
        "PromotionAmount",
    ]
    value = "|".join(data.get("vnp_" + k, "") for k in keys)
    data["vnp_SecureHash"] = hmac.new(
        SECRET.encode(), value.encode(), hashlib.sha512
    ).hexdigest()
    return data


@pytest.fixture
def admin(flow, monkeypatch):
    _, driver, _ = flow
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        driver, frozenset({"admin"})
    )
    monkeypatch.setenv("VNPAY_QUERY_IP", "23.100.101.246")
    get_settings.cache_clear()
    yield
    app.dependency_overrides.pop(get_current_actor, None)
    get_settings.cache_clear()


def mock_provider(monkeypatch, result, captured=None):
    async def handle(request):
        assert str(request.url) == vnpay_query.QUERY_URL
        data = json.loads(request.content)
        keys = [
            "RequestId",
            "Version",
            "Command",
            "TmnCode",
            "TxnRef",
            "TransactionDate",
            "CreateDate",
            "IpAddr",
            "OrderInfo",
        ]
        value = "|".join(data["vnp_" + k] for k in keys)
        assert (
            data["vnp_SecureHash"]
            == hmac.new(SECRET.encode(), value.encode(), hashlib.sha512).hexdigest()
        )
        assert data["vnp_IpAddr"] == "23.100.101.246"
        assert data["vnp_Command"] == "querydr"
        if captured is not None:
            captured.append(data)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(200, json=result)

    monkeypatch.setattr(
        vnpay_query,
        "query_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )


async def test_preview_then_apply_replay_and_audit(flow, admin, monkeypatch):
    client, driver, order = flow
    captured = []
    mock_provider(monkeypatch, signed_result(order), captured)
    result = await client.post(PATH.format(order), json={})
    assert result.status_code == 200, result.text
    assert result.json()["applied"] is False
    assert await state(driver, order) == ("pending", 0, 0)
    async with SessionFactory() as db:
        topup = await db.scalar(
            select(WalletTopup).where(WalletTopup.order_id == order)
        )
        assert captured[0]["vnp_TransactionDate"] == topup.created_at.astimezone(
            ZoneInfo("Asia/Ho_Chi_Minh")
        ).strftime("%Y%m%d%H%M%S")
    for index in range(2):
        result = await client.post(PATH.format(order), json={"apply": True})
        assert result.status_code == 200, result.text
        assert result.json()["applied"] is (index == 0)
    assert await state(driver, order) == ("succeeded", 50000, 1)
    assert len({r["vnp_RequestId"] for r in captured}) == 3
    async with SessionFactory() as db:
        rows = (
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.object_id == str(topup.id),
                    AuditLog.action.like("vnpay_reconciliation_%"),
                )
            )
        ).all()
        assert len(rows) == 3
        assert all(
            row.actor_id == driver and row.permission == "admin.wallet.topup.reconcile"
            for row in rows
        )
        assert SECRET not in str([row.data for row in rows])


@pytest.mark.parametrize(
    "changes",
    [
        {"vnp_TransactionStatus": "01"},
        {"vnp_TransactionStatus": "04"},
        {"vnp_TransactionStatus": "07"},
        {"vnp_ResponseCode": "91"},
        {"vnp_ResponseCode": "94"},
    ],
)
async def test_unresolved_never_finalizes(flow, admin, monkeypatch, changes):
    client, driver, order = flow
    mock_provider(monkeypatch, signed_result(order, **changes))
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 200, result.text
    assert not result.json()["applied"]
    assert await state(driver, order) == ("pending", 0, 0)


async def test_verified_failure_is_not_query_success_credit(flow, admin, monkeypatch):
    client, driver, order = flow
    mock_provider(monkeypatch, signed_result(order, vnp_TransactionStatus="02"))
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 200, result.text
    assert await state(driver, order) == ("failed", 0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"vnp_TmnCode": "OTHER123"},
        {"vnp_TxnRef": "vnpay" + "a" * 32},
        {"vnp_TransactionType": "02"},
        {"vnp_TransactionNo": "0"},
        {"vnp_Amount": "5000001"},
    ],
)
async def test_signed_inconsistent_response_rejected(flow, admin, monkeypatch, changes):
    client, driver, order = flow
    mock_provider(monkeypatch, signed_result(order, **changes))
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 502
    assert await state(driver, order) == ("pending", 0, 0)


async def test_bad_signature_timeout_amount_and_legacy_date(flow, admin, monkeypatch):
    client, driver, order = flow
    data = signed_result(order)
    data["vnp_SecureHash"] = "a" * 128
    for response in [data, httpx.ReadTimeout("private provider error")]:
        mock_provider(monkeypatch, response)
        result = await client.post(PATH.format(order), json={"apply": True})
        assert result.status_code == 502 and "private" not in result.text
        assert await state(driver, order) == ("pending", 0, 0)
    captured = []
    mock_provider(monkeypatch, signed_result(order, vnp_Amount="6000000"), captured)
    result = await client.post(
        PATH.format(order), json={"transaction_date": "20261011151000"}
    )
    assert result.json()["requires_review"]
    assert await state(driver, order) == ("pending", 0, 0)
    assert captured[0]["vnp_TransactionDate"] == "20261011151000"
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 200
    assert await state(driver, order) == ("needs_review", 0, 0)


async def test_query_and_ipn_race_credit_once(flow, admin, monkeypatch):
    client, driver, order = flow
    mock_provider(monkeypatch, signed_result(order))
    results = await asyncio.gather(
        client.post(PATH.format(order), json={"apply": True}),
        client.get(IPN, params=callback(order)),
        client.post(PATH.format(order), json={"apply": True}),
    )
    assert all(r.status_code == 200 for r in results)
    assert await state(driver, order) == ("succeeded", 50000, 1)


@pytest.mark.parametrize(
    "roles", [None, {"driver"}, {"accountant"}, {"station_owner"}, {"operator"}]
)
async def test_nonadmin_makes_no_external_request(flow, monkeypatch, roles):
    client, _, order = flow
    mocked = AsyncMock()
    monkeypatch.setattr(vnpay_query, "query_client", mocked)
    if roles is not None:
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            flow[1], frozenset(roles)
        )
    else:
        client.cookies.clear()
    try:
        result = await client.post(PATH.format(order), json={})
        assert result.status_code == (401 if roles is None else 403)
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
    mocked.assert_not_called()


async def test_invalid_date_missing_ip_and_unknown(flow, admin, monkeypatch):
    client, driver, order = flow
    result = await client.post(
        PATH.format(order), json={"transaction_date": "20261399151000"}
    )
    assert result.status_code == 422
    result = await client.post(PATH.format("vnpay" + "a" * 32), json={})
    assert result.status_code == 404
    monkeypatch.setenv("VNPAY_QUERY_IP", "")
    get_settings.cache_clear()
    result = await client.post(PATH.format(order), json={})
    assert result.status_code == 503
    assert await state(driver, order) == ("pending", 0, 0)


async def test_commit_failure_rolls_back_credit_and_audit(flow, admin, monkeypatch):
    client, driver, order = flow
    mock_provider(monkeypatch, signed_result(order))
    original = AsyncSession.commit

    async def fail_commit(self):
        raise SQLAlchemyError("private SQL details")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 503 and "private" not in result.text
    assert await state(driver, order) == ("pending", 0, 0)
    monkeypatch.setattr(AsyncSession, "commit", original)
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 200
    assert await state(driver, order) == ("succeeded", 50000, 1)


@pytest.mark.parametrize(
    "raw",
    [
        b"not JSON",
        b'{"vnp_TmnCode":"A","vnp_TmnCode":"B"}',
        b"[]",
        b'{"vnp_Amount":5000000}',
        b"a" * 32769,
    ],
    ids=["not-json", "duplicate-key", "array", "non-string", "oversize"],
)
async def test_malformed_query_never_changes_wallet(flow, admin, monkeypatch, raw):
    client, driver, order = flow
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=raw))
    monkeypatch.setattr(
        vnpay_query, "query_client", lambda: httpx.AsyncClient(transport=transport)
    )
    result = await client.post(PATH.format(order), json={"apply": True})
    assert result.status_code == 502
    assert await state(driver, order) == ("pending", 0, 0)


async def test_creation_time_is_reused_in_payment_url(flow):
    _, _, order = flow
    # The same persisted timestamp now drives PAY and future QueryDR.
    from urllib.parse import parse_qs, urlsplit

    from src.modules.payments.contracts import PaymentRequest
    from tests.test_vnpay_sandbox import adapter

    async with SessionFactory() as db:
        topup = await db.scalar(
            select(WalletTopup).where(WalletTopup.order_id == order)
        )
        payment = await adapter().create_payment(
            PaymentRequest(
                order_id=order,
                amount_vnd=50000,
                return_url="https://csms.example/return",
                created_at=topup.created_at,
            )
        )
        assert parse_qs(urlsplit(str(payment.redirect_url)).query)[
            "vnp_CreateDate"
        ] == [
            topup.created_at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime(
                "%Y%m%d%H%M%S"
            )
        ]
