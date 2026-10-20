import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.modules.accounting.models import ReconciliationRun
from src.modules.accounting.period_closing import (
    PeriodClosingError,
    _serialize_revenue_share,
    _validate_reconciliation_run,
    close_period,
    month_date_range,
    reopen_period,
)
from src.modules.accounting.period_models import (
    PeriodClose,
    PeriodRevision,
    PeriodSnapshot,
)
from src.modules.accounting.revenue_share import RevenueShareDay


@pytest_asyncio.fixture
async def period_migration_db() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = make_url(os.environ["DATABASE_URL"])
    database = f"s55_{uuid4().hex}"
    admin_url = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(
        admin_url.render_as_string(hide_password=False), autocommit=True
    ) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
        )

    test_url = url.set(database=database).render_as_string(hide_password=False)
    engine = create_async_engine(test_url)
    try:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=os.environ | {"DATABASE_URL": test_url},
            check=True,
            capture_output=True,
        )
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )


async def _run_migration(test_url: str, *args: str) -> None:
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "alembic", *args],
        env=os.environ | {"DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )


def _reconciliation_run(period_start: date, period_end: date) -> ReconciliationRun:
    return ReconciliationRun(
        period_type="month",
        date_from=period_start,
        date_to=period_end,
        station_id=None,
        cutoff_at=datetime(2026, 9, 1, tzinfo=UTC),
        status="completed",
        total_sessions=1,
        matched_sessions=1,
        mismatch_sessions=0,
        missing_data_sessions=0,
        total_meter_kwh=Decimal(1),
        total_billed_kwh=Decimal(1),
        kwh_discrepancy=Decimal(0),
        total_billed_vnd=100,
        total_recomputed_vnd=100,
        total_debited_vnd=100,
        money_discrepancy_vnd=0,
        summary_counts={"critical": 0, "warning": 0},
        algorithm_version="1.0",
        input_hash="a" * 64,
    )


def test_month_date_range_requires_calendar_month_start() -> None:
    assert month_date_range(date(2026, 8, 1)) == (
        date(2026, 8, 1),
        date(2026, 8, 31),
    )
    with pytest.raises(PeriodClosingError, match="ngày đầu tháng"):
        month_date_range(date(2026, 8, 2))


@pytest.mark.asyncio
async def test_period_migration_downgrade_upgrade_round_trip(
    period_migration_db: async_sessionmaker[AsyncSession],
) -> None:
    test_url = period_migration_db.kw["bind"].url.render_as_string(hide_password=False)

    await _run_migration(test_url, "downgrade", "n170030a2026")
    async with period_migration_db() as session:
        assert await session.scalar(text("SELECT to_regclass('period_closes')")) is None
        assert (
            await session.scalar(text("SELECT to_regclass('period_snapshots')")) is None
        )
        assert (
            await session.scalar(text("SELECT to_regclass('period_revisions')")) is None
        )

    await _run_migration(test_url, "upgrade", "head")
    async with period_migration_db() as session:
        assert (
            await session.scalar(text("SELECT to_regclass('period_closes')"))
            == "period_closes"
        )
        assert (
            await session.scalar(text("SELECT to_regclass('period_snapshots')"))
            == "period_snapshots"
        )
        assert (
            await session.scalar(text("SELECT to_regclass('period_revisions')"))
            == "period_revisions"
        )


def test_reconciliation_run_gate_requires_completed_clean_full_month() -> None:
    start, end = date(2026, 8, 1), date(2026, 8, 31)
    run = _reconciliation_run(start, end)
    _validate_reconciliation_run(run, start, end)

    run.summary_counts = {"critical": 0, "warning": 1}
    with pytest.raises(PeriodClosingError, match="warning"):
        _validate_reconciliation_run(run, start, end)


def test_revenue_snapshot_rejects_out_of_month_and_inconsistent_shares() -> None:
    valid_row = RevenueShareDay(
        station_id=uuid4(),
        local_date=date(2026, 8, 31),
        contract_id=uuid4(),
        owner_id=uuid4(),
        owner_share_bps=5000,
        energy_vnd=80,
        idle_vnd=20,
        owner_share_vnd=50,
        partner_share_vnd=50,
        unallocated_vnd=0,
    )
    assert _serialize_revenue_share([valid_row], date(2026, 8, 1), date(2026, 8, 31))

    out_of_month = replace(valid_row, local_date=date(2026, 9, 1))
    with pytest.raises(PeriodClosingError, match="ngoài tháng"):
        _serialize_revenue_share([out_of_month], date(2026, 8, 1), date(2026, 8, 31))

    inconsistent = replace(valid_row, partner_share_vnd=49)
    with pytest.raises(PeriodClosingError, match="không hợp lệ"):
        _serialize_revenue_share([inconsistent], date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.asyncio
async def test_close_reopen_and_reclose_preserve_immutable_history(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    period_start, period_end = date(2026, 8, 1), date(2026, 8, 31)
    run = _reconciliation_run(period_start, period_end)
    db_session.add(run)
    await db_session.flush()
    station_id, owner_id, contract_id = uuid4(), uuid4(), uuid4()
    share_row = RevenueShareDay(
        station_id=station_id,
        local_date=date(2026, 8, 31),
        contract_id=contract_id,
        owner_id=owner_id,
        owner_share_bps=5000,
        energy_vnd=80,
        idle_vnd=20,
        owner_share_vnd=50,
        partner_share_vnd=50,
        unallocated_vnd=0,
    )

    async def revenue_share(
        db: AsyncSession,
        *,
        date_from: date,
        date_to: date,
        station_id: UUID | None = None,
    ) -> list[RevenueShareDay]:
        assert (date_from, date_to, station_id) == (
            period_start,
            period_end,
            None,
        )
        return [share_row]

    monkeypatch.setattr(
        "src.modules.accounting.period_closing.calculate_partner_revenue_share",
        revenue_share,
    )

    first = await close_period(
        db_session,
        period_start=period_start,
        reconciliation_run_id=run.id,
    )
    first_id = first.id
    first_hash = first.snapshot_hash
    assert first.revision == 1
    assert first.payload["period"]["timezone"] == "Asia/Ho_Chi_Minh"
    assert first.payload["revenue_share"][0]["idle_vnd"] == 20
    assert len(first_hash) == 64

    reopened = await reopen_period(
        db_session,
        period_start=period_start,
        reason="Bổ sung dữ liệu đối soát muộn",
    )
    assert reopened.revision == 2
    assert reopened.previous_snapshot_id == first_id
    period = await db_session.scalar(
        select(PeriodClose).where(PeriodClose.period_start == period_start)
    )
    assert period is not None and period.status == "open" and period.revision == 2

    new_run = _reconciliation_run(period_start, period_end)
    db_session.add(new_run)
    await db_session.flush()
    second = await close_period(
        db_session,
        period_start=period_start,
        reconciliation_run_id=new_run.id,
    )
    assert second.revision == 3

    await db_session.flush()
    snapshots = list(
        (
            await db_session.scalars(
                select(PeriodSnapshot)
                .where(PeriodSnapshot.period_close_id == second.period_close_id)
                .order_by(PeriodSnapshot.revision)
            )
        ).all()
    )
    revisions = list(
        (
            await db_session.scalars(
                select(PeriodRevision)
                .where(PeriodRevision.period_close_id == second.period_close_id)
                .order_by(PeriodRevision.revision)
            )
        ).all()
    )
    assert [item.revision for item in snapshots] == [1, 3]
    assert [item.revision for item in revisions] == [2]
    assert snapshots[0].id == first_id and snapshots[0].snapshot_hash == first_hash


@pytest.mark.asyncio
async def test_close_rejects_wrong_or_unpassed_s53_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    period_start, period_end = date(2026, 8, 1), date(2026, 8, 31)
    run = _reconciliation_run(period_start, period_end)
    run.mismatch_sessions = 1
    run.matched_sessions = 0
    run.summary_counts = {"critical": 1, "warning": 0}
    db_session.add(run)
    await db_session.flush()

    async def unexpected_share(*args: object, **kwargs: object) -> None:
        pytest.fail("S-54 must not run when S-53 is not clean")

    monkeypatch.setattr(
        "src.modules.accounting.period_closing.calculate_partner_revenue_share",
        unexpected_share,
    )
    with pytest.raises(PeriodClosingError, match="sai lệch"):
        await close_period(
            db_session,
            period_start=period_start,
            reconciliation_run_id=run.id,
        )


@pytest.mark.asyncio
async def test_close_rejects_s53_cutoff_before_month_end(
    db_session: AsyncSession,
) -> None:
    period_start, period_end = date(2026, 8, 1), date(2026, 8, 31)
    run = _reconciliation_run(period_start, period_end)
    run.cutoff_at = datetime(2026, 8, 31, 12, tzinfo=UTC)
    db_session.add(run)
    await db_session.flush()
    with pytest.raises(PeriodClosingError, match="sau khi tháng"):
        await close_period(
            db_session,
            period_start=period_start,
            reconciliation_run_id=run.id,
        )


@pytest.mark.asyncio
async def test_snapshot_and_revision_are_database_immutable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    period_start, period_end = date(2026, 8, 1), date(2026, 8, 31)
    run = _reconciliation_run(period_start, period_end)
    db_session.add(run)
    await db_session.flush()

    async def empty_revenue_share(
        db: AsyncSession,
        *,
        date_from: date,
        date_to: date,
        station_id: UUID | None = None,
    ) -> list[RevenueShareDay]:
        return []

    monkeypatch.setattr(
        "src.modules.accounting.period_closing.calculate_partner_revenue_share",
        empty_revenue_share,
    )
    snapshot = await close_period(
        db_session,
        period_start=period_start,
        reconciliation_run_id=run.id,
    )
    revision = await reopen_period(
        db_session,
        period_start=period_start,
        reason="Kiểm tra bất biến",
    )
    await db_session.flush()

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE period_snapshots SET snapshot_hash=:value WHERE id=:id"),
                {"value": "b" * 64, "id": snapshot.id},
            )

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM period_revisions WHERE id=:id"),
                {"id": revision.id},
            )

    period = await db_session.scalar(
        select(PeriodClose).where(PeriodClose.period_start == period_start)
    )
    assert period is not None and period.status == "open"
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE period_closes SET status='closed' WHERE id=:id"),
                {"id": period.id},
            )


@pytest.mark.asyncio
async def test_reopening_requires_closed_period_and_reason(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(PeriodClosingError, match="lý do"):
        await reopen_period(
            db_session,
            period_start=date(2026, 8, 1),
            reason="   ",
        )
    with pytest.raises(PeriodClosingError, match="đang ở trạng thái"):
        await reopen_period(
            db_session,
            period_start=date(2026, 8, 1),
            reason="Không tồn tại kỳ đã chốt",
        )
