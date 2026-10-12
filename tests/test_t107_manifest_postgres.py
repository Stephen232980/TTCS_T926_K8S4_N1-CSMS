"""Real PostgreSQL isolation/idempotency tests for the T-108 manifest contract.

The fixture creates and drops a separate temporary PostgreSQL database.
"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from scripts.t107_manifest_run import apply_run, cleanup_run
from simulator.t108_contract import new_manifest
from simulator.t108_fixture import prepare_station, user
from src.modules.charging.models import ChargingCard
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import ghi_so_cai
from tests.test_effective_tariffs import committed_tariff_db as isolated_t107_db

committed_tariff_db = isolated_t107_db


@pytest.mark.asyncio
async def test_two_runs_concurrency_retry_after_debit_and_cleanup(committed_tariff_db):
    factory = committed_tariff_db
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t107-manifest-admin@example.com", ["admin"])
    first = new_manifest(revision="t107-test", mode="ci", count=2)
    second = new_manifest(revision="t107-test", mode="ci", count=2)
    async with factory() as db, db.begin():
        await prepare_station(db, first)
        await prepare_station(db, second)

    async def run_seed(manifest):
        async with factory() as db, db.begin():
            return await apply_run(
                db, manifest.model_copy(deep=True), "t107-manifest-admin@example.com"
            )

    assert sorted(await asyncio.gather(run_seed(first), run_seed(first))) == [0, 2]
    assert await run_seed(second) == 2
    async with factory() as db, db.begin():
        assert await apply_run(db, first, "t107-manifest-admin@example.com") == 0
        assert await apply_run(db, second, "t107-manifest-admin@example.com") == 0
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 4
        wallet = await db.scalar(
            select(Wallet).where(Wallet.driver_id == first.participants[0].driver_id)
        )
        await ghi_so_cai(
            db,
            wallet_id=wallet.id,
            entry_type="charging_debit",
            amount_vnd=-1000,
            reference_type="charging_session",
            reference_id="t107-debit",
        )
    assert await run_seed(first) == 0
    async with factory() as db:
        wallet = await db.scalar(
            select(Wallet).where(Wallet.driver_id == first.participants[0].driver_id)
        )
        assert wallet.balance_vnd == first.seed_amount_vnd - 1000

    async with factory() as db, db.begin():
        await cleanup_run(db, first)
        await cleanup_run(db, first)
    async with factory() as db:
        cards = list(
            await db.scalars(
                select(ChargingCard).where(
                    ChargingCard.driver_id == second.participants[0].driver_id
                )
            )
        )
        assert len(cards) == 2 and all(card.status == "active" for card in cards)
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 5


@pytest.mark.asyncio
async def test_preflight_mismatch_causes_no_wallet_writes(committed_tariff_db):
    factory = committed_tariff_db
    run = new_manifest(revision="t107-test", mode="ci", count=2)
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t107-manifest-admin-2@example.com", ["admin"])
        await prepare_station(db, run)
    bad = run.model_copy(deep=True)
    bad.seed_amount_vnd += 1
    with pytest.raises(ValueError, match="not prepared"):
        async with factory() as db, db.begin():
            await apply_run(db, bad, "t107-manifest-admin-2@example.com")
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0
