"""Real PostgreSQL round trip preserves historical billing evidence."""

import asyncio
import os
import subprocess
import sys

from sqlalchemy import select

from src.modules.billing.invoicing import lap_hoa_don
from src.modules.charging.models import ChargingSession
from tests.test_effective_tariffs import committed_tariff_db as isolated_migration_db
from tests.test_t80_invoicing import lines, seed

committed_tariff_db = isolated_migration_db


async def test_upgrade_downgrade_upgrade_preserves_invoice_and_cutover_policy(
    committed_tariff_db,
):
    factory = committed_tariff_db
    async with factory() as db, db.begin():
        historical, *_ = await seed(db)
        result = await lap_hoa_don(db, historical.id)
        invoice_id, session_id = result.invoice.id, historical.id
        before = [
            (x.id, x.amount_vnd, x.started_at, x.ended_at)
            for x in await lines(db, result.invoice)
        ]
        pending, *_ = await seed(db)
        pending.billing_lifecycle_version = 1
        pending_id = pending.id
    url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for direction, revision in [("downgrade", "c160016a2026"), ("upgrade", "head")]:
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", direction, revision],
            env=os.environ | {"DATABASE_URL": url},
            check=True,
            capture_output=True,
            timeout=60,
        )
    async with factory() as db, db.begin():
        for identifier in (session_id, pending_id):
            stored = await db.get(ChargingSession, identifier)
            assert stored.billing_lifecycle_version == 0
            assert stored.connector_released_at is None
        existing = await lap_hoa_don(db, session_id)
        assert existing.invoice.id == invoice_id and existing.invoice.total_vnd == 3000
        assert [
            (x.id, x.amount_vnd, x.started_at, x.ended_at)
            for x in await lines(db, existing.invoice)
        ] == before
        # Omitting the policy field on a new persisted row uses version 1.
        newer = ChargingSession(
            charge_point_id=historical.charge_point_id,
            connector_id=historical.connector_id,
            tag_tail="NEW",
            authorization_status="Accepted",
            started_at=historical.ended_at,
            meter_start_wh=1000,
        )
        db.add(newer)
        await db.flush()
        assert (
            await db.scalar(
                select(ChargingSession.billing_lifecycle_version).where(
                    ChargingSession.id == newer.id
                )
            )
            == 1
        )
