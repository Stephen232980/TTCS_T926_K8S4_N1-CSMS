"""Committed PostgreSQL recovery and post-reply T-81 integration."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.modules.billing import closure
from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from src.modules.ocpp import dispatcher, transport
from src.modules.wallet.models import WalletLedger
from tests.test_effective_tariffs import committed_tariff_db as isolated_closure_db
from tests.test_ocpp_foundation import connection
from tests.test_t80_invoicing import STAMP, seed

committed_tariff_db = isolated_closure_db


@pytest.fixture
async def factory(committed_tariff_db, monkeypatch):
    monkeypatch.setattr(closure, "SessionFactory", committed_tariff_db)
    monkeypatch.setattr(dispatcher, "SessionFactory", committed_tariff_db)
    return committed_tariff_db


async def saved(factory, **kwargs):
    async with factory() as db, db.begin():
        charging, *_ = await seed(db, **kwargs)
        return charging.id


async def counts(factory):
    async with factory() as db:
        return tuple(
            [
                await db.scalar(select(func.count()).select_from(model))
                for model in (Invoice, InvoiceLine, WalletLedger)
            ]
        )


async def test_closure_commits_once_and_does_not_settle(factory):
    session_id = await saved(factory)
    outcomes = await asyncio.gather(*(closure.chot_phien(session_id) for _ in range(4)))
    assert {result.invoice.id for result in outcomes} == {outcomes[0].invoice.id}
    assert await counts(factory) == (1, 1, 0)
    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.settlement_completed_at is None
        assert charging.settlement_reason is None


async def test_scan_pages_existing_invoices_manual_sessions_and_exclusions(factory):
    ids = [await saved(factory) for _ in range(5)]
    await closure.chot_phien(ids[0])
    async with factory() as db, db.begin():
        manual = await db.get(ChargingSession, ids[1])
        manual.manual_closed_at = STAMP + timedelta(hours=1)
        opened = await db.get(ChargingSession, ids[3])
        opened.ended_at = None
        settled = await db.get(ChargingSession, ids[4])
        settled.settlement_completed_at = STAMP + timedelta(hours=1)
        settled.settlement_reason = "legacy_exempt"
    for _ in range(2):
        result = await closure.scan_unsettled_sessions(batch_size=1)
        assert (result.scanned, result.ready, result.failed) == (3, 3, 0)
    assert await counts(factory) == (3, 3, 0)


async def test_scan_skips_locked_then_recovers(factory):
    session_id = await saved(factory)
    async with factory() as db, db.begin():
        await db.scalar(
            select(ChargingSession.id)
            .where(ChargingSession.id == session_id)
            .with_for_update()
        )
        result = await asyncio.wait_for(closure.scan_unsettled_sessions(), 2)
        assert (result.scanned, result.busy, result.ready) == (1, 1, 0)
    assert (await closure.scan_unsettled_sessions()).ready == 1


async def test_two_scans_and_direct_closure_share_one_invoice(factory):
    session_id = await saved(factory)
    await asyncio.gather(
        closure.scan_unsettled_sessions(),
        closure.scan_unsettled_sessions(),
        closure.chot_phien(session_id),
    )
    assert await counts(factory) == (1, 1, 0)


async def test_review_reason_is_committed_and_not_false_success(factory):
    session_id = await saved(factory, with_tariff=False)
    result = await closure.scan_unsettled_sessions()
    assert (result.needs_review, result.ready) == (1, 0)
    async with factory() as db:
        charging = await db.get(ChargingSession, session_id)
        assert charging.review_reasons
        assert charging.settlement_completed_at is None
    assert await counts(factory) == (0, 0, 0)


async def test_failure_rolls_back_invoice_and_scan_continues(factory, monkeypatch):
    first = await saved(factory)
    await saved(factory)
    original = closure.lap_hoa_don

    async def fail(db, session_id):
        outcome = await original(db, session_id)
        if session_id == first:
            raise SQLAlchemyError("injected after invoice flush")
        return outcome

    monkeypatch.setattr(closure, "lap_hoa_don", fail)
    result = await closure.scan_unsettled_sessions()
    assert (result.failed, result.ready) == (1, 1)
    assert await counts(factory) == (1, 1, 0)
    monkeypatch.setattr(closure, "lap_hoa_don", original)
    assert (await closure.scan_unsettled_sessions()).ready == 2
    assert await counts(factory) == (2, 2, 0)


async def stop_fixture(factory):
    session_id = await saved(factory)
    async with factory() as db, db.begin():
        charging = await db.get(ChargingSession, session_id)
        charging.ended_at = None
        charging.meter_stop_wh = None
        conn = connection(charging.charge_point_id)
        conn.boot_accepted = True
    raw = json.dumps(
        [
            2,
            "t81-stop",
            "StopTransaction",
            {
                "transactionId": session_id,
                "meterStop": 1000,
                "timestamp": (STAMP + timedelta(hours=1)).isoformat(),
                "reason": "Local",
            },
        ]
    )
    return session_id, conn, raw


async def test_real_stop_commit_and_reply_precede_slow_invoice(factory, monkeypatch):
    session_id, conn, raw = await stop_fixture(factory)
    sent = []

    async def send(reply):
        async with factory() as db:
            assert (await db.get(ChargingSession, session_id)).ended_at is not None
            assert await db.scalar(select(Invoice.id)) is None
        sent.append(json.loads(reply))

    conn.websocket.send_text = send
    runner = closure.ClosureRunner()
    monkeypatch.setattr(closure, "_runner", runner)
    entered, release = asyncio.Event(), asyncio.Event()
    original = closure.chot_phien

    async def delayed(session_id):
        entered.set()
        await release.wait()
        return await original(session_id)

    monkeypatch.setattr(closure, "chot_phien", delayed)
    worker = asyncio.create_task(runner.worker())
    try:
        await asyncio.wait_for(transport.handle_message(conn, raw), 2)
        await asyncio.wait_for(entered.wait(), 1)
        assert sent[0][0] == 3 and not release.is_set()
        assert await counts(factory) == (0, 0, 0)
        release.set()
        await asyncio.wait_for(runner.queue.join(), 2)
        conn.websocket.send_text = AsyncMock()
        await transport.handle_message(conn, raw)
        await asyncio.wait_for(runner.queue.join(), 2)
        assert await counts(factory) == (1, 1, 0)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("send_failure", [False, True])
async def test_restart_scan_recovers_stop_without_queue(
    factory, monkeypatch, send_failure
):
    _session_id, conn, raw = await stop_fixture(factory)
    monkeypatch.setattr(closure, "_runner", None)
    conn.websocket.send_text = AsyncMock(
        side_effect=ConnectionError() if send_failure else None
    )
    if send_failure:
        with pytest.raises(ConnectionError):
            await transport.handle_message(conn, raw)
    else:
        await transport.handle_message(conn, raw)
    assert await counts(factory) == (0, 0, 0)
    assert (await closure.scan_unsettled_sessions()).ready == 1
    assert await counts(factory) == (1, 1, 0)


@pytest.mark.parametrize("database_error", [False, True])
async def test_failed_stop_reply_does_not_schedule(
    factory, monkeypatch, database_error
):
    _, conn, raw = await stop_fixture(factory)
    if database_error:
        monkeypatch.setattr(
            transport, "dispatch_call", AsyncMock(side_effect=SQLAlchemyError())
        )
    else:
        payload = json.loads(raw)
        payload[3].pop("meterStop")
        raw = json.dumps(payload)
    schedule = AsyncMock()
    monkeypatch.setattr(transport, "schedule_closure", schedule)
    await transport.handle_message(conn, raw)
    schedule.assert_not_called()
    assert await counts(factory) == (0, 0, 0)


async def test_bounded_queue_coalesces_and_worker_survives_failure(monkeypatch):
    runner = closure.ClosureRunner(capacity=1)
    assert runner.schedule(1) and runner.schedule(1)
    assert not runner.schedule(2)
    close = AsyncMock(side_effect=[RuntimeError("injected"), None])
    monkeypatch.setattr(closure, "chot_phien", close)
    worker = asyncio.create_task(runner.worker())
    try:
        await asyncio.wait_for(runner.queue.join(), 1)
        assert runner.schedule(2)
        await asyncio.wait_for(runner.queue.join(), 1)
        assert close.await_count == 2 and not runner.pending
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_lifespan_starts_recovery_and_cancels_workers(monkeypatch):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def scan():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(closure, "closure_scan_loop", scan)
    async with closure.closure_lifespan():
        await asyncio.wait_for(entered.wait(), 1)
        assert closure.schedule_closure(1)
    assert cancelled.is_set() and not closure.schedule_closure(1)


async def test_recovery_runs_immediately_and_retries_each_minute(monkeypatch):
    scan = AsyncMock(side_effect=[SQLAlchemyError(), closure.ScanResult()])
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(closure, "scan_unsettled_sessions", scan)
    monkeypatch.setattr(closure.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await closure.closure_scan_loop()
    assert scan.await_count == 2 and waits == [60, 60]


async def test_scan_rejects_invalid_batch_size():
    with pytest.raises(ValueError):
        await closure.scan_unsettled_sessions(batch_size=0)
