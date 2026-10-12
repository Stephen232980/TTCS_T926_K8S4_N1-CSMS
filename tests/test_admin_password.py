import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.entrypoints.http import app
from src.modules.identity.models import Role, Session, User, UserRole
from src.modules.identity.security import (
    hash_password,
    hash_session_token,
    verify_password,
)
from src.platform.audit.models import AuditLog
from src.platform.database.session import SessionFactory

OLD = "Old-test-only-2026!"
NEW = "New-test-only-2026!"


@pytest_asyncio.fixture
async def reset_accounts():
    result = {}
    async with SessionFactory() as db, db.begin():
        roles = dict((await db.execute(select(Role.code, Role.id))).all())
        for name, role in [
            ("admin", "admin"),
            ("target", "driver"),
            ("other", "operator"),
        ]:
            user = User(
                email=uuid4().hex + "@example.com",
                password_hash=hash_password(OLD),
                status="active",
            )
            db.add(user)
            await db.flush()
            db.add(UserRole(user_id=user.id, role_id=roles[role]))
            token = uuid4().hex
            db.add(
                Session(
                    user_id=user.id,
                    token_hash=hash_session_token(token),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            result[name] = user.id
            result[name + "_token"] = token
            result[name + "_email"] = user.email
            result[name + "_updated"] = user.updated_at.isoformat()
    # This test DB is disposable. Retain audit-linked users instead of deleting immutable evidence.
    return result


def client(data, role="admin"):
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        cookies={"session": data[role + "_token"]},
    )


def body(data, role="target"):
    return {
        "password": NEW,
        "confirm_password": NEW,
        "expected_updated_at": data[role + "_updated"],
    }


@pytest.mark.asyncio
async def test_admin_reset_revokes_sessions_preserves_roles_and_audits(reset_accounts):
    d = reset_accounts
    async with client(d) as c:
        r = await c.post(f"/api/v1/admin/accounts/{d['target']}/password", json=body(d))
        assert r.status_code == 200, r.text
        assert (
            r.headers["cache-control"] == "no-store"
            and OLD not in r.text
            and NEW not in r.text
        )
        assert r.json()["status"] == "active" and r.json()["roles"] == ["driver"]
        journal = await c.get(
            "/api/v1/admin/account-audit?action=account_password_reset"
        )
        assert journal.status_code == 200
        assert any(
            row["target_id"] == str(d["target"]) for row in journal.json()["items"]
        )
    async with client(d, "target") as c:
        assert (await c.get("/api/v1/auth/me")).status_code == 401
    async with SessionFactory() as db:
        u = await db.get(User, d["target"])
        assert verify_password(u.password_hash, NEW) and not verify_password(
            u.password_hash, OLD
        )
        sessions = list(
            await db.scalars(select(Session).where(Session.user_id == d["target"]))
        )
        assert sessions and all(s.revoked_at for s in sessions)
        a = await db.scalar(
            select(AuditLog).where(
                AuditLog.object_id == str(d["target"]),
                AuditLog.action == "account.credentials_reset",
            )
        )
        assert a and a.actor_id == d["admin"] and a.data["revoked_sessions"] == 1
        assert NEW not in json.dumps(a.data) and u.password_hash not in json.dumps(
            a.data
        )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (
            await c.post(
                "/api/v1/auth/login", json={"email": d["target_email"], "password": OLD}
            )
        ).status_code == 401
        assert (
            await c.post(
                "/api/v1/auth/login", json={"email": d["target_email"], "password": NEW}
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_reset_denies_non_admin_stale_and_invalid_data(reset_accounts):
    d = reset_accounts
    path = f"/api/v1/admin/accounts/{d['target']}/password"
    async with client(d, "other") as c:
        assert (await c.post(path, json=body(d))).status_code == 403
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.post(path, json=body(d))).status_code == 401
    async with client(d) as c:
        for bad in [
            {**body(d), "password": "Z8q!v", "confirm_password": "Z8q!v"},
            {**body(d), "confirm_password": OLD},
            {
                **body(d),
                "password": NEW + "x" * 1024,
                "confirm_password": NEW + "x" * 1024,
            },
        ]:
            r = await c.post(path, json=bad)
            assert r.status_code == 422 and bad["password"] not in r.text
        assert (
            await c.post(
                path, json={**body(d), "expected_updated_at": "2000-01-01T00:00:00Z"}
            )
        ).status_code == 409
        assert (
            await c.post(f"/api/v1/admin/accounts/{uuid4()}/password", json=body(d))
        ).status_code == 404
    async with SessionFactory() as db:
        u = await db.get(User, d["target"])
        assert verify_password(u.password_hash, OLD)
        assert not await db.scalar(
            select(AuditLog.id).where(AuditLog.object_id == str(d["target"]))
        )


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_reset_and_revocations(
    reset_accounts, monkeypatch
):
    d = reset_accounts

    async def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr("src.modules.identity.admin_service.ghi_nhat_ky", fail)
    async with client(d) as c:
        assert (
            await c.post(f"/api/v1/admin/accounts/{d['target']}/password", json=body(d))
        ).status_code == 500
    async with SessionFactory() as db:
        u = await db.get(User, d["target"])
        assert verify_password(u.password_hash, OLD)
        s = await db.scalar(select(Session).where(Session.user_id == d["target"]))
        assert s.revoked_at is None


@pytest.mark.asyncio
async def test_self_reset_revokes_current_admin_session(reset_accounts):
    d = reset_accounts
    async with client(d) as c:
        assert (
            await c.post(
                f"/api/v1/admin/accounts/{d['admin']}/password", json=body(d, "admin")
            )
        ).status_code == 200
        assert (await c.get("/api/v1/admin/accounts")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_status,expected",
    [
        ("suspended", 200),
        ("deactivated", 409),
        ("pending_deletion", 409),
        ("anonymized", 409),
    ],
)
async def test_reset_preserves_status_and_rejects_closed_accounts(
    reset_accounts, target_status, expected
):
    d = reset_accounts
    async with SessionFactory() as db:
        u = await db.get(User, d["target"])
        u.status = target_status
        await db.commit()
        await db.refresh(u)
        d["target_updated"] = u.updated_at.isoformat()
    async with client(d) as c:
        r = await c.post(f"/api/v1/admin/accounts/{d['target']}/password", json=body(d))
        assert r.status_code == expected
        if expected == 200:
            assert r.json()["status"] == target_status
    async with SessionFactory() as db:
        u = await db.get(User, d["target"])
        assert u.status == target_status
        assert verify_password(u.password_hash, NEW if expected == 200 else OLD)
