import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.entrypoints.http import app
from src.modules.identity.models import (
    AccountAudit,
    LoginIpAttempt,
    Role,
    Session,
    User,
    UserRole,
)
from src.modules.identity.security import (
    hash_password,
    hash_session_token,
    verify_password,
)

PASSWORD = "Admin-api-test-2026"
BASE = "/api/v1/admin/accounts"


@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession) -> AsyncIterator[dict[str, str]]:
    prefix = f"admin-api-{uuid4().hex}"
    data = {"prefix": prefix}
    role_ids = dict((await db_session.execute(select(Role.code, Role.id))).all())
    for name, code in [
        ("admin", "admin"),
        ("admin2", "admin"),
        ("target", "driver"),
        ("owner", "station_owner"),
        ("operator", "operator"),
        ("driver", "driver"),
        ("accountant", "accountant"),
    ]:
        user = User(
            email=f"{prefix}-{name}@example.com", password_hash=hash_password(PASSWORD)
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(UserRole(user_id=user.id, role_id=role_ids[code]))
        token = f"{prefix}-{name}-token"
        db_session.add(
            Session(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        data[name] = str(user.id)
        data[f"{name}_token"] = token
    await db_session.commit()
    try:
        yield data
    finally:
        await db_session.rollback()
        ids = select(User.id).where(User.email.startswith(prefix))
        await db_session.execute(
            delete(AccountAudit).where(AccountAudit.target_id.in_(ids))
        )
        await db_session.execute(delete(User).where(User.email.startswith(prefix)))
        await db_session.execute(
            delete(LoginIpAttempt).where(LoginIpAttempt.ip_address == prefix)
        )
        await db_session.commit()


def client_for(accounts: dict[str, str], name: str = "admin") -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(accounts["prefix"], 123)),
        base_url="http://test",
        cookies={"session": accounts[f"{name}_token"]},
    )


@pytest.mark.asyncio
async def test_create_account_roles_login_and_audit(
    accounts: dict[str, str], db_session: AsyncSession
) -> None:
    email = f"{accounts['prefix']}-NEW@Example.com"
    async with client_for(accounts) as client:
        roles = await client.get("/api/v1/admin/roles")
        assert {r["code"] for r in roles.json()} == {
            "admin",
            "operator",
            "station_owner",
            "driver",
            "accountant",
        }
        response = await client.post(
            BASE,
            json={
                "email": email,
                "password": PASSWORD,
                "roles": ["driver", "station_owner"],
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["email"] == email.lower()
        assert body["roles"] == ["driver", "station_owner"]
        assert body["status"] == "active"
        assert response.headers["cache-control"] == "no-store"
        duplicate = await client.post(
            BASE,
            json={"email": email.lower(), "password": PASSWORD, "roles": ["driver"]},
        )
        assert duplicate.status_code == 409
    stored = await db_session.get(User, UUID(body["id"]))
    assert stored and stored.password_hash != PASSWORD
    assert verify_password(stored.password_hash, PASSWORD)
    audit = await db_session.scalar(
        select(AccountAudit).where(AccountAudit.target_id == stored.id)
    )
    assert audit and audit.before_state is None
    assert audit.permission == "admin.accounts.manage"
    assert audit.actor_roles == ["admin"]
    assert "password" not in str(audit.after_state)
    async with client_for(accounts, "target") as client:
        login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        assert login.status_code == 200
        me = await client.get("/api/v1/auth/me")
        assert me.json()["roles"] == ["driver", "station_owner"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["owner", "operator", "driver", "accountant"])
async def test_only_admin_can_use_all_endpoints(
    accounts: dict[str, str], name: str
) -> None:
    async with client_for(accounts, name) as client:
        for method, url, body in [
            ("GET", BASE, None),
            ("GET", "/api/v1/admin/roles", None),
            ("GET", f"{BASE}/{accounts['target']}", None),
            (
                "POST",
                BASE,
                {
                    "email": "denied@example.com",
                    "password": PASSWORD,
                    "roles": ["admin"],
                },
            ),
            (
                "PATCH",
                f"{BASE}/{accounts['target']}",
                {
                    "status": "suspended",
                    "expected_updated_at": datetime.now(UTC).isoformat(),
                },
            ),
        ]:
            response = await client.request(method, url, json=body)
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "permission_denied"
        client.cookies.clear()
        assert (await client.get(BASE)).status_code == 401


@pytest.mark.asyncio
async def test_filters_pagination_and_validation(accounts: dict[str, str]) -> None:
    async with client_for(accounts) as client:
        response = await client.get(
            BASE, params={"search": accounts["prefix"], "role": "admin", "page_size": 1}
        )
        body = response.json()
        assert body["total"] == 2 and body["total_pages"] == 2
        page2 = await client.get(
            BASE,
            params={
                "search": accounts["prefix"],
                "role": "admin",
                "page_size": 1,
                "page": 2,
            },
        )
        assert body["items"][0]["id"] != page2.json()["items"][0]["id"]
        assert (await client.get(BASE, params={"search": "%"})).json()["total"] == 0
        assert (await client.get(BASE, params={"page_size": 101})).status_code == 422
        assert (await client.get(f"{BASE}/{uuid4()}")).status_code == 404
        for roles in [[], ["admin", "admin"], ["superadmin"]]:
            invalid = await client.post(
                BASE,
                json={
                    "email": f"{accounts['prefix']}-invalid@example.com",
                    "password": PASSWORD,
                    "roles": roles,
                },
            )
            assert invalid.status_code == 422
            assert PASSWORD not in invalid.text
        invalid = await client.post(
            BASE,
            json={
                "email": f"{accounts['prefix']}-invalid@example.com",
                "password": "abcXYZ9!",
                "roles": ["admin"],
            },
        )
        assert invalid.status_code == 422
        assert "abcXYZ9!" not in invalid.text

        target_url = f"{BASE}/{accounts['target']}"
        timestamp = (await client.get(target_url)).json()["updated_at"]
        for changes in [
            {},
            {"roles": None},
            {"status": None},
            {"roles": []},
            {"roles": ["admin", "admin"]},
            {"status": "deactivated"},
            {"email": "changed@example.com"},
        ]:
            invalid = await client.patch(
                target_url, json={"expected_updated_at": timestamp, **changes}
            )
            assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_roles_apply_next_request_and_lock_revokes_sessions(
    accounts: dict[str, str],
) -> None:
    async with client_for(accounts) as admin, client_for(accounts, "target") as target:
        before = (await admin.get(f"{BASE}/{accounts['target']}")).json()
        changed = await admin.patch(
            f"{BASE}/{accounts['target']}",
            json={
                "expected_updated_at": before["updated_at"],
                "roles": ["driver", "operator"],
            },
        )
        assert changed.status_code == 200, changed.text
        assert (await target.get("/api/v1/auth/me")).json()["roles"] == [
            "driver",
            "operator",
        ]
        stale = await admin.patch(
            f"{BASE}/{accounts['target']}",
            json={"expected_updated_at": before["updated_at"], "status": "suspended"},
        )
        assert stale.status_code == 409
        locked = await admin.patch(
            f"{BASE}/{accounts['target']}",
            json={
                "expected_updated_at": changed.json()["updated_at"],
                "status": "suspended",
            },
        )
        assert locked.status_code == 200
        assert (await target.get("/api/v1/auth/me")).status_code == 401
        login = await target.post(
            "/api/v1/auth/login", json={"email": before["email"], "password": PASSWORD}
        )
        assert login.status_code == 401
        unlocked = await admin.patch(
            f"{BASE}/{accounts['target']}",
            json={
                "expected_updated_at": locked.json()["updated_at"],
                "status": "active",
            },
        )
        assert unlocked.status_code == 200
        assert (await target.get("/api/v1/auth/me")).status_code == 401
        assert (
            await target.post(
                "/api/v1/auth/login",
                json={"email": before["email"], "password": PASSWORD},
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_self_protection_and_concurrent_admin_demotions(
    accounts: dict[str, str],
) -> None:
    async with client_for(accounts) as first, client_for(accounts, "admin2") as second:
        a = (await first.get(f"{BASE}/{accounts['admin']}")).json()
        b = (await first.get(f"{BASE}/{accounts['admin2']}")).json()
        for change in [{"status": "suspended"}, {"roles": ["driver"]}]:
            result = await first.patch(
                f"{BASE}/{accounts['admin']}",
                json={"expected_updated_at": a["updated_at"], **change},
            )
            assert result.status_code == 409
        results = await asyncio.gather(
            first.patch(
                f"{BASE}/{accounts['admin2']}",
                json={"expected_updated_at": b["updated_at"], "roles": ["driver"]},
            ),
            second.patch(
                f"{BASE}/{accounts['admin']}",
                json={"expected_updated_at": a["updated_at"], "roles": ["driver"]},
            ),
        )
        assert sorted(r.status_code for r in results) == [200, 403]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["suspended", "deactivated", "pending_deletion", "anonymized"]
)
async def test_nonactive_accounts_cannot_login_or_use_session(
    accounts: dict[str, str], db_session: AsyncSession, status: str
) -> None:
    user = await db_session.get(User, UUID(accounts["target"]))
    assert user
    user.status = status
    await db_session.commit()
    async with client_for(accounts, "target") as client:
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        assert (
            await client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
            )
        ).status_code == 401
