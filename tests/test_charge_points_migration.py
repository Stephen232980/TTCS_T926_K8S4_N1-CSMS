from alembic.config import Config
from alembic.script import ScriptDirectory

REVISION = "ecbbbbc04358"
DOWN_REVISION = "04645d9d9d66"
CURRENT_HEAD = "a104walletbalance"


def test_charge_points_migration_revision_chain() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)


def test_migration_chain_has_only_expected_alembic_head() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [CURRENT_HEAD]
