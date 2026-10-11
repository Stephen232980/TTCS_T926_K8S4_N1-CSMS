"""VNPAY wire-format vectors and real PostgreSQL callback settlement."""

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import HttpUrl, SecretStr, ValidationError
from sqlalchemy import func, select

from src.config import Settings, get_settings
from src.entrypoints.http import app
from src.modules.identity.models import Role, Session, User, UserRole
from src.modules.identity.security import hash_session_token
from src.modules.payments.contracts import (
    InvalidWebhookPayload,
    InvalidWebhookSignature,
    PaymentRequest,
)
from src.modules.payments.vnpay_gateway import VnpayGateway
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import SessionFactory

SECRET = "vnpay-only-test-secret"
IPN = "/api/v1/payments/vnpay/ipn"
RETURN = "/api/v1/payments/vnpay/return"


def adapter():
    return VnpayGateway(
        tmn_code="TEST1234",
        secret=SecretStr(SECRET),
        payment_url="https://sandbox.vnpayment.vn/paymentv2/vpcpay.html",
        return_url=HttpUrl("https://csms.example/api/v1/payments/vnpay/return"),
    )


def callback(order, **changes):
    params = {
        "vnp_TmnCode": "TEST1234",
        "vnp_Amount": "5000000",
        "vnp_TxnRef": order,
        "vnp_ResponseCode": "00",
        "vnp_TransactionStatus": "00",
        "vnp_TransactionNo": str(
            int(hashlib.sha256(order.encode()).hexdigest()[:12], 16)
        ),
        "vnp_OrderInfo": "Nap vi CSMS " + order,
    }
    params.update(changes)
    signature = hmac.new(
        SECRET.encode(), urlencode(sorted(params.items())).encode(), hashlib.sha512
    ).hexdigest()
    return list(params.items()) + [("vnp_SecureHash", signature)]


async def test_payment_url_wire_format():
    payment = await adapter().create_payment(
        PaymentRequest(
            order_id="topup-vnpay-" + "a" * 32,
            amount_vnd=50000,
            return_url="https://frontend.example/wallet/topup/return",
            client_ip="203.0.113.5",
        )
    )
    url = urlsplit(str(payment.redirect_url))
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    signature = params.pop("vnp_SecureHash")
    assert (
        signature
        == hmac.new(
            SECRET.encode(), urlencode(sorted(params.items())).encode(), hashlib.sha512
        ).hexdigest()
    )
    assert params["vnp_Amount"] == "5000000"
    assert params["vnp_IpAddr"] == "203.0.113.5"
    assert (
        params["vnp_ReturnUrl"] == "https://csms.example/api/v1/payments/vnpay/return"
    )
    assert params["vnp_Version"] == "2.1.0"
    assert datetime.strptime(params["vnp_ExpireDate"], "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    ) - datetime.strptime(params["vnp_CreateDate"], "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    ) == timedelta(minutes=15)
    assert SECRET not in str(payment)


@pytest.mark.parametrize(
    "changes",
    [
        {"vnp_Amount": "5000001"},
        {"vnp_Amount": "5e6"},
        {"vnp_TmnCode": "OTHER123"},
        {"vnp_ResponseCode": "00", "vnp_TransactionStatus": "02"},
        {"vnp_TransactionNo": "0"},
        {"vnp_TxnRef": "other"},
        {"vnp_TxnRef": "topup-" + "a" * 32},
    ],
)
def test_authenticated_invalid_result(changes):
    with pytest.raises(InvalidWebhookPayload):
        adapter().verify_query(callback("topup-vnpay-" + "a" * 32, **changes))


def test_tampered_missing_and_duplicated_signatures():
    items = callback("topup-vnpay-" + "a" * 32)
    for invalid in [
        items[:-1],
        items + [items[-1]],
        [(k, "1" if k == "vnp_Amount" else v) for k, v in items],
    ]:
        with pytest.raises(InvalidWebhookSignature):
            adapter().verify_query(invalid)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/return",
        "https://x:y@example.com/return",
        "https://example.com/return?url=evil",
    ],
)
def test_return_config_requires_plain_https(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, vnpay_return_url=url)


@pytest_asyncio.fixture
async def flow(monkeypatch):
    for name, value in {
        "PAYMENT_GATEWAY": "sandbox",
        "PAYMENT_WEBHOOK_SECRET": SECRET,
        "VNPAY_TMN_CODE": "TEST1234",
        "VNPAY_RETURN_URL": "https://csms.example" + RETURN,
        "PAYMENT_RETURN_URL": "https://csms.example/wallet/topup/return",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    token = uuid4().hex
    async with SessionFactory() as db, db.begin():
        role = await db.scalar(select(Role).where(Role.code == "driver"))
        driver = User(email=f"vnpay-{uuid4()}@example.com", password_hash="unused")
        db.add(driver)
        await db.flush()
        db.add(UserRole(user_id=driver.id, role_id=role.id))
        db.add(
            Session(
                user_id=driver.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        driver_id = driver.id
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://csms.example",
            cookies={"session": token},
        ) as client:
            response = await client.post(
                "/api/v1/driver/wallet/topups", json={"amount_vnd": 50000}
            )
            assert response.status_code == 201, response.text
            assert response.json()["redirect_url"].startswith(
                "https://sandbox.vnpayment.vn/"
            )
            yield client, driver_id, response.json()["order_id"]
    finally:
        get_settings.cache_clear()


async def state(driver_id, order):
    async with SessionFactory() as db:
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver_id))
        topup = await db.scalar(
            select(WalletTopup).where(WalletTopup.order_id == order)
        )
        count = await db.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
        )
        return topup.status, wallet.balance_vnd, count


async def test_return_never_credits_then_concurrent_ipns_credit_once(flow):
    client, driver, order = flow
    returned = await client.get(RETURN, params=callback(order))
    assert returned.status_code == 303
    assert parse_qs(urlsplit(returned.headers["location"]).query)["order_code"] == [
        order
    ]
    assert await state(driver, order) == ("pending", 0, 0)
    replies = await asyncio.gather(
        *(client.get(IPN, params=callback(order)) for _ in range(5))
    )
    assert sorted(r.json()["RspCode"] for r in replies) == [
        "00",
        "02",
        "02",
        "02",
        "02",
    ]
    assert await state(driver, order) == ("succeeded", 50000, 1)
    again = await client.get(IPN, params=callback(order))
    assert again.json()["RspCode"] == "02"
    assert await state(driver, order) == ("succeeded", 50000, 1)


@pytest.mark.parametrize("code,expected", [("24", "cancelled"), ("51", "failed")])
async def test_failure_and_cancellation_do_not_credit(flow, code, expected):
    client, driver, order = flow
    result = await client.get(
        IPN,
        params=callback(
            order,
            vnp_ResponseCode=code,
            vnp_TransactionStatus="02",
            vnp_TransactionNo="0",
        ),
    )
    assert result.json()["RspCode"] == "00"
    assert await state(driver, order) == (expected, 0, 0)
    late = await client.get(IPN, params=callback(order))
    assert late.json()["RspCode"] == "99"
    assert await state(driver, order) == ("needs_review", 0, 0)


async def test_bad_signature_unknown_order_and_amount_mismatch(flow, caplog):
    client, driver, order = flow
    result = await client.get(IPN, params=callback(order)[:-1])
    assert result.json()["RspCode"] == "97"
    assert "client_ip=" in caplog.text and SECRET not in caplog.text
    assert await state(driver, order) == ("pending", 0, 0)
    result = await client.get(IPN, params=callback("topup-vnpay-" + uuid4().hex))
    assert result.json()["RspCode"] == "01"
    result = await client.get(IPN, params=callback(order, vnp_Amount="4000000"))
    assert result.json()["RspCode"] == "04"
    assert await state(driver, order) == ("needs_review", 0, 0)


async def test_invalid_return_and_protocol_conflict_do_not_mutate(flow):
    client, driver, order = flow
    result = await client.get(RETURN, params=callback(order)[:-1])
    assert result.status_code == 400
    result = await client.get(IPN, params=callback(order, vnp_TransactionStatus="02"))
    assert result.json()["RspCode"] == "99"
    assert await state(driver, order) == ("pending", 0, 0)


async def test_ipn_not_available_when_fake_selected(flow, monkeypatch):
    client, driver, order = flow
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    get_settings.cache_clear()
    assert (await client.get(IPN, params=callback(order))).status_code == 503
    assert await state(driver, order) == ("pending", 0, 0)


async def test_failure_zero_transaction_id_does_not_conflict_across_orders(flow):
    client, driver, order = flow
    first = await client.get(
        IPN,
        params=callback(
            order,
            vnp_ResponseCode="24",
            vnp_TransactionStatus="02",
            vnp_TransactionNo="0",
        ),
    )
    assert first.json()["RspCode"] == "00"
    created = await client.post(
        "/api/v1/driver/wallet/topups", json={"amount_vnd": 50000}
    )
    other = created.json()["order_id"]
    second = await client.get(
        IPN,
        params=callback(
            other,
            vnp_ResponseCode="24",
            vnp_TransactionStatus="02",
            vnp_TransactionNo="0",
        ),
    )
    assert second.json()["RspCode"] == "00"
    assert await state(driver, other) == ("cancelled", 0, 0)


async def test_transaction_id_reused_for_another_order_never_credits_twice(flow):
    client, driver, order = flow
    assert (await client.get(IPN, params=callback(order))).json()["RspCode"] == "00"
    created = await client.post(
        "/api/v1/driver/wallet/topups", json={"amount_vnd": 50000}
    )
    other = created.json()["order_id"]
    transaction = dict(callback(order))["vnp_TransactionNo"]
    result = await client.get(
        IPN, params=callback(other, vnp_TransactionNo=transaction)
    )
    assert result.json()["RspCode"] == "99"
    assert await state(driver, other) == ("needs_review", 50000, 1)


async def test_commit_failure_rolls_back_and_allows_retry(flow, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession

    client, driver, order = flow

    async def failed_commit(self):
        raise SQLAlchemyError("private gateway data must not be logged")

    with monkeypatch.context() as patch:
        patch.setattr(AsyncSession, "commit", failed_commit)
        # Both the route and DB dependency commit: use direct injected session
        # with a dependency that does not add its own transaction boundary.
        from src.platform.database.session import get_db_session

        async def database():
            async with SessionFactory() as session:
                yield session

        app.dependency_overrides[get_db_session] = database
        try:
            result = await client.get(IPN, params=callback(order))
            assert result.json()["RspCode"] == "99"
        finally:
            app.dependency_overrides.pop(get_db_session)
    assert await state(driver, order) == ("pending", 0, 0)
    assert (await client.get(IPN, params=callback(order))).json()["RspCode"] == "00"
    assert await state(driver, order) == ("succeeded", 50000, 1)


async def test_callback_scope_removes_query_for_access_logging(flow):
    _, _, order = flow
    scopes = []

    async def recording_app(scope, receive, send):
        await app(scope, receive, send)
        scopes.append(scope["query_string"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=recording_app),
        base_url="https://csms.example",
    ) as client:
        assert (await client.get(RETURN, params=callback(order))).status_code == 303
        assert (await client.get(IPN, params=callback(order)[:-1])).json()[
            "RspCode"
        ] == "97"
    assert scopes == [b"", b""]
