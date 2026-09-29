from alembic.config import Config
from alembic.script import ScriptDirectory


def _get_stations_migration():
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    rev = script.get_revision("8f2b1d3a4c5e")
    assert rev is not None, (
        "Revision 8f2b1d3a4c5e not found in Alembic script directory"
    )
    return rev, rev.module


def test_stations_migration_revision_chain() -> None:
    rev, stations_migration = _get_stations_migration()
    assert rev.revision == "8f2b1d3a4c5e"
    assert rev.down_revision == "106fd5767106"
    assert callable(stations_migration.upgrade)
    assert callable(stations_migration.downgrade)


def test_alembic_revision_exists_in_script_directory() -> None:
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    rev = script.get_revision("8f2b1d3a4c5e")

    assert rev is not None
    assert rev.down_revision == "106fd5767106"
