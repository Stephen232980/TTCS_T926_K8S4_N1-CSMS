"""Durability and parameter isolation for cached MeterValues writes."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from src.modules.charging.models import ChargingSession, MeterSample
from src.modules.identity.models import User
from src.modules.ocpp.dispatcher import (
    dispatch_call,
    meter_reply_statement,
    process_call,
)
from src.modules.ocpp.frames import Frame
from src.modules.ocpp.models import OcppMessageReply
from src.modules.stations.models import ChargePoint, Connector, Station
from src.platform.database.session import SessionFactory
from tests.test_ocpp_foundation import charger_fixture, connection


def test_small_report_statement_is_compilation_cacheable():
    statement = meter_reply_statement(4)
    assert statement is meter_reply_statement(4)
    assert statement._generate_cache_key() is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_count", [1, 4, 16, 17])
async def test_meter_write_replay_and_rollback_preserve_exact_samples(sample_count):
    async with SessionFactory() as session, session.begin():
        station, charger = await charger_fixture(session)
        station_id, charger_id, owner_id = station.id, charger.id, station.owner_id
        connector = Connector(charge_point_id=charger_id, connector_number=1)
        session.add(connector)
        await session.flush()
        stamp = datetime.now(UTC) - timedelta(minutes=5)
        transaction = ChargingSession(
            charge_point_id=charger_id,
            connector_id=connector.id,
            tag_tail="TEST",
            authorization_status="Invalid",
            started_at=stamp,
            meter_start_wh=Decimal(1000),
            review_reasons=[],
        )
        session.add(transaction)
        await session.flush()
        transaction_id = transaction.id

    def frame(offset):
        return Frame(
            2,
            str(uuid4()),
            {
                "connectorId": 1,
                "transactionId": transaction_id,
                "meterValue": [
                    {
                        "timestamp": (
                            stamp + timedelta(seconds=offset + index)
                        ).isoformat(),
                        "sampledValue": [{"value": str(1100 + offset + index)}],
                    }
                    for index in range(sample_count)
                ],
            },
            action="MeterValues",
        )

    def admitted():
        conn = connection(charger_id, station_id)
        conn.boot_accepted = True
        return conn

    try:
        first = frame(1)
        replies = await asyncio.gather(
            *[dispatch_call(admitted(), first, record_seen=True) for _ in range(2)]
        )
        assert replies[0] == replies[1]
        second = frame(100)
        await dispatch_call(admitted(), second, record_seen=True)
        rolled_back = frame(200)
        async with SessionFactory() as session:
            await process_call(admitted(), rolled_back, session, record_seen=True)
            await session.rollback()
        # A new transaction sees only committed samples and their durable replies.
        async with SessionFactory() as session:
            values = (
                await session.scalars(
                    select(MeterSample.value)
                    .where(MeterSample.session_id == transaction_id)
                    .order_by(MeterSample.timestamp)
                )
            ).all()
            assert values == [
                Decimal(1100 + offset + index)
                for offset in (1, 100)
                for index in range(sample_count)
            ]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OcppMessageReply)
                    .where(OcppMessageReply.charge_point_id == charger_id)
                )
                == 2
            )
    finally:
        async with SessionFactory() as session, session.begin():
            await session.execute(
                delete(OcppMessageReply).where(
                    OcppMessageReply.charge_point_id == charger_id
                )
            )
            await session.execute(
                delete(ChargingSession).where(ChargingSession.id == transaction_id)
            )
            await session.execute(
                delete(Connector).where(Connector.charge_point_id == charger_id)
            )
            await session.execute(
                delete(ChargePoint).where(ChargePoint.id == charger_id)
            )
            await session.execute(delete(Station).where(Station.id == station_id))
            await session.execute(delete(User).where(User.id == owner_id))
