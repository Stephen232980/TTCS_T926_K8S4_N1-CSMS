import importlib

from alembic.config import Config
from alembic.script import ScriptDirectory

cp_migration = importlib.import_module(
    "migrations.versions.5e8a9b0c1d2f_tao_bang_charge_points_va_connectors"
)


def test_charge_points_migration_revision_chain() -> None:
    assert cp_migration.revision == "5e8a9b0c1d2f"
    assert cp_migration.down_revision == "8f2b1d3a4c5e"
    assert callable(cp_migration.upgrade)
    assert callable(cp_migration.downgrade)


def test_alembic_heads_resolves_to_charge_points_migration() -> None:
    alembic_config = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_config)
    heads = script.get_heads()

    assert heads == ["5e8a9b0c1d2f"]
    rev = script.get_revision("5e8a9b0c1d2f")
    assert rev is not None
    assert rev.down_revision == "8f2b1d3a4c5e"
