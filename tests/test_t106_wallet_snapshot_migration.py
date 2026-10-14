"""Round-trip the nullable snapshot without changing existing start history."""

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from simulator.t108_contract import new_manifest
from simulator.t108_fixture import prepare_station, user
from src.modules.charging.driver_models import DriverStartRequest
from tests.test_effective_tariffs import committed_tariff_db as isolated_db

committed_tariff_db = isolated_db


async def test_nullable_snapshot_migration_round_trip(committed_tariff_db):
    factory = committed_tariff_db
    manifest = new_manifest(
        revision="migration-test", mode="ci", count=1, duration=120, boundary=60
    )
    participant = manifest.participants[0]
    key = uuid4()
    async with factory() as db, db.begin():
        await prepare_station(db, manifest)
        await user(db, participant.driver_id, participant.driver_email, ["driver"])
        db.add(
            DriverStartRequest(
                id=key,
                driver_id=participant.driver_id,
                connector_id=participant.connector_id,
                charge_point_id=participant.charge_point_id,
                created_at=datetime.now(UTC),
                lease_until=datetime.now(UTC),
                status="Rejected",
                reply_status="Accepted",
                rejection_reason="wallet_low",
                balance_vnd=-3_000_000_000,
                minimum_balance_vnd=4_000_000_000,
            )
        )
    test_url = factory.kw["bind"].url.render_as_string(hide_password=False)
    for action, target in (("downgrade", "4db8d8987c3a"), ("upgrade", "head")):
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "alembic", action, target],
            env=os.environ | {"DATABASE_URL": test_url},
            check=True,
            capture_output=True,
        )
        async with factory() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT status,reply_status,rejection_reason FROM driver_start_requests WHERE id=:id"
                    ),
                    {"id": key},
                )
            ).one()
            assert tuple(row) == ("Rejected", "Accepted", "wallet_low")
    async with factory() as db:
        restored = await db.get(DriverStartRequest, key)
        assert restored.balance_vnd is None and restored.minimum_balance_vnd is None
