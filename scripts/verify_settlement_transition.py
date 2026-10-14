"""Reject first T-102 deployment until writers are stopped and cutoff is approved."""

import argparse
from datetime import UTC, datetime

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from src.config import settings


def check_transition(connection, *, cutoff: str, runtime_running: bool) -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    versions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    applied = any(
        revision.revision == "4db8d8987c3a"
        for (version,) in versions
        for revision in scripts.iterate_revisions(version, "base")
    )
    if applied:
        return
    if runtime_running:
        raise ValueError(
            "First T-102 transition requires stopped backend and invoice writers"
        )
    if not cutoff.strip():
        raise ValueError("First T-102 transition requires an approved UTC cutoff")
    stamp = datetime.fromisoformat(cutoff)
    if stamp.tzinfo is None:
        raise ValueError("T-102 cutoff must include timezone")
    if stamp.astimezone(UTC) > datetime.now(UTC):
        raise ValueError("T-102 cutoff cannot be in the future")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-running", choices=("true", "false"), required=True)
    args = parser.parse_args()
    url = make_url(settings.database_url).set(drivername="postgresql")
    try:
        with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
            check_transition(
                connection,
                cutoff=settings.legacy_settlement_cutoff,
                runtime_running=args.runtime_running == "true",
            )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except psycopg.Error:
        raise SystemExit("T-102 preflight database check failed") from None
    print("T-102 transition preflight passed")


if __name__ == "__main__":
    main()
