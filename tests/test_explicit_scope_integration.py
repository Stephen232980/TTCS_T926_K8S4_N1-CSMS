from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.authorization import CurrentActor
from src.modules.identity.dependencies import get_current_actor
from src.modules.identity.models import Role, Session, User, UserRole
from src.modules.identity.role_assignment import assign_user_roles
from src.modules.identity.security import hash_session_token
from src.platform.database.session import get_db_session
from tests.test_charging_sessions import setup, start


@pytest.mark.parametrize("extra", ["admin", "operator", "accountant", "driver"])
async def test_combined_owner_roles_cannot_escape_ownership_through_read_or_write(
    db_session, extra
):
    own, own_charger, _, _, card, conn, tag = await setup(db_session)
    (
        other,
        other_charger,
        _other_connector,
        _,
        other_card,
        other_conn,
        other_tag,
    ) = await setup(db_session)
    own_tx = (await start(db_session, conn, tag, datetime.now(UTC))).payload[
        "transactionId"
    ]
    other_tx = (
        await start(db_session, other_conn, other_tag, datetime.now(UTC))
    ).payload["transactionId"]
    actor = CurrentActor(own.owner_id, frozenset({"station_owner", extra}))

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[get_current_actor] = lambda: actor
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for prefix in ("/api/v1", "/api/v1/owner"):
                # Client-provided scope is ignored; it cannot broaden authorization.
                injected = await client.get(
                    f"{prefix}/stations", params={"scope": "all"}
                )
                assert injected.status_code == 422
                stations = await client.get(f"{prefix}/stations")
                assert stations.status_code == 200
                assert {r["id"] for r in stations.json()["items"]} == {str(own.id)}
                assert (
                    await client.get(f"{prefix}/stations/{other.id}")
                ).status_code == 403
                assert (
                    await client.patch(
                        f"{prefix}/stations/{other.id}", json={"name": "forbidden"}
                    )
                ).status_code == 403
                assert (
                    await client.get(f"{prefix}/stations/{other.id}/photo")
                ).status_code == 403
                assert (
                    await client.delete(f"{prefix}/stations/{other.id}/photo")
                ).status_code == 403
                assert (
                    await client.patch(
                        f"{prefix}/charge-points/{other_charger.id}",
                        json={"name": "forbidden"},
                    )
                ).status_code == 403
                sessions = await client.get(f"{prefix}/charging/sessions")
                assert {r["id"] for r in sessions.json()["items"]} == {own_tx}
                assert (
                    await client.get(f"{prefix}/charging/sessions/{other_tx}/samples")
                ).status_code == 404
                assert (
                    await client.get(f"{prefix}/charging/sessions/{other_tx}/events")
                ).status_code == 404
                cards = await client.get(f"{prefix}/charging/cards")
                assert {r["id"] for r in cards.json()} == {str(card.id)}
                assert (
                    await client.patch(
                        f"{prefix}/charging/cards/{other_card.id}",
                        json={"status": "blocked"},
                    )
                ).status_code == 404
                monitor = await client.get(f"{prefix}/ocpp/connections")
                assert {r["id"] for r in monitor.json()["items"]} == {
                    str(own_charger.id)
                }
            if extra in {"admin", "operator"}:
                area = "ops" if extra == "operator" else "admin"
                global_stations = await client.get(f"/api/v1/{area}/stations")
                assert {r["id"] for r in global_stations.json()["items"]} == {
                    str(own.id),
                    str(other.id),
                }
                global_monitor = await client.get(f"/api/v1/{area}/ocpp/connections")
                assert len(global_monitor.json()["items"]) == 2
                assert (
                    await client.get(
                        f"/api/v1/{area}/charging/sessions/{other_tx}/samples"
                    )
                ).status_code == 200
            if extra == "accountant":
                global_sessions = await client.get(
                    "/api/v1/accounting/charging/sessions"
                )
                assert {r["id"] for r in global_sessions.json()["items"]} == {
                    own_tx,
                    other_tx,
                }
            if extra == "admin":
                assert (
                    await client.post(
                        f"/api/v1/ocpp/charge-points/{other_charger.id}/reset",
                        json={"request_id": str(uuid4())},
                    )
                ).status_code == 403
                assert (
                    await client.post(
                        f"/api/v1/charging/sessions/{other_tx}/close",
                        json={"reason": "must deny"},
                    )
                ).status_code == 403
    finally:
        app.dependency_overrides.clear()
    await db_session.refresh(other)
    await db_session.refresh(other_card)
    assert other.name != "forbidden" and other_card.status == "active"


async def test_same_session_observes_role_addition_and_removal_next_request(db_session):
    user = User(email=f"scope-session-{uuid4()}@example.com", password_hash="unused")
    db_session.add(user)
    await db_session.flush()
    await assign_user_roles(db_session, user.id, ["driver"])
    token = str(uuid4())
    db_session.add(
        Session(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db_session.flush()

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"session": token},
        ) as client:
            assert (await client.get("/api/v1/admin/accounts")).status_code == 403
            await assign_user_roles(db_session, user.id, ["admin"], replace=False)
            assert (await client.get("/api/v1/admin/accounts")).status_code == 200
            assert (await client.get("/api/v1/owner/stations")).status_code == 403
            await assign_user_roles(db_session, user.id, ["driver"])
            assert (await client.get("/api/v1/admin/accounts")).status_code == 403
            assert (await client.get("/api/v1/auth/me")).json()["roles"] == ["driver"]
    finally:
        app.dependency_overrides.clear()


async def test_seed_style_role_addition_validates_existing_roles(
    db_session, monkeypatch
):
    from src.modules.identity import role_assignment

    user = User(email=f"role-pair-{uuid4()}@example.com", password_hash="unused")
    db_session.add(user)
    await db_session.flush()
    await assign_user_roles(db_session, user.id, ["accountant"])
    monkeypatch.setattr(
        role_assignment,
        "FORBIDDEN_ROLE_PAIRS",
        frozenset({frozenset({"admin", "accountant"})}),
    )
    with pytest.raises(HTTPException) as error:
        await assign_user_roles(db_session, user.id, ["admin"], replace=False)
    assert error.value.status_code == 422
    codes = set(
        await db_session.scalars(
            select(Role.code).join(UserRole).where(UserRole.user_id == user.id)
        )
    )
    assert codes == {"accountant"}
