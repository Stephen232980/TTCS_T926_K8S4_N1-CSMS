from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from src.entrypoints.http import app
from src.modules.identity.authorization import AuthorizationEvidence, CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.wallet.administration import dieu_chinh_vi, mo_khoa_vi
from src.modules.wallet.manual_topup import ManualTopupRequest, nap_tay
from src.modules.wallet.models import Wallet
from src.modules.wallet.service import ghi_so_cai
from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky
from tests.test_manual_topup import api_db, isolated_wallet_db  # noqa: F401
from tests.test_wallet_service import setup_wallet


async def fetch(actor, params=None):
    if actor:
        app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/api/v1/admin/wallet-audit", params=params)
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_projection_filters_legacy_and_replay(api_db):  # noqa: F811
    factory, actor, driver_id, wallet_id = api_db
    request_id = uuid4()
    async with factory() as db:
        request = ManualTopupRequest(
            amount_vnd=100,
            request_id=request_id,
            payment_received=True,
            reason="Cash receipt",
        )
        first = await nap_tay(
            db,
            driver_id=driver_id,
            actor_id=actor.user_id,
            request=request,
            authorization=AuthorizationEvidence(
                "admin.wallet.manual_topup", ("admin",)
            ),
        )
        await db.commit()
        replay = await nap_tay(
            db,
            driver_id=driver_id,
            actor_id=actor.user_id,
            request=request,
            authorization=AuthorizationEvidence(
                "admin.wallet.manual_topup", ("admin",)
            ),
        )
        assert replay.ledger_id == first.ledger_id
        _, other = await setup_wallet(db)
        await ghi_nhat_ky(
            db,
            actor_id=actor.user_id,
            action="wallet.unlocked",
            object_type="wallet",
            object_id=str(other.id),
        )
        await ghi_nhat_ky(
            db,
            actor_id=actor.user_id,
            action="wallet.unlocked",
            object_type="wallet",
            object_id=str(wallet_id),
        )
        await db.commit()
    response = await fetch(actor, {"driver_id": str(driver_id)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2 and body["page_size"] == 50
    assert all(row["wallet_id"] == str(wallet_id) for row in body["items"])
    legacy = next(row for row in body["items"] if row["legacy"])
    assert legacy["reason"] is None and legacy["before_balance_vnd"] is None
    row = next(row for row in body["items"] if not row["legacy"])
    assert (
        row["amount_vnd"] == 100
        and row["before_balance_vnd"] == 0
        and row["after_balance_vnd"] == 100
    )
    assert row["reason"] == "Cash receipt" and row["ledger_id"] == first.ledger_id
    assert row["reference_id"] == "PT-AUTO-" + request_id.hex
    assert (
        await fetch(
            actor, {"wallet_id": str(wallet_id), "action": "wallet.manual_topup"}
        )
    ).json()["total"] == 1
    assert (
        await fetch(actor, {"wallet_id": str(wallet_id), "driver_id": str(uuid4())})
    ).json()["total"] == 0
    assert (
        await fetch(
            actor, {"from_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
        )
    ).json()["total"] == 0
    page1 = (await fetch(actor, {"page_size": 1, "page": 1})).json()
    page2 = (await fetch(actor, {"page_size": 1, "page": 2})).json()
    assert (
        page1["items"][0]["id"] != page2["items"][0]["id"] and page1["total_pages"] == 3
    )


@pytest.mark.parametrize(
    "role", [None, "driver", "operator", "station_owner", "accountant"]
)
async def test_no_network_audit_access_for_nonadmins(role):
    response = await fetch(CurrentActor(uuid4(), frozenset([role])) if role else None)
    assert response.status_code == (403 if role else 401)


async def test_query_validation_and_unlock_reason(api_db):  # noqa: F811
    _, actor, driver_id, wallet_id = api_db
    for params in [
        {"page": 0},
        {"page_size": 51},
        {"driver_id": "bad"},
        {"action": "unknown"},
        {"from_at": "2026-10-17T12:00:00Z", "to_at": "2026-10-16T12:00:00Z"},
    ]:
        assert (await fetch(actor, params)).status_code == 422
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for body in [
                None,
                {},
                {"reason": ""},
                {"reason": " "},
                {"reason": "x" * 501},
            ]:
                response = await client.post(
                    f"/api/v1/admin/wallets/{wallet_id}/unlock", json=body
                )
                assert response.status_code == 422
            response = await client.post(
                f"/api/v1/admin/drivers/{uuid4()}/wallet/manual-topups",
                json={"amount_vnd": 10, "receipt_code": "missing-reason"},
            )
            # Unknown wallet remains 404 without leaking other wallet data.
            assert response.status_code == 404
            response = await client.post(
                f"/api/v1/admin/drivers/{driver_id}/wallet/manual-topups",
                json={"amount_vnd": 10, "receipt_code": "missing-reason"},
            )
            assert response.status_code == 422
            for route in [
                f"/api/v1/admin/wallets/{wallet_id}/unlock",
                f"/api/v1/admin/drivers/{driver_id}/wallet/manual-topups",
            ]:
                response = await client.post(
                    route, json={"password": "Do-not-echo-me", "reason": "Checked"}
                )
                assert (
                    response.status_code == 422
                    and "Do-not-echo-me" not in response.text
                )
    finally:
        app.dependency_overrides.pop(get_current_actor, None)


async def test_adjustment_unlock_projection_and_no_duplicate_audit(api_db):  # noqa: F811
    factory, actor, driver_id, wallet_id = api_db
    async with factory() as db:
        (await db.get(Wallet, wallet_id)).status = "locked"
        await db.commit()
        audit_id = uuid4()
        for _ in range(2):
            await dieu_chinh_vi(
                db,
                wallet_id=wallet_id,
                actor_id=actor.user_id,
                amount_vnd=50,
                reason="Correction",
                audit_id=audit_id,
            )
        for _ in range(2):
            await mo_khoa_vi(
                db,
                wallet_id=wallet_id,
                actor_id=actor.user_id,
                reason="Ledger verified",
            )
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 2
    entries = (await fetch(actor, {"driver_id": str(driver_id)})).json()["items"]
    adjustment = next(e for e in entries if e["action"] == "wallet.adjusted")
    assert adjustment["reason"] == "Correction" and adjustment["reference_id"] == str(
        audit_id
    )
    unlock = next(e for e in entries if e["action"] == "wallet.unlocked")
    assert (
        unlock["reason"] == "Ledger verified"
        and unlock["before_balance_vnd"] == unlock["after_balance_vnd"] == 50
    )
    assert unlock["amount_vnd"] is None


async def test_audit_tables_reject_mutations(isolated_wallet_db):  # noqa: F811
    async with isolated_wallet_db() as db:
        for table in ["audit_logs", "wallet_audits"]:
            for operation in [
                f"UPDATE {table} SET action='x'",
                f"DELETE FROM {table}",
                f"TRUNCATE {table}",
            ]:
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(text(operation))


async def test_legacy_pending_topup_replays_without_reason_or_new_money(api_db):  # noqa: F811
    factory, actor, driver_id, wallet_id = api_db
    key = uuid4()
    evidence = AuthorizationEvidence("admin.wallet.manual_topup", ("admin",))
    async with factory() as db:
        entry = await ghi_so_cai(
            db,
            wallet_id=wallet_id,
            actor_id=actor.user_id,
            amount_vnd=100,
            entry_type="manual_topup",
            reference_type="manual_topup",
            reference_id="PT-AUTO-" + key.hex,
        )
        await ghi_nhat_ky(
            db,
            actor_id=actor.user_id,
            action="wallet.manual_topup",
            object_type="wallet",
            object_id=str(wallet_id),
            data={
                "ledger_id": entry.id,
                "request_id": str(key),
                "payment_received": True,
                "external_reference": None,
            },
        )
        await db.commit()
        replay = await nap_tay(
            db,
            driver_id=driver_id,
            actor_id=actor.user_id,
            request=ManualTopupRequest(
                amount_vnd=100, request_id=key, payment_received=True
            ),
            authorization=evidence,
        )
        assert replay.ledger_id == entry.id
        assert (await db.get(Wallet, wallet_id)).balance_vnd == 100
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 1
