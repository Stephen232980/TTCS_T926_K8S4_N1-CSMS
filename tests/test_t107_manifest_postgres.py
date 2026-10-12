"""Real PostgreSQL isolation/idempotency tests for the T-108 manifest contract.

The fixture creates and drops a separate temporary PostgreSQL database.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from scripts.t107_manifest_run import apply_run, cleanup_run
from simulator.t108_contract import new_manifest
from simulator.t108_fixture import prepare_station, user
from src.modules.charging.models import ChargingCard, ChargingSession
from src.modules.charging.service import tag_hash
from src.modules.identity.models import User
from src.modules.pricing.models import Tariff, TariffBand
from src.modules.stations.models import ChargePoint, Station
from src.modules.wallet.models import Wallet, WalletLedger
from src.modules.wallet.service import ghi_so_cai
from src.platform.audit.models import AuditLog
from tests.test_effective_tariffs import committed_tariff_db as isolated_t107_db

committed_tariff_db = isolated_t107_db


@pytest.mark.asyncio
async def test_two_runs_concurrency_retry_after_debit_and_cleanup(committed_tariff_db):
    factory = committed_tariff_db
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t107-manifest-admin@example.com", ["admin"])
    first = new_manifest(revision="t107-test", mode="ci", count=20)
    second = new_manifest(revision="t107-test", mode="ci", count=20)
    async with factory() as db, db.begin():
        await prepare_station(db, first)
        await prepare_station(db, second)

    async def run_seed(manifest):
        async with factory() as db, db.begin():
            return await apply_run(
                db, manifest.model_copy(deep=True), "t107-manifest-admin@example.com"
            )

    assert sorted(await asyncio.gather(run_seed(first), run_seed(first))) == [0, 20]
    assert await run_seed(second) == 20
    async with factory() as db, db.begin():
        assert await apply_run(db, first, "t107-manifest-admin@example.com") == 0
        assert await apply_run(db, second, "t107-manifest-admin@example.com") == 0
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 40
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "wallet.manual_topup")
            )
            == 40
        )
        for run in (first, second):
            ids = [p.driver_id for p in run.participants]
            wallets = list(
                await db.scalars(select(Wallet).where(Wallet.driver_id.in_(ids)))
            )
            assert len(wallets) == 20 and all(
                w.balance_vnd == run.seed_amount_vnd for w in wallets
            )
            cards = list(
                await db.scalars(
                    select(ChargingCard).where(ChargingCard.driver_id.in_(ids))
                )
            )
            assert len(cards) == 40 and all(c.status == "active" for c in cards)
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Tariff)
                    .where(Tariff.station_id == run.station_id)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(TariffBand)
                    .where(TariffBand.tariff_id == run.tariff_id)
                )
                == 3
            )
            receipts = list(
                await db.scalars(
                    select(WalletLedger).where(
                        WalletLedger.reference_id.in_(
                            [p.seed_receipt_code for p in run.participants]
                        )
                    )
                )
            )
            assert len(receipts) == 20
            assert all(
                r.entry_type == "manual_topup"
                and r.reference_type == "manual_topup"
                and r.actor_id is not None
                and r.amount_vnd == run.seed_amount_vnd
                for r in receipts
            )
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
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 41
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "wallet.manual_topup")
            )
            == 40
        )
        assert (await db.get(Station, first.station_id)).archived_at is not None
        assert (await db.get(Station, second.station_id)).archived_at is None
        drivers = list(
            await db.scalars(
                select(User).where(
                    User.id.in_([p.driver_id for p in first.participants])
                )
            )
        )
        assert len(drivers) == 20 and all(d.status == "deactivated" for d in drivers)


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


async def test_mid_run_card_conflict_rolls_back_all_twenty_drivers(committed_tariff_db):
    factory = committed_tariff_db
    run = new_manifest(revision="t107-test", mode="ci", count=20)
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t107-conflict-admin@example.com", ["admin"])
        await prepare_station(db, run)
        foreign = await user(db, uuid4(), "t107-foreign-driver@example.com", ["driver"])
        card = ChargingCard(
            tag_hash=tag_hash(run.participants[9].card_tag),
            tag_tail="test",
            driver_id=foreign.id,
            issuer_id=run.owner_id,
            status="active",
        )
        db.add(card)
        await db.flush()
        collision_id, foreign_id = card.id, foreign.id
    with pytest.raises(ValueError, match="card collision"):
        async with factory() as db, db.begin():
            await apply_run(
                db, run.model_copy(deep=True), "t107-conflict-admin@example.com"
            )
    async with factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.id.in_([p.driver_id for p in run.participants]))
            )
            == 0
        )
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 0
        assert (await db.get(ChargingCard, collision_id)).driver_id == foreign_id
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "wallet.manual_topup")
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Tariff)
                .where(Tariff.station_id == run.station_id)
            )
            == 1
        )


@pytest.mark.parametrize("ended", [False, True], ids=["open", "ended-unsettled"])
async def test_cleanup_rejects_open_or_unsettled_without_partial_archiving(
    committed_tariff_db, ended
):
    factory = committed_tariff_db
    run = new_manifest(revision="t107-test", mode="ci", count=20)
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t107-cleanup-admin@example.com", ["admin"])
        await prepare_station(db, run)
        assert await apply_run(db, run, "t107-cleanup-admin@example.com") == 20
        participant = run.participants[9]
        now = datetime.now(UTC)
        db.add(
            ChargingSession(
                charge_point_id=participant.charge_point_id,
                connector_id=participant.connector_id,
                driver_id=participant.driver_id,
                tag_tail="test",
                authorization_status="Accepted",
                started_at=now - timedelta(minutes=1),
                ended_at=now if ended else None,
                meter_start_wh=Decimal(0),
                meter_stop_wh=Decimal(1000) if ended else None,
                billing_lifecycle_version=0,
                review_reasons=[],
            )
        )
    with pytest.raises(ValueError, match="open/unsettled"):
        async with factory() as db, db.begin():
            await cleanup_run(db, run)
    async with factory() as db:
        assert (await db.get(Station, run.station_id)).archived_at is None
        drivers = list(
            await db.scalars(
                select(User).where(User.id.in_([p.driver_id for p in run.participants]))
            )
        )
        assert len(drivers) == 20 and all(d.status == "active" for d in drivers)
        chargers = list(
            await db.scalars(
                select(ChargePoint).where(ChargePoint.station_id == run.station_id)
            )
        )
        assert len(chargers) == 20 and all(c.archived_at is None for c in chargers)
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 20
