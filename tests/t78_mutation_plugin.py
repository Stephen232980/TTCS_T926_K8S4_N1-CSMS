"""Only loaded explicitly by the T-78 mutation verification command."""

import pytest

from src.modules.billing import segmentation


@pytest.fixture(autouse=True)
def floor_money(monkeypatch):
    monkeypatch.setattr(
        segmentation, "tien_dong", lambda wh, rate: int(wh * rate // 1000)
    )
