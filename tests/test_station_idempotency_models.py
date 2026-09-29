from alembic.config import Config
from alembic.script import ScriptDirectory

from src.modules.stations.models import StationCreateIdempotency


def test_station_create_idempotency_table_contract() -> None:
    table = StationCreateIdempotency.__table__

    assert table.name == "station_create_idempotency"
    assert {column.name for column in table.primary_key.columns} == {
        "actor_id",
        "idempotency_key",
    }

    assert table.c.request_hash.type.length == 64
    assert not table.c.request_hash.nullable
    assert not table.c.station_id.nullable
    assert not table.c.created_at.nullable

    foreign_keys = {
        foreign_key.parent.name: (
            foreign_key.target_fullname,
            foreign_key.ondelete,
        )
        for foreign_key in table.foreign_keys
    }
    assert foreign_keys == {
        "actor_id": ("users.id", "RESTRICT"),
        "station_id": ("stations.id", "RESTRICT"),
    }


def test_station_create_idempotency_migration_revision_chain() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision("04645d9d9d66")

    assert revision is not None
    assert revision.down_revision == "8f2b1d3a4c5e"
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
