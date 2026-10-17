import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.modules.billing.models import Invoice
from src.modules.charging.models import ChargingSession
from src.modules.identity.authorization import AuthorizationEvidence
from src.modules.privacy.default_policy import VERSION
from src.modules.privacy.executor import execute_job
from src.modules.privacy.models import PrivacyJob
from src.modules.privacy.schemas import PrivacyDecision
from src.modules.privacy.service import PrivacyRetentionService
from src.modules.privacy.worker import privacy_execution_loop
from src.modules.reporting.schemas import RevenueReportQuery
from src.modules.reporting.service import get_revenue_report
from src.modules.stations.models import ChargePoint, Connector, Station
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import SessionFactory
from tests.test_privacy_postgres import seed


async def prepared_job():
    uid, admin = await seed()
    now = datetime.now(UTC)
    async with SessionFactory() as db:
        station = Station(
            owner_id=admin,
            name="Retained",
            address="Test",
            latitude=Decimal(0),
            longitude=Decimal(0),
        )
        db.add(station)
        await db.flush()
        cp = ChargePoint(station_id=station.id, code=f"privacy-exec-{uuid4().hex}")
        db.add(cp)
        await db.flush()
        connector = Connector(charge_point_id=cp.id, connector_number=1)
        db.add(connector)
        await db.flush()
        session = ChargingSession(
            charge_point_id=cp.id,
            connector_id=connector.id,
            driver_id=uid,
            tag_tail="1234",
            authorization_status="Accepted",
            started_at=now - timedelta(hours=1),
            ended_at=now,
            connector_released_at=now,
            settlement_completed_at=now,
            settlement_reason="debited",
            meter_start_wh=Decimal(0),
            meter_stop_wh=Decimal(1000),
            energy_kwh=Decimal(1),
        )
        db.add(session)
        await db.flush()
        db.add(
            Invoice(
                driver_id=uid,
                station_id=station.id,
                session_id=session.id,
                total_vnd=1000,
                rounding_rule="test",
            )
        )
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == uid))
        db.add_all(
            [
                WalletLedger(
                    wallet_id=wallet.id,
                    entry_type="gateway_topup",
                    amount_vnd=1000,
                    balance_after_vnd=1000,
                    reference_type="test",
                    reference_id=str(uuid4()),
                ),
                WalletLedger(
                    wallet_id=wallet.id,
                    entry_type="charging_debit",
                    amount_vnd=-1000,
                    balance_after_vnd=0,
                    reference_type="charging_session",
                    reference_id=str(session.id),
                ),
            ]
        )
        await db.commit()
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(
            uid, "privacy-test-password", "Erase personal data"
        )
        await service.review_request(
            receipt.id,
            PrivacyDecision(
                decision="approved", reason="Approved request", policy_version=VERSION
            ),
            admin,
            AuthorizationEvidence(permission="admin.privacy.manage", roles=("admin",)),
        )
        job = await db.scalar(
            select(PrivacyJob).where(PrivacyJob.request_id == receipt.id)
        )
        return uid, admin, job.id, session.id


async def financial_snapshot(db):
    return (
        await db.execute(
            text(
                "SELECT (SELECT COALESCE(sum(total_vnd),0) FROM invoices), (SELECT COALESCE(sum(amount_vnd),0) FROM wallet_ledger),(SELECT COALESCE(sum(energy_kwh),0) FROM charging_sessions)"
            )
        )
    ).one()


async def test_executor_preserves_financials_and_removes_original_join_paths():
    uid, owner_id, job_id, session_id = await prepared_job()
    async with SessionFactory() as db:
        before = await financial_snapshot(db)
        report_before = (
            await get_revenue_report(db, RevenueReportQuery(period="month"), owner_id)
        ).model_dump()
    engine = create_async_engine(settings.database_url)

    # Exercise the same NOLOGIN privilege group used by the separate worker.
    @event.listens_for(engine.sync_engine, "connect")
    def set_executor_role(connection, _):
        connection.cursor().execute("SET ROLE csms_privacy_executor")

    try:
        assert await execute_job(engine, job_id) == 3
        assert await execute_job(engine, job_id) == 3
    finally:
        await engine.dispose()
    async with SessionFactory() as db:
        assert await financial_snapshot(db) == before
        assert (
            await get_revenue_report(db, RevenueReportQuery(period="month"), owner_id)
        ).model_dump() == report_before
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM privacy_private.subjects WHERE original_user_id=:uid"
                ),
                {"uid": uid},
            )
            == 0
        )
        assert (
            await db.scalar(
                text("SELECT status FROM users WHERE id=:uid"), {"uid": uid}
            )
            == "anonymized"
        )
        assert await db.scalar(
            text("SELECT driver_id<>:uid FROM charging_sessions WHERE id=:id"),
            {"uid": uid, "id": session_id},
        )
        for table in (
            "invoices",
            "wallets",
            "charging_sessions",
            "charging_cards",
            "wallet_topups",
            "reservations",
            "driver_start_requests",
        ):
            assert (
                await db.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE driver_id=:uid"),
                    {"uid": uid},
                )
                == 0
            )
        assert (
            await db.scalar(
                text("SELECT count(*) FROM sessions WHERE user_id=:uid"), {"uid": uid}
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM charging_cards WHERE driver_id=(SELECT driver_id FROM charging_sessions WHERE id=:id) AND status='active'"
                ),
                {"id": session_id},
            )
            == 0
        )


async def test_hold_after_freeze_blocks_redaction_and_can_be_reviewed():
    uid, admin, job_id, _ = await prepared_job()
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                text("SELECT privacy_private.execute_stage(:id)"), {"id": job_id}
            )
            == 1
        )
        await db.commit()
        await PrivacyRetentionService(db).set_legal_hold(
            uid, True, "New dispute", admin
        )
        with pytest.raises(DBAPIError, match="legal_hold"):
            await db.execute(
                text("SELECT privacy_private.execute_stage(:id)"), {"id": job_id}
            )
        await db.rollback()
        assert (
            await db.scalar(
                text("SELECT checkpoint FROM privacy_jobs WHERE id=:id"), {"id": job_id}
            )
            == 1
        )
        assert (
            await db.scalar(
                text("SELECT count(*) FROM charging_sessions WHERE driver_id=:uid"),
                {"uid": uid},
            )
            == 1
        )


async def test_application_cannot_call_private_function_or_bypass_immutable_trigger():
    await prepared_job()
    async with SessionFactory() as db:
        await db.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='privacy_test_app') THEN CREATE ROLE privacy_test_app NOLOGIN; END IF; END $$"
            )
        )
        await db.execute(
            text("GRANT SELECT,UPDATE ON public.invoices TO privacy_test_app")
        )
        await db.commit()
        await db.execute(text("SET LOCAL ROLE privacy_test_app"))
        with pytest.raises(DBAPIError):
            await db.execute(
                text("SELECT privacy_private.execute_stage(:id)"), {"id": uuid4()}
            )
        await db.rollback()
        await db.execute(text("SET LOCAL ROLE privacy_test_app"))
        await db.execute(
            text("SELECT set_config('csms.privacy_job',:id,true)"), {"id": str(uuid4())}
        )
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text("UPDATE invoices SET total_vnd=total_vnd+1"))
        await db.rollback()


@pytest.mark.parametrize("balance", [1000000, -5000])
async def test_approved_request_cannot_execute_with_unresolved_wallet(balance):
    uid, admin = await seed(balance)
    async with SessionFactory() as db:
        service = PrivacyRetentionService(db)
        receipt = await service.create_request(
            uid, "privacy-test-password", "Original AC"
        )
        await service.review_request(
            receipt.id,
            PrivacyDecision(
                decision="approved", reason="Reviewed request", policy_version=VERSION
            ),
            admin,
            AuthorizationEvidence(permission="admin.privacy.manage", roles=("admin",)),
        )
        job = await db.scalar(
            select(PrivacyJob).where(PrivacyJob.request_id == receipt.id)
        )
        job_id = job.id
    engine = create_async_engine(settings.database_url)
    try:
        with pytest.raises(DBAPIError, match="wallet_refund_or_debt_required"):
            await execute_job(engine, job_id)
    finally:
        await engine.dispose()
    async with SessionFactory() as db:
        assert (
            await db.scalar(
                text("SELECT status FROM users WHERE id=:uid"), {"uid": uid}
            )
            == "active"
        )
        assert (
            await db.scalar(
                text("SELECT balance_vnd FROM wallets WHERE driver_id=:uid"),
                {"uid": uid},
            )
            == balance
        )
        job = await db.get(PrivacyJob, job_id)
        assert job.status == "needs_review" and job.checkpoint == 0
        assert job.last_error == "wallet_refund_or_debt_required"


async def test_production_worker_executes_the_job_created_by_approval(monkeypatch):
    uid, _, job_id, _ = await prepared_job()
    monkeypatch.setattr(settings, "privacy_worker_enabled", True)
    monkeypatch.setattr(settings, "privacy_worker_interval_seconds", 1)
    task = asyncio.create_task(privacy_execution_loop())
    try:
        async with asyncio.timeout(10):
            while True:
                async with SessionFactory() as db:
                    job = await db.get(PrivacyJob, job_id)
                    if job.status == "completed":
                        assert (
                            await db.scalar(
                                text("SELECT status FROM users WHERE id=:uid"),
                                {"uid": uid},
                            )
                            == "anonymized"
                        )
                        break
                await asyncio.sleep(0.05)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
