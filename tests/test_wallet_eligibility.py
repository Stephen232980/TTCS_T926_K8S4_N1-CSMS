import pytest

from src.config import settings
from src.modules.wallet.service import du_so_du_de_sac


@pytest.mark.parametrize(
    ("balance_vnd", "price_vnd_per_kwh", "expected"),
    [
        (22_499, 2_500, False),
        (22_500, 2_500, True),
        (24_999, 3_000, False),
        (25_000, 3_000, True),
    ],
)
def test_du_so_du_de_sac_uses_station_price(
    balance_vnd: int, price_vnd_per_kwh: int, expected: bool
) -> None:
    assert du_so_du_de_sac(balance_vnd, price_vnd_per_kwh) is expected


def test_du_so_du_de_sac_uses_shared_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "charging_minimum_kwh", 3)
    monkeypatch.setattr(settings, "wallet_reserve_vnd", 7_000)

    assert not du_so_du_de_sac(12_999, 2_000)
    assert du_so_du_de_sac(13_000, 2_000)


@pytest.mark.parametrize(
    ("balance_vnd", "price_vnd_per_kwh"),
    [(True, 2_500), (22_500, True), (22_500.0, 2_500), (22_500, 2_500.0)],
)
def test_du_so_du_de_sac_rejects_non_integer_amounts(
    balance_vnd: object, price_vnd_per_kwh: object
) -> None:
    with pytest.raises(TypeError):
        du_so_du_de_sac(balance_vnd, price_vnd_per_kwh)


def test_du_so_du_de_sac_rejects_negative_station_price() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        du_so_du_de_sac(100_000, -1)
