import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.audit.models import AuditLog
from src.platform.database.session import get_db_session
from tests.test_wallet_service import isolated_wallet_db, setup_wallet  # noqa: F401

PATH = "/api/v1/admin/drivers/{}/wallet/manual-topups"


@pytest.fixture
def request_api():
    async def request(driver_id, body, actor=None):
        if actor:
            app.dependency_overrides[get_current_actor] = lambda: actor
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.post(PATH.format(driver_id), json=body)
        finally:
            app.dependency_overrides.pop(get_current_actor, None)

    return request


@pytest.fixture
async def api_db(isolated_wallet_db):  # noqa: F811
    factory = isolated_wallet_db

    async def database():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = database
    try:
        async with factory() as session:
            admin, _ = await setup_wallet(session, admin=True)
            driver, wallet = await setup_wallet(session)
            await session.commit()
        yield (
            factory,
            CurrentActor(admin.id, frozenset({"admin"})),
            driver.id,
            wallet.id,
        )
    finally:
        app.dependency_overrides.pop(get_db_session, None)


def payload(**overrides):
    return {"amount_vnd": 500_000, "receipt_code": "PT-001"} | overrides


@pytest.mark.parametrize(
    "roles", [None, {"accountant"}, {"operator"}, {"driver"}, {"station_owner"}]
)
async def test_only_admin_can_topup(request_api, roles):
    actor = CurrentActor(uuid4(), frozenset(roles)) if roles else None
    response = await request_api(uuid4(), payload(), actor)
    assert response.status_code == (403 if roles else 401)


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_vnd", -1),
        ("amount_vnd", 0),
        ("amount_vnd", 1.5),
        ("amount_vnd", True),
        ("amount_vnd", "500000"),
        ("amount_vnd", 2**63),
        ("receipt_code", " "),
        ("receipt_code", 123),
        ("receipt_code", "x" * 129),
        ("actor_id", str(uuid4())),
    ],
)
async def test_invalid_input_has_field_error(request_api, field, value):
    response = await request_api(
        uuid4(), payload(**{field: value}), CurrentActor(uuid4(), frozenset({"admin"}))
    )
    assert response.status_code == 422
    assert any(error["loc"] == ["body", field] for error in response.json()["detail"])


async def counts(factory):
    async with factory() as session:
        return (
            await session.scalar(select(func.count()).select_from(WalletLedger)),
            await session.scalar(select(func.count()).select_from(AuditLog)),
        )


async def test_credit_receipt_replay_and_audit(api_db, request_api):
    factory, actor, driver_id, wallet_id = api_db
    response = await request_api(driver_id, payload(receipt_code=" PT-001 "), actor)
    assert response.status_code == 201, response.text
    assert response.json()["balance_after_vnd"] == 500_000
    for body in [payload(), payload(amount_vnd=600_000)]:
        replay = await request_api(driver_id, body, actor)
        assert (
            replay.status_code == 409
            and replay.json()["detail"] == "receipt_already_used"
        )
    assert await counts(factory) == (1, 1)
    async with factory() as session:
        assert (await session.get(Wallet, wallet_id)).balance_vnd == 500_000
        audit = await session.scalar(select(AuditLog))
        assert audit.actor_id == actor.user_id
        assert audit.action == "wallet.manual_topup"
        assert audit.object_type == "wallet" and audit.object_id == str(wallet_id)
        assert (
            audit.permission == "admin.wallet.manual_topup"
            and audit.actor_roles == ["admin"]
        )
        assert audit.data == {
            "ledger_id": response.json()["ledger_id"],
            "amount_vnd": 500_000,
            "receipt_code": "PT-001",
        }
        entry = await session.get(WalletLedger, audit.data["ledger_id"])
        assert entry.actor_id == actor.user_id and entry.reference_id == "PT-001"
        assert entry.entry_type == "manual_topup"


@pytest.mark.parametrize("different_wallet", [False, True])
async def test_same_receipt_concurrent_requests_only_one_success(
    api_db, different_wallet
):
    factory, actor, driver_id, _wallet_id = api_db
    other_id = driver_id
    if different_wallet:
        async with factory() as session:
            other, _ = await setup_wallet(session)
            other_id = other.id
            await session.commit()
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = await asyncio.wait_for(
                asyncio.gather(
                    client.post(PATH.format(driver_id), json=payload()),
                    client.post(PATH.format(other_id), json=payload()),
                ),
                timeout=15,
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await counts(factory) == (1, 1)
    async with factory() as session:
        assert await session.scalar(select(func.sum(Wallet.balance_vnd))) == 500_000


async def test_different_receipts_same_wallet_no_lost_credit(api_db):
    factory, actor, driver_id, wallet_id = api_db
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = await asyncio.gather(
                *[
                    client.post(
                        PATH.format(driver_id), json=payload(receipt_code=receipt)
                    )
                    for receipt in ["PT-001", "PT-002"]
                ]
            )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)
    assert all(response.status_code == 201 for response in responses)
    assert await counts(factory) == (2, 2)
    async with factory() as session:
        assert (await session.get(Wallet, wallet_id)).balance_vnd == 1_000_000


async def test_configured_limit_and_missing_wallet(api_db, request_api, monkeypatch):
    from src.config import settings

    factory, actor, driver_id, _ = api_db
    monkeypatch.setattr(settings, "wallet_manual_topup_max_vnd", 600_000)
    assert (
        await request_api(driver_id, payload(amount_vnd=600_001), actor)
    ).status_code == 422
    assert (await request_api(uuid4(), payload(), actor)).status_code == 404
    assert await counts(factory) == (0, 0)
    assert (
        await request_api(driver_id, payload(amount_vnd=600_000), actor)
    ).status_code == 201


async def test_locked_wallet_and_inactive_admin_rejected(api_db, request_api):
    from src.modules.identity.models import User

    factory, actor, driver_id, wallet_id = api_db
    async with factory() as session:
        (await session.get(Wallet, wallet_id)).status = "locked"
        await session.commit()
    assert (await request_api(driver_id, payload(), actor)).status_code == 409
    async with factory() as session:
        (await session.get(User, actor.user_id)).status = "deactivated"
        await session.commit()
    assert (await request_api(driver_id, payload(), actor)).status_code == 403
    assert await counts(factory) == (0, 0)


async def test_audit_failure_rolls_back_credit(api_db, request_api, monkeypatch):
    import src.modules.wallet.manual_topup as service

    factory, actor, driver_id, wallet_id = api_db

    original = service.ghi_nhat_ky

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(service, "ghi_nhat_ky", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await request_api(driver_id, payload(), actor)
    assert await counts(factory) == (0, 0)
    async with factory() as session:
        assert (await session.get(Wallet, wallet_id)).balance_vnd == 0


async def test_ledger_failure_leaves_no_audit_or_credit(
    api_db, request_api, monkeypatch
):
    import src.modules.wallet.manual_topup as service
    from src.modules.wallet.exceptions import WalletAmountError

    factory, actor, driver_id, wallet_id = api_db
    original = service.ghi_so_cai

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        raise WalletAmountError("ledger operation failed")

    monkeypatch.setattr(service, "ghi_so_cai", fail)
    response = await request_api(driver_id, payload(), actor)
    assert response.status_code == 422
    assert await counts(factory) == (0, 0)
    async with factory() as session:
        assert (await session.get(Wallet, wallet_id)).balance_vnd == 0


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_logs SET action='changed'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ],
)
async def test_audit_cannot_be_changed(api_db, request_api, sql):
    factory, actor, driver_id, _ = api_db
    assert (await request_api(driver_id, payload(), actor)).status_code == 201
    async with factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            async with session.begin_nested():
                await session.execute(text(sql))


def test_openapi_and_policy_contract():
    from src.modules.identity.authorization import get_access_policy
    from src.modules.wallet.admin_router import manual_topup

    policy = get_access_policy(manual_topup)
    assert policy.permission == "admin.wallet.manual_topup" and policy.scope == "all"
    assert policy.roles == frozenset({"admin"})
    route = app.openapi()["paths"][PATH.format("{driver_id}")]["post"]
    assert {"201", "401", "403", "404", "409", "422"} <= route["responses"].keys()
