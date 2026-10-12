"""Real OCPP/DB runner regression; test settlement fixtures are not staging evidence."""

import asyncio
import socket
import sys
from uuid import uuid4

import pytest
import uvicorn

from scripts.t108_staging import execute
from simulator.t108_contract import new_manifest, save_json
from simulator.t108_fixture import cleanup_manifest, seed_manifest, user
from src.entrypoints.http import app
from src.platform.database.session import SessionFactory
from tests.test_effective_tariffs import committed_tariff_db as isolated_ocpp_db

committed_tariff_db = isolated_ocpp_db


@pytest.mark.asyncio
async def test_twenty_real_sockets_automatically_settle_and_replay_once(
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
            run, f"ws://127.0.0.1:{port}", tmp_path, factory, timeout=15
        )
        save_json(tmp_path / "dependency-state.json", first)
        assert all(row["actual"].get("total_vnd") == 5000 for row in first["rows"])
        assert all(row["actual"]["invoice_count"] == 1 for row in first["rows"])
        assert first["passed"]
        assert all(
            row["actual"]["settlement_reason"] == "debited" for row in first["rows"]
        )
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
