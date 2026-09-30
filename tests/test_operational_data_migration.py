from alembic.config import Config
from alembic.script import ScriptDirectory

REVISION = "7b1d4f2a9c30"
DOWN_REVISION = "ecbbbbc04358"


def test_operational_data_migration_revision_chain() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.revision == REVISION
    assert revision.down_revision == DOWN_REVISION
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
