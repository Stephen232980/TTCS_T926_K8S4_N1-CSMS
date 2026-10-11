import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.platform.audit.models import AuditLog
from src.platform.audit.service import ghi_nhat_ky
from tests.test_wallet_service import isolated_wallet_db  # noqa: F401


def fields(**overrides):
    return {
        "actor_id": None,
        "action": "wallet.reconcile",
        "object_type": "wallet",
        "object_id": str(uuid4()),
    } | overrides


async def test_generic_summary_id_system_actor_and_authorization(db_session):
    data = {
        "ledger_id": 12,
        "amount_vnd": 500000,
        "receipt_code": "PT-001",
        "checks": [{"matched": True}],
    }
    audit_id = await ghi_nhat_ky(
        db_session,
        **fields(
            data=data,
            permission="admin.wallet.manual_topup",
            actor_roles=["admin", "admin"],
        ),
    )
    assert isinstance(audit_id, UUID)
    data["checks"][0]["matched"] = False
    row = await db_session.get(AuditLog, audit_id)
    assert row.actor_id is None and row.occurred_at.tzinfo is not None
    assert row.data["checks"][0]["matched"] is True
    assert row.permission == "admin.wallet.manual_topup" and row.actor_roles == [
        "admin"
    ]


@pytest.mark.parametrize(
    "key",
    [
        "idTag",
        "id_tag",
        "ID-Tag",
        "EMAIL",
        "phone_number",
        "access-token",
        "passwordHash",
    ],
)
@pytest.mark.parametrize("nested", [False, True])
async def test_sensitive_keys_rejected_recursively_without_writing(
    db_session, key, nested
):
    data = {key: "private"}
    if nested:
        data = {"items": [{"inner": data}]}
    with pytest.raises(ValueError, match="Sensitive"):
        await ghi_nhat_ky(db_session, **fields(data=data))
    assert (await db_session.scalars(select(AuditLog))).all() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"action": " "},
        {"object_type": ""},
        {"object_id": " "},
        {"action": "x" * 101},
        {"permission": " "},
        {"actor_roles": "admin"},
        {"data": {"value": float("nan")}},
        {"data": {"value": uuid4()}},
    ],
)
async def test_invalid_summary_rejected(db_session, overrides):
    with pytest.raises((ValueError, TypeError)):
        await ghi_nhat_ky(db_session, **fields(**overrides))
    assert (await db_session.scalars(select(AuditLog))).all() == []


async def test_default_json_and_database_constraints(db_session):
    audit_id = await ghi_nhat_ky(db_session, **fields())
    row = await db_session.get(AuditLog, audit_id)
    assert row.data == {} and row.permission is None and row.actor_roles is None
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO audit_logs(id,action,object_type,object_id,data) VALUES (:id,'x','wallet','1','[]'::jsonb)"
                ),
                {"id": uuid4()},
            )


async def test_actor_reference_is_validated(db_session):
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await ghi_nhat_ky(db_session, **fields(actor_id=uuid4()))


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE audit_logs SET action='changed'",
        "DELETE FROM audit_logs",
        "TRUNCATE audit_logs",
    ],
)
async def test_even_owner_cannot_rewrite_audit(db_session, mutation):
    audit_id = await ghi_nhat_ky(db_session, **fields())
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(mutation))
    assert await db_session.get(AuditLog, audit_id) is not None


async def test_caller_rollback_removes_audit_and_helper_does_not_commit(
    isolated_wallet_db,  # noqa: F811
):
    factory = isolated_wallet_db
    async with factory() as session:
        audit_id = await ghi_nhat_ky(session, **fields())
        async with factory() as reader:
            assert await reader.get(AuditLog, audit_id) is None
        await session.rollback()
    async with factory() as reader:
        assert await reader.get(AuditLog, audit_id) is None


async def test_real_runtime_login_insert_select_only_and_no_owner_membership(
    isolated_wallet_db,  # noqa: F811
):
    owner_url = isolated_wallet_db.kw["bind"].url
    connection_url = owner_url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    role = "t57_runtime_" + uuid4().hex
    password = uuid4().hex
    with psycopg.connect(connection_url, autocommit=True) as owner:
        owner.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOINHERIT PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        grants = Path("scripts/grant_audit_logs.sql").read_text(encoding="utf-8")
        grants = "\n".join(
            line for line in grants.splitlines() if not line.startswith(("--", "\\"))
        )
        owner.execute(grants.replace(':"app_role"', '"' + role + '"'))
    engine = create_async_engine(owner_url.set(username=role, password=password))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as runtime:
            result = (
                await runtime.execute(
                    text(
                        "SELECT current_user, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert tuple(result) == (role, False, False, False, False)
            assert (
                await runtime.scalar(
                    text(
                        "SELECT pg_has_role(current_user, tableowner, 'MEMBER') FROM pg_tables WHERE schemaname='public' AND tablename='audit_logs'"
                    )
                )
                is False
            )
            assert (
                await runtime.scalar(
                    text(
                        "SELECT tableowner=current_user FROM pg_tables WHERE schemaname='public' AND tablename='audit_logs'"
                    )
                )
                is False
            )
            audit_id = await ghi_nhat_ky(runtime, **fields())
            await runtime.commit()
            assert await runtime.get(AuditLog, audit_id) is not None
            for mutation in [
                "UPDATE audit_logs SET action='x'",
                "DELETE FROM audit_logs",
                "TRUNCATE audit_logs",
            ]:
                with pytest.raises(DBAPIError) as error:
                    async with runtime.begin_nested():
                        await runtime.execute(text(mutation))
                assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        await engine.dispose()
        with psycopg.connect(connection_url, autocommit=True) as owner:
            owner.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            owner.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


async def test_foundation_migration_round_trip(isolated_wallet_db):  # noqa: F811
    factory = isolated_wallet_db
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for direction, target in [("downgrade", "f130014a2026"), ("upgrade", "head")]:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", direction, target],
            env=os.environ | {"DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
        async with factory() as session:
            assert (await session.scalar(text("SELECT to_regclass('audit_logs')"))) == (
                None if direction == "downgrade" else "audit_logs"
            )
            assert (
                await session.scalar(
                    text("SELECT to_regclass('ocpp_control_requests')")
                )
                == "ocpp_control_requests"
            )
