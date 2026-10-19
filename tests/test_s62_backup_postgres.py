"""Opt-in acceptance: disposable migrated PostgreSQL 16 plus backup runtime image.

See docs/S62_BACKUP_RUNBOOK.md for setup. Never point this test at staging.
"""

import os
import subprocess
from pathlib import Path

import psycopg
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.modules.charging.driver_router import owned_session
from src.modules.wallet.models import Wallet, WalletLedger
from src.platform.database.session import SessionFactory

pytestmark = pytest.mark.skipif(
    os.getenv("S62_ACCEPTANCE_CONTAINER") != "csms-s62-review-db",
    reason="requires explicitly provisioned disposable S62 databases and Docker image",
)


def snapshot(url):
    from psycopg import sql

    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as db:
        tables = db.execute(
            "SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('public','privacy_private') ORDER BY 1,2"
        ).fetchall()
        result = {}
        for schema, table in tables:
            rows = db.execute(
                sql.SQL(
                    "SELECT row_to_json(t)::text FROM {}.{} t ORDER BY row_to_json(t)::text"
                ).format(sql.Identifier(schema), sql.Identifier(table))
            ).fetchall()
            result[f"{schema}.{table}"] = rows
        sequences = db.execute(
            "SELECT schemaname, sequencename, last_value FROM pg_sequences WHERE schemaname='public' ORDER BY 1,2"
        ).fetchall()
        result["sequences"] = sequences
        return result


async def test_real_migrated_backup_restore_and_application_read(tmp_path: Path):
    from src.entrypoints.http import app
    from tests.test_t82_driver_invoice import sample

    source_url = os.environ["DATABASE_URL"]
    target_url = os.environ["S62_ACCEPTANCE_TARGET_URL"]
    assert source_url.endswith("/s62_source") and target_url.endswith("/s62_restore")
    async with SessionFactory() as db:
        charging, driver = await sample(db)
        wallet = await db.scalar(select(Wallet).where(Wallet.driver_id == driver.id))
        assert wallet is not None
        wallet.balance_vnd = 46500
        await db.flush()
        db.add(
            WalletLedger(
                wallet_id=wallet.id,
                entry_type="charging_debit",
                amount_vnd=-3500,
                balance_after_vnd=46500,
                reference_type="charging_session",
                reference_id=str(charging.id),
            )
        )
        await db.commit()
        charging_id = charging.id
        expected = await owned_session(db, charging)
    app.dependency_overrides.clear()
    before = snapshot(source_url)
    root = tmp_path.resolve()
    (root / "backups").mkdir()
    (root / "mirror").mkdir()
    (root / "key").write_bytes(Fernet.generate_key())
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        "csms-s62-review",
        "--mount",
        f"type=bind,src={root},dst=/acceptance",
        "-e",
        "S62_BACKUP_DIR=/acceptance/backups",
        "-e",
        "S62_MIRROR_DIR=/acceptance/mirror",
        "-e",
        "S62_BACKUP_KEY_FILE=/acceptance/key",
        "-e",
        "DATABASE_URL=postgresql://postgres@csms-s62-review-db/s62_source",
        "-e",
        "S62_RESTORE_DATABASE_URL=postgresql://postgres@csms-s62-review-db/s62_restore",
        "csms-s62-backup:review",
    ]

    def run(*command):
        return subprocess.run(
            [*args, *command], capture_output=True, timeout=120, check=False
        )

    backup = run("backup")
    assert backup.returncode == 0, backup.stderr.decode()
    archive = next((root / "backups").glob("*.dump.enc"))
    assert (root / "mirror" / archive.name).read_bytes() == archive.read_bytes()
    restored = run("restore", f"/acceptance/mirror/{archive.name}")
    assert restored.returncode == 0, restored.stderr.decode()
    assert snapshot(target_url) == before
    assert snapshot(source_url) == before
    target_engine = create_async_engine(target_url)
    try:
        from src.modules.charging.models import ChargingSession

        async with AsyncSession(target_engine) as db:
            charging = await db.get(ChargingSession, charging_id)
            actual = await owned_session(db, charging)
            assert actual == expected
    finally:
        await target_engine.dispose()
    # Retry into populated target must fail without modifying restored data.
    assert run("restore", f"/acceptance/mirror/{archive.name}").returncode != 0
    assert snapshot(target_url) == before
    print(
        f"S62 acceptance: {len(before) - 1} tables, sequences, wallet/ledger/invoice, application read, empty-target guard passed; encrypted_bytes={archive.stat().st_size}"
    )
