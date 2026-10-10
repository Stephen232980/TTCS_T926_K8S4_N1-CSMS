import asyncio
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import delete, func, select

from src.config import Settings, get_settings, settings
from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, User, UserRole
from src.modules.payments.contracts import (
    GatewayEvent,
    PaymentGatewayUnavailable,
    PaymentRedirect,
    PaymentRequest,
)
from src.modules.payments.dependencies import get_payment_gateway
from src.modules.payments.fake_gateway import FakeGateway
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.topup_models import WalletTopup
from src.platform.database.session import SessionFactory

PATH = "/api/v1/driver/wallet/topups"


@pytest.mark.asyncio
async def test_t92_real_adapter_from_topup_creation_through_signed_dispatch(
    context, monkeypatch
):
    client, _, ids = context
    monkeypatch.setenv("PAYMENT_GATEWAY", "fake")
    monkeypatch.setenv("PAYMENT_WEBHOOK_SECRET", "t92-t93-integration-test-secret")
    get_settings.cache_clear()
    app.dependency_overrides[get_payment_gateway] = lambda: FakeGateway(
        base_url="http://127.0.0.1:8012", secret=get_settings().payment_webhook_secret
    )
    try:
        created = await client.post(PATH, json={"amount_vnd": 50000})
        assert created.status_code == 201
        data = created.json()
        assert data["status"] == "pending"
        payment_page = await client.get(data["redirect_url"])
        assert payment_page.status_code == 200
        query = {
            key: values[0]
            for key, values in parse_qs(urlsplit(data["redirect_url"]).query).items()
        }
        query["amount_vnd"] = int(query["amount_vnd"])
        query["expires"] = int(query["expires"])
        delivered = await client.post(
            "/api/v1/payments/fake/dispatch", json={**query, "status": "succeeded"}
        )
        assert delivered.status_code == 200
        assert delivered.json()["statuses"] == [200]
        async with SessionFactory() as db:
            topup = await db.scalar(
                select(WalletTopup).where(WalletTopup.order_id == data["order_id"])
            )
            assert topup is not None and topup.status == "pending"
            # Current T-95 receiver only verifies. Do not claim wallet-credit acceptance.
            assert (
                await db.scalar(
                    select(Wallet.balance_vnd).where(Wallet.driver_id == ids[0])
                )
                == 0
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(WalletLedger)
                    .join(Wallet)
                    .where(Wallet.driver_id == ids[0])
                )
                == 0
            )
    finally:
        get_settings.cache_clear()


class StubGateway:
    def __init__(self):
        self.requests = []
        self.error = None
        self.finish_during_call = False
        self.check_locks = True
        self.delay_seconds = 0

    async def create_payment(self, request: PaymentRequest) -> PaymentRedirect:
        self.requests.append(request)
        async with SessionFactory() as db:
            topup = await db.scalar(
                select(WalletTopup).where(WalletTopup.order_id == request.order_id)
            )
            assert topup is not None and topup.status == "pending"
            assert topup.amount_vnd == request.amount_vnd
            # Would fail if provisioning held its user lock during gateway I/O.
            if self.check_locks:
                assert (
                    await db.scalar(
                        select(User.id)
                        .where(User.id == topup.driver_id)
                        .with_for_update(nowait=True)
                    )
                    == topup.driver_id
                )
            if self.finish_during_call:
                topup.status = "succeeded"
                await db.commit()
        await asyncio.sleep(self.delay_seconds)
        if self.error is not None:
            raise self.error
        return PaymentRedirect(
            redirect_url=f"https://fake.example/pay/{request.order_id}"
        )

    def verify_webhook(
        self, raw_body: bytes, headers: Mapping[str, str]
    ) -> GatewayEvent:
        raise NotImplementedError


@pytest_asyncio.fixture
async def context():
    async with SessionFactory() as db:
        role = await db.scalar(select(Role).where(Role.code == "driver"))
        if role is None:
            role = Role(code="driver")
            db.add(role)
            await db.flush()
        users = [
            User(
                email=f"t93-{uuid4()}@example.com",
                password_hash="unused",
                status="active",
            )
            for _ in range(2)
        ]
        db.add_all(users)
        await db.flush()
        ids = [user.id for user in users]
        db.add_all([UserRole(user_id=user_id, role_id=role.id) for user_id in ids])
        await db.commit()
    gateway = StubGateway()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        ids[0], frozenset({"driver"})
    )
    app.dependency_overrides[get_payment_gateway] = lambda: gateway
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, gateway, ids
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
        app.dependency_overrides.pop(get_payment_gateway, None)
        async with SessionFactory() as db:
            await db.execute(delete(WalletTopup).where(WalletTopup.driver_id.in_(ids)))
            await db.execute(delete(Wallet).where(Wallet.driver_id.in_(ids)))
            await db.execute(delete(UserRole).where(UserRole.user_id.in_(ids)))
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()


async def counts(driver_id):
    async with SessionFactory() as db:
        orders = await db.scalar(
            select(func.count())
            .select_from(WalletTopup)
            .where(WalletTopup.driver_id == driver_id)
        )
        ledger = await db.scalar(
            select(func.count())
            .select_from(WalletLedger)
            .join(Wallet)
            .where(Wallet.driver_id == driver_id)
        )
        balance = await db.scalar(
            select(Wallet.balance_vnd).where(Wallet.driver_id == driver_id)
        )
        return orders, ledger, balance


@pytest.mark.asyncio
async def test_create_pending_order_is_committed_before_gateway_and_does_not_credit(
    context,
):
    client, gateway, ids = context
    result = await client.post(PATH, json={"amount_vnd": 100000})
    assert result.status_code == 201
    data = result.json()
    assert data["status"] == "pending" and data["amount_vnd"] == 100000
    assert data["redirect_url"].endswith(data["order_id"])
    assert gateway.requests[0].return_url == settings.payment_return_url
    polled = await client.get(PATH + "/" + data["order_id"])
    assert polled.status_code == 200
    assert polled.json()["status"] == "pending"
    assert await counts(ids[0]) == (1, 0, 0)
    assert await counts(ids[1]) == (0, 0, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount", [-1, 0, 9999, 5000001, 1.5, 100000.0, True, "100000", 2**63]
)
async def test_invalid_money_never_calls_gateway_or_creates_order(context, amount):
    client, gateway, ids = context
    result = await client.post(PATH, json={"amount_vnd": amount})
    assert result.status_code == 422
    assert gateway.requests == []
    assert await counts(ids[0]) == (0, 0, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [10000, 5000000])
async def test_inclusive_default_limits(context, amount):
    client, _, _ = context
    assert (await client.post(PATH, json={"amount_vnd": amount})).status_code == 201


@pytest.mark.asyncio
async def test_custom_server_limits(context, monkeypatch):
    client, gateway, _ = context
    monkeypatch.setattr(settings, "wallet_topup_min_vnd", 20000)
    monkeypatch.setattr(settings, "wallet_topup_max_vnd", 30000)
    assert (await client.post(PATH, json={"amount_vnd": 19999})).status_code == 422
    assert (await client.post(PATH, json={"amount_vnd": 30001})).status_code == 422
    assert (await client.post(PATH, json={"amount_vnd": 20000})).status_code == 201
    assert len(gateway.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", ["wallet_id", "driver_id"])
@pytest.mark.parametrize("location", ["body", "query"])
async def test_client_cannot_select_another_wallet(context, selector, location):
    client, gateway, ids = context
    body = {"amount_vnd": 100000}
    query = {}
    if location == "body":
        body[selector] = str(ids[1])
    else:
        query[selector] = str(ids[1])
    assert (await client.post(PATH, json=body, params=query)).status_code == 403
    assert gateway.requests == []
    assert await counts(ids[0]) == (0, 0, None)


@pytest.mark.asyncio
async def test_order_lookup_is_owned_and_does_not_expose_foreign_order(context):
    client, _, ids = context
    data = (await client.post(PATH, json={"amount_vnd": 100000})).json()
    app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
        ids[1], frozenset({"driver"})
    )
    foreign = await client.get(PATH + "/" + data["order_id"])
    unknown = await client.get(PATH + "/missing")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


@pytest.mark.asyncio
async def test_no_gateway_returns_503_without_creating_order(context):
    client, gateway, ids = context
    app.dependency_overrides.pop(get_payment_gateway)
    result = await client.post(PATH, json={"amount_vnd": 100000})
    assert result.status_code == 503
    assert gateway.requests == []
    assert await counts(ids[0]) == (0, 0, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        PaymentGatewayUnavailable("private adapter detail"),
        TimeoutError("private timeout detail"),
    ],
)
async def test_uncertain_gateway_failure_keeps_committed_order_without_credit(
    context, error
):
    client, gateway, ids = context
    gateway.error = error
    result = await client.post(PATH, json={"amount_vnd": 100000})
    assert result.status_code == 503 and "private" not in result.text
    order_id = result.json()["detail"]["order_id"]
    assert (await client.get(PATH + "/" + order_id)).json()["status"] == "pending"
    assert await counts(ids[0]) == (1, 0, 0)


@pytest.mark.asyncio
async def test_concurrent_requests_have_distinct_order_ids(context):
    client, gateway, ids = context
    # Other requests may briefly hold provisioning locks; check release separately.
    gateway.check_locks = False
    replies = await asyncio.gather(
        *[client.post(PATH, json={"amount_vnd": 100000}) for _ in range(3)]
    )
    assert all(reply.status_code == 201 for reply in replies)
    assert len({reply.json()["order_id"] for reply in replies}) == 3
    assert await counts(ids[0]) == (3, 0, 0)


@pytest.mark.asyncio
async def test_fast_result_is_not_overwritten_with_pending(context):
    client, gateway, _ = context
    gateway.finish_during_call = True
    result = await client.post(PATH, json={"amount_vnd": 100000})
    assert result.status_code == 201 and result.json()["status"] == "succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("POST", PATH), ("GET", PATH + "/unknown")])
async def test_anonymous_and_non_driver_denied(method, path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.request(
            method, path, json={"amount_vnd": 100000} if method == "POST" else None
        )
        assert result.status_code == 401
        app.dependency_overrides[get_current_actor] = lambda: CurrentActor(
            uuid4(), frozenset({"admin", "operator"})
        )
        try:
            result = await client.request(
                method, path, json={"amount_vnd": 100000} if method == "POST" else None
            )
            assert result.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_actor, None)


@pytest.mark.parametrize(
    "minimum,maximum", [(0, 1), (1, 0), (20000, 10000), (1, 2**63)]
)
def test_invalid_limit_configuration_rejected(minimum, maximum):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://unused",
            wallet_topup_min_vnd=minimum,
            wallet_topup_max_vnd=maximum,
        )


@pytest.mark.asyncio
async def test_real_timeout_cancels_gateway_and_preserves_order(context, monkeypatch):
    from src.modules.wallet import topup_router

    client, gateway, ids = context
    gateway.delay_seconds = 1
    monkeypatch.setattr(topup_router, "PAYMENT_CREATE_TIMEOUT_SECONDS", 0.05)
    result = await client.post(PATH, json={"amount_vnd": 100000})
    assert result.status_code == 503
    order_id = result.json()["detail"]["order_id"]
    assert (await client.get(PATH + "/" + order_id)).json()["status"] == "pending"
    assert await counts(ids[0]) == (1, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pending", "succeeded", "failed", "cancelled", "needs_review"]
)
async def test_polling_returns_current_status_and_reason(context, status):
    client, _, _ = context
    data = (await client.post(PATH, json={"amount_vnd": 100000})).json()
    async with SessionFactory() as db:
        topup = await db.scalar(
            select(WalletTopup).where(WalletTopup.order_id == data["order_id"])
        )
        topup.status = status
        topup.reason = "Test status reason"
        await db.commit()
    result = await client.get(PATH + "/" + data["order_id"])
    assert result.status_code == 200
    assert result.json()["status"] == status
    assert result.json()["reason"] == "Test status reason"


@pytest.mark.asyncio
async def test_client_cannot_override_return_url(context):
    client, gateway, ids = context
    result = await client.post(
        PATH, json={"amount_vnd": 100000, "return_url": "https://attacker.example/"}
    )
    assert result.status_code == 422 and gateway.requests == []
    assert await counts(ids[0]) == (0, 0, None)
