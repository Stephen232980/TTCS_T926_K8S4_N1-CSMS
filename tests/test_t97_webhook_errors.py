"""T-97 HTTP contract, durable warning grouping and safe anomaly evidence."""

import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.route_inventory import registered_routes
from src.modules.payments import webhook_router
from src.modules.wallet.topup_models import WalletTopup
from src.platform.audit.models import AuditLog
from src.platform.database.session import SessionFactory
from tests.test_t95_webhook_settlement import (
    PATH,
    SECRET,
    read,
    send,
)
from tests.test_t95_webhook_settlement import (
    context as settlement_context,
)

# Reuse the T-95 HTTP/PostgreSQL fixture to exercise the same integration path.
context = settlement_context


async def warnings_for(topup_id):
    async with SessionFactory() as db:
        return list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.object_type == "wallet_topup",
                    AuditLog.object_id == str(topup_id),
                    AuditLog.action.like("payment_webhook.%"),
                )
            )
        )


async def seed(context, state, tx):
    client, ids = context
    if state == "succeeded":
        assert (await send(client, ids[3], tx=tx)).status_code == 200
    elif state != "pending":
        async with SessionFactory() as db, db.begin():
            topup = await db.get(WalletTopup, ids[2])
            topup.status = state
            topup.gateway_transaction_id = tx
            topup.reason = "Existing review evidence"
    return client, ids


def test_only_one_payment_webhook_and_documented_http_contract():
    routes = [
        route
        for route, path in registered_routes(app.routes)
        if isinstance(route, APIRoute) and path == PATH and "POST" in route.methods
    ]
    assert len(routes) == 1
    assert routes[0].endpoint is webhook_router.receive_payment_webhook
    responses = app.openapi()["paths"][PATH]["post"]["responses"]
    assert {"200", "400", "401", "404", "503"} <= responses.keys()


@pytest.mark.parametrize(
    "old,event,final,code",
    [
        ("pending", "succeeded", "succeeded", None),
        ("pending", "failed", "failed", None),
        ("pending", "cancelled", "cancelled", None),
        ("succeeded", "succeeded", "succeeded", None),
        ("succeeded", "failed", "succeeded", "late_non_success"),
        ("succeeded", "cancelled", "succeeded", "late_non_success"),
        ("failed", "succeeded", "needs_review", "late_success"),
        ("failed", "failed", "failed", None),
        ("failed", "cancelled", "failed", None),
        ("cancelled", "succeeded", "needs_review", "late_success"),
        ("cancelled", "failed", "cancelled", None),
        ("cancelled", "cancelled", "cancelled", None),
        ("needs_review", "succeeded", "needs_review", "review_callback"),
        ("needs_review", "failed", "needs_review", "review_callback"),
        ("needs_review", "cancelled", "needs_review", "review_callback"),
    ],
)
async def test_all_fifteen_transitions_and_warning_contract(
    context, caplog, old, event, final, code
):
    tx = str(uuid4())
    client, ids = await seed(context, old, tx)
    response = await send(client, ids[3], status=event, tx=tx)
    assert response.status_code == 200
    assert response.json() == {"status": final, "received": True}
    topup, wallet, count = await read(ids)
    assert topup.status == final
    credited = old == "succeeded" or (old == "pending" and event == "succeeded")
    assert wallet.balance_vnd == (50000 if credited else 0)
    assert count == int(credited)
    warnings = await warnings_for(ids[2])
    assert len(warnings) == int(code is not None)
    if code:
        assert warnings[0].action == f"payment_webhook.{code}"
        assert f"code={code}" in caplog.text
    if old == "needs_review":
        assert topup.reason == "Existing review evidence"


@pytest.mark.parametrize(
    "state", ["pending", "succeeded", "failed", "cancelled", "needs_review"]
)
async def test_authentication_and_amount_precede_every_state(context, state, caplog):
    tx = str(uuid4())
    client, ids = await seed(context, state, tx)
    for headers in [{}, {"X-Payment-Signature": "sha256=" + "0" * 64}]:
        response = await client.post(
            PATH, content=b"PRIVATE_RAW_PAYLOAD", headers=headers
        )
        assert response.status_code == 401
    topup, wallet, count = await read(ids)
    assert topup.status == state
    assert wallet.balance_vnd == (50000 if state == "succeeded" else 0)
    assert count == int(state == "succeeded")
    assert await warnings_for(ids[2]) == []
    assert "client_ip" in caplog.text
    assert "PRIVATE_RAW_PAYLOAD" not in caplog.text and SECRET not in caplog.text
    for _ in range(5):
        response = await send(client, ids[3], amount=49999, tx=tx)
        assert response.status_code == 400
        assert response.json()["received"] is False
    topup, wallet, count = await read(ids)
    assert topup.status == ("succeeded" if state == "succeeded" else "needs_review")
    assert wallet.balance_vnd == (50000 if state == "succeeded" else 0)
    assert count == int(state == "succeeded")
    warnings = await warnings_for(ids[2])
    assert len(warnings) == 1
    assert warnings[0].action == "payment_webhook.amount_mismatch"
    assert caplog.text.count("code=amount_mismatch") == 1


@pytest.mark.parametrize(
    "state,event,code",
    [
        ("succeeded", "failed", "late_non_success"),
        ("succeeded", "cancelled", "late_non_success"),
        ("failed", "succeeded", "late_success"),
        ("cancelled", "succeeded", "late_success"),
        ("needs_review", "succeeded", "review_callback"),
        ("needs_review", "failed", "review_callback"),
        ("needs_review", "cancelled", "review_callback"),
    ],
)
async def test_concurrent_retries_group_warnings_across_sessions(
    context, caplog, state, event, code
):
    tx = str(uuid4())
    client, ids = await seed(context, state, tx)
    responses = await asyncio.gather(
        *(send(client, ids[3], status=event, tx=tx) for _ in range(5))
    )
    assert all(response.status_code == 200 for response in responses)
    rows = await warnings_for(ids[2])
    codes = [row.action for row in rows]
    assert codes.count(f"payment_webhook.{code}") == 1
    assert caplog.text.count(f"code={code}") == 1
    assert len(rows) == 1
    topup, wallet, count = await read(ids)
    assert topup.status == ("succeeded" if state == "succeeded" else "needs_review")
    assert wallet.balance_vnd == (50000 if state == "succeeded" else 0)
    assert count == int(state == "succeeded")


async def test_unknown_order_retries_are_grouped_without_external_data(context, caplog):
    client, ids = context
    order = f"PRIVATE_ORDER_{uuid4()}"
    tx = f"PRIVATE_TRANSACTION_{uuid4()}"
    body = json.dumps(
        {
            "order_id": order,
            "gateway_transaction_id": tx,
            "amount_vnd": 50000,
            "status": "succeeded",
            "reason": "PRIVATE_GATEWAY_REASON",
        }
    ).encode()
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    responses = await asyncio.gather(
        *(
            client.post(PATH, content=body, headers={"X-Payment-Signature": signature})
            for _ in range(5)
        )
    )
    assert all(response.status_code == 404 for response in responses)
    async with SessionFactory() as db:
        rows = list(
            await db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "payment_webhook.unknown_order"
                )
            )
        )
    rows = [
        row
        for row in rows
        if row.object_id == hashlib.sha256(order.encode()).hexdigest()
    ]
    assert len(rows) == 1
    assert caplog.text.count("code=unknown_order") == 1
    evidence = caplog.text + str(rows[0].data)
    for private in (
        order,
        tx,
        "PRIVATE_GATEWAY_REASON",
        SECRET,
        signature,
        body.decode(),
    ):
        assert private not in evidence
    topup, wallet, count = await read(ids)
    assert topup.status == "pending" and wallet.balance_vnd == 0 and count == 0


async def test_distinct_anomalies_keep_safe_evidence_and_preserve_success(
    context, caplog
):
    tx = str(uuid4())
    client, ids = await seed(context, "succeeded", tx)
    for _ in range(5):
        assert (await send(client, ids[3], amount=1, tx=tx)).status_code == 400
        assert (
            await send(client, ids[3], tx=tx, status="failed", reason="PRIVATE_REASON")
        ).status_code == 200
        assert (
            await send(client, ids[3], tx="PRIVATE_OTHER_TRANSACTION")
        ).status_code == 200
    rows = await warnings_for(ids[2])
    assert {row.action for row in rows} == {
        "payment_webhook.amount_mismatch",
        "payment_webhook.late_non_success",
        "payment_webhook.gateway_conflict",
    }
    assert len(rows) == 3
    evidence = caplog.text + str([row.data for row in rows])
    for private in ("PRIVATE_REASON", "PRIVATE_OTHER_TRANSACTION", SECRET, ids[3]):
        assert private not in evidence
    topup, wallet, count = await read(ids)
    assert topup.status == "succeeded" and topup.reason is None
    assert wallet.balance_vnd == 50000 and count == 1


async def test_warning_marker_rolls_back_and_retry_can_emit_after_commit(
    context, caplog, monkeypatch
):
    client, ids = context
    actual = webhook_router.process_topup_webhook

    async def fail_before_commit(session, event):
        await actual(session, event)
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(webhook_router, "process_topup_webhook", fail_before_commit)
    with pytest.raises(RuntimeError, match="simulated failure"):
        await send(client, ids[3], amount=1)
    assert await warnings_for(ids[2]) == []
    assert "code=amount_mismatch" not in caplog.text
    topup, wallet, count = await read(ids)
    assert topup.status == "pending" and wallet.balance_vnd == 0 and count == 0
    monkeypatch.setattr(webhook_router, "process_topup_webhook", actual)
    assert (await send(client, ids[3], amount=1)).status_code == 400
    assert len(await warnings_for(ids[2])) == 1
    assert caplog.text.count("code=amount_mismatch") == 1
