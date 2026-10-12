"""Real OCPP/DB runner regression; test settlement fixtures are not staging evidence."""

import asyncio
import socket
import sys
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import uvicorn
from sqlalchemy import select

from scripts.t108_staging import execute
from simulator.t108_contract import new_manifest, save_json
from simulator.t108_fixture import cleanup_manifest, seed_manifest, user
from src.entrypoints.http import app
from src.modules.billing.invoicing import lap_hoa_don
from src.modules.charging.models import ChargingSession
from src.modules.wallet.service import tru_vi
from src.platform.database.session import SessionFactory
from tests.test_effective_tariffs import committed_tariff_db as isolated_ocpp_db

committed_tariff_db = isolated_ocpp_db


@pytest.mark.asyncio
async def test_twenty_real_sockets_replay_and_verifier_reject_missing_settlement(
    committed_tariff_db, monkeypatch, tmp_path
):
    factory = committed_tariff_db
    # Every production OCPP/worker read must use the disposable test database.
    for name, module in tuple(sys.modules.items()):
        if (
            name.startswith("src.")
            and getattr(module, "SessionFactory", None) is SessionFactory
        ):
            monkeypatch.setattr(module, "SessionFactory", factory)
    run = new_manifest(
        revision="test-harness", mode="ci", count=20, duration=120, boundary=60
    )
    async with factory() as db, db.begin():
        await user(db, uuid4(), "t108-ocpp-admin@example.com", ["admin"])
        assert await seed_manifest(db, run, "t108-ocpp-admin@example.com") == 20
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", ws="websockets-sansio")
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.05)
        first = await execute(
            run, f"ws://127.0.0.1:{port}", tmp_path, factory, timeout=2
        )
        save_json(tmp_path / "dependency-state.json", first)
        assert all(row["actual"].get("total_vnd") == 5000 for row in first["rows"])
        assert all(row["actual"]["invoice_count"] == 1 for row in first["rows"])
        if not first["passed"]:
            assert all("settlement_missing" in row["failures"] for row in first["rows"])
            with pytest.raises(ValueError, match="unsettled"):
                async with factory() as db, db.begin():
                    await cleanup_manifest(db, run)
            # Test-only settled fixture exercises the positive verifier path.
            # Never called by the CLI; T-102 must provide runtime settlement.
            async with factory() as db, db.begin():
                for participant in run.participants:
                    charging = await db.scalar(
                        select(ChargingSession).where(
                            ChargingSession.charge_point_id
                            == participant.charge_point_id
                        )
                    )
                    outcome = await lap_hoa_don(db, charging.id)
                    await tru_vi(db, invoice=outcome.invoice)
                    charging.settlement_completed_at = datetime.now(UTC)
                    charging.settlement_reason = "debited"
        replay = await execute(
            run, f"ws://127.0.0.1:{port}", tmp_path, factory, timeout=2
        )
        assert replay["passed"]
        assert all(
            row["actual"]["sessions"] == first["rows"][i]["actual"]["sessions"]
            for i, row in enumerate(replay["rows"])
        )
        assert all(row["actual"]["debit_amounts"] == [-5000] for row in replay["rows"])
        assert not replay["staging_acceptance_candidate"]
        async with factory() as db, db.begin():
            await cleanup_manifest(db, run)
            await cleanup_manifest(db, run)
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
