import asyncio
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.modules.billing.models import Invoice, InvoiceLine
from src.modules.charging.models import ChargingSession
from tests.test_charging_sessions import setup, start
from tests.test_effective_tariffs import committed_tariff_db as invoice_database
from tests.test_ocpp_control import db_session as isolated_session
from tests.test_tariff_schema import make_tariff

db_session = isolated_session
committed_invoice_db = invoice_database


async def invoice_fixture(session):
    station, _, _, driver, _, conn, tag = await setup(session)
    reply = await start(session, conn, tag)
    charging = await session.get(ChargingSession, reply.payload["transactionId"])
    invoice = Invoice(
        session_id=charging.id,
        driver_id=driver.id,
        station_id=station.id,
        total_vnd=5_000_000_001,
        rounding_rule="Round each line to dong, then sum",
    )
    session.add(invoice)
    await session.flush()
    tariff = await make_tariff(session)
    # Use a version belonging to the same station for a valid future T-80 snapshot.
    tariff.station_id = station.id
    await session.flush()
    line = InvoiceLine(
        invoice_id=invoice.id,
        line_type="energy",
        local_date=date(2026, 10, 7),
        started_at=datetime(2026, 10, 7, 12, tzinfo=UTC),
        ended_at=datetime(2026, 10, 7, 13, tzinfo=UTC),
        energy_wh=Decimal("1234.567891"),
        rate_vnd=5_000_000_001,
        band_label="Snapshot",
        interpolated=True,
        tariff_id=tariff.id,
        amount_vnd=5_000_000_001,
    )
    session.add(line)
    await session.flush()
    return charging, invoice, line


async def test_snapshot_bigint_decimal_and_unsettled_defaults(db_session):
    charging, invoice, line = await invoice_fixture(db_session)
    assert (
        charging.settlement_completed_at is None and charging.settlement_reason is None
    )
    assert line.energy_wh == Decimal("1234.567891")
    assert invoice.total_vnd == line.amount_vnd == line.rate_vnd == 5_000_000_001
    assert invoice.created_at.tzinfo is not None
    line_id = line.id
    db_session.expire_all()
    saved = await db_session.get(InvoiceLine, line_id)
    assert saved.band_label == "Snapshot" and saved.interpolated


async def test_one_invoice_per_session_but_multiple_energy_lines(db_session):
    _, invoice, line = await invoice_fixture(db_session)
    db_session.add(
        InvoiceLine(
            invoice_id=invoice.id,
            line_type="energy",
            local_date=line.local_date,
            started_at=line.ended_at,
            ended_at=line.ended_at + timedelta(hours=1),
            energy_wh=0,
            rate_vnd=0,
            band_label="Free",
            interpolated=False,
            tariff_id=line.tariff_id,
            amount_vnd=0,
        )
    )
    await db_session.flush()
    with pytest.raises(IntegrityError, match="uq_invoices_session"):
        async with db_session.begin_nested():
            db_session.add(
                Invoice(
                    session_id=invoice.session_id,
                    driver_id=invoice.driver_id,
                    station_id=invoice.station_id,
                    total_vnd=0,
                    rounding_rule="Zero",
                )
            )
            await db_session.flush()


@pytest.mark.parametrize("reason", ["debited", "zero_invoice", "legacy_exempt"])
async def test_settlement_valid_pairs(db_session, reason):
    charging, _, _ = await invoice_fixture(db_session)
    charging.settlement_reason = reason
    charging.settlement_completed_at = datetime.now(UTC)
    await db_session.flush()


@pytest.mark.parametrize(
    "stamp,reason",
    [(None, "debited"), (True, None), (True, "unknown"), (None, "unknown")],
)
async def test_settlement_invalid_pairs(db_session, stamp, reason):
    charging, _, _ = await invoice_fixture(db_session)
    with pytest.raises(IntegrityError, match="ck_charging_sessions_settlement"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE charging_sessions SET settlement_completed_at=:stamp, settlement_reason=:reason WHERE id=:id"
                ),
                {
                    "stamp": datetime.now(UTC) if stamp else None,
                    "reason": reason,
                    "id": charging.id,
                },
            )


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("invoices", "total_vnd", -1),
        ("invoices", "rounding_rule", " "),
        ("invoice_lines", "line_type", "wrong"),
        ("invoice_lines", "energy_wh", -1),
        ("invoice_lines", "rate_vnd", -1),
        ("invoice_lines", "amount_vnd", -1),
        ("invoice_lines", "band_label", " "),
        ("invoice_lines", "tariff_id", uuid4()),
    ],
)
async def test_constraints_on_direct_insert(db_session, table, column, value):
    _, invoice, line = await invoice_fixture(db_session)
    model = Invoice if table == "invoices" else InvoiceLine
    source = invoice if model is Invoice else line
    values = {c.name: getattr(source, c.name) for c in model.__table__.columns}
    values["id"] = uuid4()
    values[column] = value
    constraint = {
        "total_vnd": "ck_invoices_total",
        "rounding_rule": "ck_invoices_rounding_rule",
        "line_type": "ck_invoice_lines_type",
        "energy_wh": "ck_invoice_lines_nonnegative",
        "rate_vnd": "ck_invoice_lines_nonnegative",
        "amount_vnd": "ck_invoice_lines_nonnegative",
        "band_label": "ck_invoice_lines_label",
        "tariff_id": "foreign key",
    }[column]
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await db_session.execute(model.__table__.insert().values(**values))


@pytest.mark.parametrize("invalid", ["interval", "idle_energy"])
async def test_line_interval_and_idle_energy(db_session, invalid):
    _, _, line = await invoice_fixture(db_session)
    values = {c.name: getattr(line, c.name) for c in InvoiceLine.__table__.columns}
    values["id"] = uuid4()
    if invalid == "interval":
        values["ended_at"] = values["started_at"]
    else:
        values["line_type"] = "idle"
    with pytest.raises(IntegrityError, match="ck_invoice_lines_"):
        async with db_session.begin_nested():
            await db_session.execute(InvoiceLine.__table__.insert().values(**values))


@pytest.mark.parametrize(
    "table,column",
    [
        ("charging_sessions", "id"),
        ("users", "id"),
        ("stations", "id"),
        ("tariffs", "id"),
    ],
)
async def test_referenced_entities_cannot_be_deleted(db_session, table, column):
    _, invoice, line = await invoice_fixture(db_session)
    target = {
        "charging_sessions": invoice.session_id,
        "users": invoice.driver_id,
        "stations": invoice.station_id,
        "tariffs": line.tariff_id,
    }[table]
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(f"DELETE FROM {table} WHERE {column}=:id"), {"id": target}
            )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE invoices SET total_vnd=0",
        "DELETE FROM invoices",
        "TRUNCATE invoices CASCADE",
        "UPDATE invoice_lines SET amount_vnd=0",
        "DELETE FROM invoice_lines",
        "TRUNCATE invoice_lines",
        "TRUNCATE charging_sessions CASCADE",
    ],
)
async def test_owner_mutations_blocked(db_session, statement):
    await invoice_fixture(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


async def test_runtime_grants_allow_read_insert_only(db_session):
    _, invoice, line = await invoice_fixture(db_session)
    station, _, _, driver, _, conn, tag = await setup(db_session)
    reply = await start(db_session, conn, tag)
    new_invoice = {
        "id": uuid4(),
        "session_id": reply.payload["transactionId"],
        "driver_id": driver.id,
        "station_id": station.id,
        "total_vnd": 0,
        "rounding_rule": "Zero invoice",
    }
    role = "invoice_test_" + uuid4().hex
    await db_session.execute(
        text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOINHERIT')
    )
    script = Path("scripts/grant_invoice_evidence.sql").read_text()
    for stmt in (
        "\n".join(s for s in script.splitlines() if not s.startswith(("--", "\\")))
        .replace(':"app_role"', f'"{role}"')
        .split(";")
    ):
        if stmt.strip() and stmt.strip() not in ("BEGIN", "COMMIT"):
            await db_session.execute(text(stmt))
    await db_session.execute(text(f'SET LOCAL ROLE "{role}"'))
    await db_session.execute(Invoice.__table__.insert().values(**new_invoice))
    assert (
        await db_session.scalar(
            select(Invoice.total_vnd).where(Invoice.id == new_invoice["id"])
        )
        == 0
    )
    assert (
        await db_session.scalar(
            select(Invoice.total_vnd).where(Invoice.id == invoice.id)
        )
        == 5_000_000_001
    )
    values = {c.name: getattr(line, c.name) for c in InvoiceLine.__table__.columns}
    values["id"] = uuid4()
    await db_session.execute(InvoiceLine.__table__.insert().values(**values))
    for table in ("invoices", "invoice_lines"):
        for verb in ("UPDATE", "DELETE", "TRUNCATE"):
            stmt = (
                f"UPDATE {table} SET id=id"
                if verb == "UPDATE"
                else f"DELETE FROM {table}"
                if verb == "DELETE"
                else f"TRUNCATE {table} CASCADE"
            )
            with pytest.raises(DBAPIError):
                async with db_session.begin_nested():
                    await db_session.execute(text(stmt))
    await db_session.execute(text("RESET ROLE"))


async def test_migration_round_trip_keeps_existing_session(committed_invoice_db):
    factory = committed_invoice_db
    async with factory() as session:
        charging, _, _ = await invoice_fixture(session)
        session_id = charging.id
        await session.commit()
    env = os.environ | {
        "DATABASE_URL": factory.kw["bind"].url.render_as_string(hide_password=False)
    }
    for command in [("downgrade", "c100011a2026"), ("upgrade", "head")]:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", *command],
            env=env,
            check=True,
            capture_output=True,
        )
    async with factory() as session:
        charging = await session.get(ChargingSession, session_id)
        assert charging is not None and charging.settlement_reason is None
        assert await session.scalar(select(Invoice.id)) is None
