"""Meter history is read once without weakening normal or recovery ordering."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select

from src.modules.charging.models import MeterSample
from src.platform.database.session import engine
from tests.test_charging_recovery import reconnect
from tests.test_charging_sessions import call, meter_payload, setup, start


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recovered,explicit_id", [(False, True), (True, True), (True, False)]
)
async def test_meter_reads_once_and_only_recovery_accepts_buffered_gap(
    db_session, recovered, explicit_id
):
    station, charger, _, _, _, conn, tag = await setup(db_session)
    stamp = datetime.now(UTC) - timedelta(minutes=5)
    tid = (await start(db_session, conn, tag, stamp)).payload["transactionId"]
    await call(
        db_session,
        conn,
        "MeterValues",
        meter_payload(tid, stamp + timedelta(seconds=30), 3000),
    )
    if recovered:
        conn = await reconnect(db_session, charger, station)
    payload = meter_payload(tid, stamp + timedelta(seconds=20), 2000)
    if not explicit_id:
        payload.pop("transactionId")
    reads = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "charging_meter_samples" in statement
        ):
            reads.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert (await call(db_session, conn, "MeterValues", payload)).kind == 3
        assert len(reads) == 1
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    values = (
        await db_session.scalars(
            select(MeterSample.value)
            .where(MeterSample.session_id == tid)
            .order_by(MeterSample.timestamp)
        )
    ).all()
    assert values == (
        [Decimal(2000), Decimal(3000)] if recovered and explicit_id else [Decimal(3000)]
    )
