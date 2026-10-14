"""T-107 non-mutating seed plan checks; DB acceptance comes after T-55 integration."""

import pytest

from scripts.t107_tariff_seed import Plan


def test_three_bands_cover_whole_day_without_overlap():
    bands = Plan(720, 735, (2000, 3000, 2500)).bands()
    assert [(b.start_min, b.end_min) for b in bands] == [
        (0, 720),
        (720, 735),
        (735, 1440),
    ]
    assert [b.label for b in bands] == ["T107-01", "T107-02", "T107-03"]


@pytest.mark.parametrize("first,second", [(0, 10), (100, 100), (200, 100), (100, 1440)])
def test_boundaries_must_be_in_the_same_day(first, second):
    with pytest.raises(ValueError):
        Plan(first, second, (1000, 2000, 3000)).bands()


def test_price_type_and_seed_prefix_are_strict():
    with pytest.raises(ValueError):
        Plan(1, 2, (1, True, 3)).bands()
    with pytest.raises(ValueError):
        Plan(1, 2, (1, 2, 3), "SIM-").bands()


@pytest.mark.asyncio
async def test_identical_existing_tariff_is_not_inserted_even_when_already_used():
    from datetime import UTC, date, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from scripts.t107_tariff_seed import ensure_first_tariff

    station_id, tariff_id, owner_id = uuid4(), uuid4(), uuid4()
    station = SimpleNamespace(
        id=station_id,
        name="T107-standalone-station",
        owner_id=owner_id,
        timezone="Asia/Ho_Chi_Minh",
        archived_at=None,
    )
    tariff = SimpleNamespace(
        id=tariff_id,
        effective_from=date(2025, 1, 1),
        idle_rate_vnd_per_minute=0,
        grace_minutes=0,
        used_at=datetime.now(UTC),
    )
    bands = [
        SimpleNamespace(
            start_min=b.start_min,
            end_min=b.end_min,
            energy_rate_vnd_per_kwh=b.energy_rate_vnd_per_kwh,
            label=b.label,
        )
        for b in Plan(720, 735, (2000, 3000, 2500)).bands()
    ]

    class Rows:
        def __init__(self, items):
            self.items = items

        def all(self):
            return self.items

    session = SimpleNamespace(
        scalar=AsyncMock(return_value=station),
        scalars=AsyncMock(side_effect=[Rows([tariff]), Rows(bands)]),
    )
    result = await ensure_first_tariff(
        session, station_id=station_id, plan=Plan(720, 735, (2000, 3000, 2500))
    )
    assert result == (tariff_id, False)
    assert session.scalar.await_count == 1
    assert session.scalars.await_count == 2
