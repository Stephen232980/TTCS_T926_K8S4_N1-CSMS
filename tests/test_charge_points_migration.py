from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def _get_charge_points_migration():
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    config = Config(str(ini_path))
    script = ScriptDirectory.from_config(config)
    rev = script.get_revision("5e8a9b0c1d2f")

    assert rev is not None, "Charge points migration revision not found"
    return rev, rev.module


def test_charge_points_migration_revision_chain() -> None:
    rev, cp_migration = _get_charge_points_migration()

    assert rev.revision == "5e8a9b0c1d2f"
    assert rev.down_revision == "8f2b1d3a4c5e"
    assert callable(cp_migration.upgrade)
    assert callable(cp_migration.downgrade)


def test_alembic_revision_exists_in_script_directory() -> None:
    rev, _ = _get_charge_points_migration()

    assert rev.revision == "5e8a9b0c1d2f"
    assert rev.down_revision == "8f2b1d3a4c5e"
