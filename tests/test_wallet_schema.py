from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.modules.identity.models import User
from src.modules.wallet.models import Wallet, WalletLedger


async def wallet_fixture(session):
    driver = User(email=f"wallet-{uuid4()}@example.com", password_hash="unused")
    session.add(driver)
    await session.flush()
    wallet = Wallet(driver_id=driver.id)
    session.add(wallet)
    await session.flush()
    return driver, wallet


def entry(target_wallet_id, **overrides):
    values = {
        "wallet_id": target_wallet_id,
        "entry_type": "manual_topup",
        "amount_vnd": 5_000_000_000,
        "balance_after_vnd": 5_000_000_000,
        "reference_type": "manual_topup",
        "reference_id": str(uuid4()),
    }
    return WalletLedger(**(values | overrides))


async def test_wallet_defaults_bigint_debt_and_latest_history(db_session):
    driver, wallet = await wallet_fixture(db_session)
    assert wallet.balance_vnd == 0 and wallet.status == "active"
    assert wallet.created_at.tzinfo is not None
    positive = entry(wallet.id, actor_id=driver.id)
    debit = entry(
        wallet.id,
        entry_type="charging_debit",
        amount_vnd=-6_000_000_000,
        balance_after_vnd=-1_000_000_000,
        reference_type="charging_session",
    )
    db_session.add_all([positive, debit])
    wallet.balance_vnd = -1_000_000_000
    await db_session.flush()
    rows = (
        await db_session.scalars(
            select(WalletLedger)
            .where(WalletLedger.wallet_id == wallet.id)
            .order_by(WalletLedger.id.desc())
        )
    ).all()
    assert [row.amount_vnd for row in rows] == [-6_000_000_000, 5_000_000_000]
    assert rows[0].actor_id is None and rows[1].actor_id == driver.id
    assert rows[0].balance_after_vnd == wallet.balance_vnd
    assert all(row.created_at.tzinfo is not None for row in rows)


async def test_driver_has_only_one_wallet(db_session):
    driver, _ = await wallet_fixture(db_session)
    with pytest.raises(IntegrityError, match="uq_wallets_driver"):
        async with db_session.begin_nested():
            db_session.add(Wallet(driver_id=driver.id))
            await db_session.flush()


@pytest.mark.parametrize(
    "kind", ["gateway_topup", "manual_topup", "charging_debit", "adjustment"]
)
async def test_all_ledger_types_exist_including_adjustment(db_session, kind):
    driver, wallet = await wallet_fixture(db_session)
    row = entry(
        wallet.id,
        entry_type=kind,
        actor_id=driver.id,
        reference_type="audit" if kind == "adjustment" else "manual_topup",
    )
    db_session.add(row)
    await db_session.flush()
    assert row.id is not None


@pytest.mark.parametrize("other_wallet", [False, True])
async def test_reference_collision_is_global_even_with_different_reference_type(
    db_session, other_wallet
):
    driver, wallet = await wallet_fixture(db_session)
    row = entry(wallet.id)
    db_session.add(row)
    await db_session.flush()
    second = (await wallet_fixture(db_session))[1] if other_wallet else wallet
    with pytest.raises(IntegrityError, match="uq_wallet_ledger_reference"):
        async with db_session.begin_nested():
            db_session.add(
                entry(
                    second.id,
                    reference_id=row.reference_id,
                    reference_type="other",
                    amount_vnd=1,
                )
            )
            await db_session.flush()
    # Distinct financial operations may share an ID, as specified by (type, ID).
    db_session.add(
        entry(
            wallet.id,
            reference_id=row.reference_id,
            entry_type="adjustment",
            reference_type="audit",
            actor_id=driver.id,
        )
    )
    await db_session.flush()


@pytest.mark.parametrize(
    "model,field,value,constraint",
    [
        ("wallet", "status", "unknown", "ck_wallets_status"),
        ("ledger", "entry_type", "unknown", "ck_wallet_ledger_entry_type"),
        ("ledger", "reference_id", "   ", "ck_wallet_ledger_reference_nonempty"),
        ("ledger", "reference_type", "", "ck_wallet_ledger_reference_nonempty"),
    ],
)
async def test_database_rejects_invalid_wallet_fields(
    db_session, model, field, value, constraint
):
    _, wallet = await wallet_fixture(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            if model == "wallet":
                wallet.status = value
            else:
                db_session.add(entry(wallet.id, **{field: value}))
            await db_session.flush()


@pytest.mark.parametrize("target", ["driver", "wallet", "actor"])
async def test_missing_foreign_keys_rejected(db_session, target):
    _, wallet = await wallet_fixture(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            row = (
                Wallet(driver_id=uuid4())
                if target == "driver"
                else entry(
                    wallet.id,
                    **{("wallet_id" if target == "wallet" else "actor_id"): uuid4()},
                )
            )
            db_session.add(row)
            await db_session.flush()


@pytest.mark.parametrize("target", ["driver", "wallet", "actor"])
async def test_delete_cannot_remove_referenced_financial_entities(db_session, target):
    driver, wallet = await wallet_fixture(db_session)
    actor = User(email=f"actor-{uuid4()}@example.com", password_hash="unused")
    db_session.add(actor)
    await db_session.flush()
    db_session.add(entry(wallet.id, actor_id=actor.id))
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            if target == "wallet":
                await db_session.execute(delete(Wallet).where(Wallet.id == wallet.id))
            else:
                await db_session.execute(
                    delete(User).where(
                        User.id == (driver.id if target == "driver" else actor.id)
                    )
                )


MUTATIONS = [
    "UPDATE wallet_ledger SET amount_vnd = 1",
    "DELETE FROM wallet_ledger",
    "TRUNCATE wallet_ledger",
    "TRUNCATE wallets CASCADE",
]


@pytest.mark.parametrize("statement", MUTATIONS)
async def test_owner_cannot_modify_ledger_even_by_cascading_truncate(
    db_session, statement
):
    _, wallet = await wallet_fixture(db_session)
    db_session.add(entry(wallet.id))
    await db_session.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_restricted_application_role_can_insert_read_but_not_mutate(db_session):
    _, wallet = await wallet_fixture(db_session)
    role = "test_wallet_" + uuid4().hex
    # Role creation and grants roll back with the test fixture; no persistent role.
    await db_session.execute(
        text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOINHERIT')
    )
    sql = Path("scripts/grant_wallet_ledger.sql").read_text(encoding="utf-8")
    sql = "\n".join(
        line for line in sql.splitlines() if not line.startswith(("--", "\\"))
    )
    for statement in sql.replace(':"app_role"', f'"{role}"').split(";"):
        if statement.strip() and statement.strip() not in ("BEGIN", "COMMIT"):
            await db_session.execute(text(statement))
    async with db_session.begin_nested():
        await db_session.execute(text(f'SET LOCAL ROLE "{role}"'))
        row = (
            await db_session.execute(
                text("""INSERT INTO wallet_ledger
            (wallet_id, entry_type, amount_vnd, balance_after_vnd, reference_type, reference_id)
            VALUES (:wallet, 'manual_topup', 5000, 5000, 'manual_topup', :reference)
            RETURNING id, amount_vnd"""),
                {"wallet": wallet.id, "reference": str(uuid4())},
            )
        ).one()
        assert row[1] == 5000
        assert (
            await db_session.scalar(
                text("SELECT amount_vnd FROM wallet_ledger WHERE id = :id"),
                {"id": row[0]},
            )
            == 5000
        )
        for statement in MUTATIONS[:3]:
            with pytest.raises(DBAPIError, match="permission denied"):
                async with db_session.begin_nested():
                    await db_session.execute(text(statement))
        await db_session.execute(text("RESET ROLE"))


async def test_wallet_history_index_and_integer_column_types(db_session):
    index = await db_session.scalar(
        text(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'wallet_ledger' AND indexname = 'ix_wallet_ledger_wallet_id_id_desc'"
        )
    )
    assert "(wallet_id, id DESC)" in index
    rows = (
        await db_session.execute(
            text("""SELECT table_name, column_name, data_type
        FROM information_schema.columns WHERE table_schema = 'public'
        AND ((table_name = 'wallets' AND column_name = 'balance_vnd')
        OR (table_name = 'wallet_ledger' AND column_name IN ('id', 'amount_vnd', 'balance_after_vnd')))""")
        )
    ).all()
    assert len(rows) == 4 and all(row[2] == "bigint" for row in rows)


@pytest.mark.parametrize("invalid", ["missing_actor", "missing_audit_type"])
async def test_adjustment_requires_human_actor_and_audit_reference(db_session, invalid):
    driver, wallet = await wallet_fixture(db_session)
    with pytest.raises(IntegrityError, match="ck_wallet_ledger_adjustment_audit"):
        async with db_session.begin_nested():
            db_session.add(
                entry(
                    wallet.id,
                    entry_type="adjustment",
                    actor_id=None if invalid == "missing_actor" else driver.id,
                    reference_type="manual_topup"
                    if invalid == "missing_audit_type"
                    else "audit",
                )
            )
            await db_session.flush()


async def test_adjustment_storage_allows_locked_wallet_and_negative_balance(db_session):
    driver, wallet = await wallet_fixture(db_session)
    wallet.status = "locked"
    row = entry(
        wallet.id,
        entry_type="adjustment",
        actor_id=driver.id,
        reference_type="audit",
        amount_vnd=-50_000,
        balance_after_vnd=-50_000,
    )
    db_session.add(row)
    await db_session.flush()
    assert row.id is not None and row.amount_vnd == -50_000
