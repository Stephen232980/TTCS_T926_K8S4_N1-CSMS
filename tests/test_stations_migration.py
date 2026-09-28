import importlib

from alembic.config import Config
from alembic.script import ScriptDirectory

stations_migration = importlib.import_module(
    "migrations.versions.8f2b1d3a4c5e_tao_bang_stations"
)


def test_stations_migration_revision_chain() -> None:
    assert stations_migration.revision == "8f2b1d3a4c5e"
    assert stations_migration.down_revision == "106fd5767106"
    assert callable(stations_migration.upgrade)
    assert callable(stations_migration.downgrade)


def test_alembic_heads_resolves_to_stations_migration() -> None:
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()

    assert heads == ["8f2b1d3a4c5e"]
    rev = script.get_revision("8f2b1d3a4c5e")
    assert rev is not None
    assert rev.down_revision == "106fd5767106"
