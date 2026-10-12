"""Preflight reads real revision state without writing financial data."""

import psycopg
import pytest

from scripts.verify_settlement_transition import check_transition
from tests.test_effective_tariffs import committed_tariff_db as isolated_db

committed_tariff_db = isolated_db


@pytest.mark.parametrize(
    "running,cutoff,allowed",
    [
        (True, "2000-01-01T00:00:00+00:00", False),
        (False, "", False),
        (False, "2000-01-01T00:00:00", False),
        (False, "2999-01-01T00:00:00+00:00", False),
        (False, "2000-01-01T00:00:00+00:00", True),
    ],
)
async def test_first_transition_preflight(
    committed_tariff_db, running, cutoff, allowed
):
    async with committed_tariff_db() as db:
        url = db.bind.url.set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
        # Dedicated fixture DB only. Model state prior to first T-102 migration.
        connection.execute("UPDATE alembic_version SET version_num='d180018a2026'")
        if allowed:
            check_transition(connection, cutoff=cutoff, runtime_running=running)
        else:
            with pytest.raises(ValueError):
                check_transition(connection, cutoff=cutoff, runtime_running=running)
        assert connection.execute("SELECT count(*) FROM invoices").fetchone()[0] == 0
        connection.rollback()


async def test_later_deploy_needs_no_maintenance(committed_tariff_db):
    async with committed_tariff_db() as db:
        url = db.bind.url.set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
        check_transition(connection, cutoff="", runtime_running=True)
