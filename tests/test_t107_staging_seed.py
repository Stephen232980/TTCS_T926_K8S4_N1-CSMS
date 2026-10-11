"""T-107 contract tests; no DB access or writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from scripts.t107_staging_seed import (
    DRIVER_COUNT,
    FixtureConfig,
    _credit_once,
    card_tag,
    charger_code,
    driver_email,
    receipt_code,
)
from scripts.t107_tariff_seed import Plan


def test_unique_namespaces_match_twenty_chargers_and_drivers():
    assert DRIVER_COUNT == 20
    assert driver_email(1) == "t107-seed-driver-001@example.com"
    assert driver_email(20) == "t107-seed-driver-020@example.com"
    assert charger_code(1) == "T107-001"
    assert charger_code(20) == "T107-020"
    assert card_tag(1) == "T107TAG-001"
    assert receipt_code(20) == "T107-SEED-020"
    for creator in (driver_email, charger_code, card_tag, receipt_code):
        assert len({creator(i) for i in range(1, 21)}) == DRIVER_COUNT


@pytest.mark.parametrize("index", [0, 21, -1, 1.0, True])
def test_out_of_range_ids_rejected(index):
    for creator in (driver_email, charger_code, card_tag, receipt_code):
        with pytest.raises(ValueError):
            creator(index)


def test_three_band_plan_and_manual_seed_credit_validation():
    config = FixtureConfig(Plan(720, 735, (2000, 3000, 2500)), 100_000)
    config.validate()
    assert len(config.plan.bands()) == 3


@pytest.mark.parametrize("amount", [0, -1, True, 2**63])
def test_invalid_credit_amount_fails_closed(amount):
    with pytest.raises(ValueError):
        FixtureConfig(Plan(720, 735, (2000, 3000, 2500)), amount).validate()


@pytest.mark.asyncio
async def test_initial_credit_calls_t88_once_and_uses_fixed_receipt():
    wallet = SimpleNamespace(id=uuid4(), status="active", balance_vnd=0)
    driver = SimpleNamespace(id=uuid4(), email=driver_email(1))
    admin = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: ["operator", "admin"])),
    )
    with patch("scripts.t107_staging_seed.nap_tay", new_callable=AsyncMock) as topup:
        result = await _credit_once(
            session, driver=driver, wallet=wallet, admin=admin,
            index=1, amount_vnd=100_000,
        )
    assert result is True
    topup.assert_awaited_once()
    kwargs = topup.await_args.kwargs
    assert kwargs["driver_id"] == driver.id
    assert kwargs["actor_id"] == admin.id
    assert kwargs["authorization"].permission == "admin.wallet.manual_topup"
    assert kwargs["authorization"].roles == ("admin", "operator")
    assert kwargs["request"].receipt_code == "T107-SEED-001"
    assert kwargs["request"].amount_vnd == 100_000


@pytest.mark.asyncio
async def test_repeat_receipt_is_not_credited_again_even_after_wallet_debit():
    wallet = SimpleNamespace(id=uuid4(), status="active", balance_vnd=31_000)
    existing = SimpleNamespace(
        wallet_id=wallet.id, amount_vnd=100_000, reference_type="manual_topup"
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=existing))
    with patch("scripts.t107_staging_seed.nap_tay", new_callable=AsyncMock) as topup:
        result = await _credit_once(
            session,
            driver=SimpleNamespace(id=uuid4(), email=driver_email(1)),
            wallet=wallet, admin=SimpleNamespace(id=uuid4()),
            index=1, amount_vnd=100_000,
        )
    assert result is False
    topup.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_receipt_for_wrong_wallet_refuses_to_adopt():
    wallet = SimpleNamespace(id=uuid4(), status="active", balance_vnd=100_000)
    session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(
        wallet_id=uuid4(), amount_vnd=100_000, reference_type="manual_topup"
    )))
    with patch("scripts.t107_staging_seed.nap_tay", new_callable=AsyncMock) as topup:
        with pytest.raises(RuntimeError, match="Conflicting existing receipt"):
            await _credit_once(
                session, driver=SimpleNamespace(id=uuid4(), email=driver_email(1)),
                wallet=wallet, admin=SimpleNamespace(id=uuid4()),
                index=1, amount_vnd=100_000,
            )
    topup.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_nonempty_wallet_is_not_silently_credited():
    wallet = SimpleNamespace(id=uuid4(), status="active", balance_vnd=40_000)
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with patch("scripts.t107_staging_seed.nap_tay", new_callable=AsyncMock) as topup:
        with pytest.raises(RuntimeError, match="nonempty/locked wallet"):
            await _credit_once(
                session, driver=SimpleNamespace(id=uuid4(), email=driver_email(1)),
                wallet=wallet, admin=SimpleNamespace(id=uuid4()),
                index=1, amount_vnd=100_000,
            )
    topup.assert_not_awaited()


def _cleanup_session_fixture(unsettled_count: int = 0):
    from scripts.t107_staging_seed import STATION_ADDRESS, STATION_NAME

    owner = SimpleNamespace(id=uuid4(), status="active")
    station = SimpleNamespace(
        id=uuid4(), owner_id=owner.id, name=STATION_NAME,
        address=STATION_ADDRESS, archived_at=None, status="active",
    )
    drivers = []
    cards = []
    per_driver_cards = []
    chargers = []
    connectors = []
    responses = [owner, station]
    for idx in range(1, 21):
        driver = SimpleNamespace(id=uuid4(), status="active")
        charger = SimpleNamespace(
            id=uuid4(), station_id=station.id,
            name=f"T107 virtual charger {charger_code(idx)}", archived_at=None,
        )
        card = SimpleNamespace(
            id=uuid4(), driver_id=driver.id, issuer_id=owner.id, status="active",
        )
        auto_card = SimpleNamespace(
            id=uuid4(), driver_id=driver.id, issuer_id=driver.id, status="active",
        )
        per_driver_cards.append([card, auto_card])
        connector = SimpleNamespace(archived_at=None)
        drivers.append(driver)
        cards.extend((card, auto_card))
        chargers.append(charger)
        connectors.append(connector)
        responses.extend((driver, charger, card, connector))
    responses.append(unsettled_count)
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=responses), execute=AsyncMock(),
        scalars=AsyncMock(side_effect=[
            SimpleNamespace(all=lambda members=members: members)
            for members in per_driver_cards
        ]),
    )
    return session, owner, station, drivers, cards, chargers, connectors


@pytest.mark.asyncio
async def test_logical_cleanup_archives_only_own_fixture_and_preserves_evidence():
    from scripts.t107_staging_seed import cleanup_fixture

    session, owner, station, drivers, cards, chargers, connectors = (
        _cleanup_session_fixture()
    )
    result = await cleanup_fixture(session)
    assert result == 20
    assert owner.status == "deactivated"
    assert station.status == "inactive" and station.archived_at is not None
    assert all(d.status == "deactivated" for d in drivers)
    assert all(c.status == "blocked" for c in cards)
    assert all(c.archived_at is not None for c in chargers)
    assert all(c.archived_at is not None for c in connectors)
    assert not hasattr(session, "delete")


@pytest.mark.asyncio
async def test_cleanup_refuses_open_or_unsettled_session_without_mutating_data():
    from scripts.t107_staging_seed import cleanup_fixture

    session, owner, station, drivers, cards, chargers, connectors = (
        _cleanup_session_fixture(unsettled_count=1)
    )
    with pytest.raises(RuntimeError, match="open/unsettled"):
        await cleanup_fixture(session)
    assert owner.status == "active" and station.archived_at is None
    assert all(d.status == "active" for d in drivers)
    assert all(c.status == "active" for c in cards)
    assert all(c.archived_at is None for c in chargers + connectors)


@pytest.mark.asyncio
async def test_cleanup_is_idempotent_when_fixture_was_already_archived():
    from scripts.t107_staging_seed import cleanup_fixture

    session, owner, station, drivers, cards, chargers, connectors = (
        _cleanup_session_fixture()
    )
    station.archived_at = "prior cleanup marker"
    owner.status = "deactivated"
    for driver in drivers:
        driver.status = "deactivated"
    for card in cards:
        card.status = "blocked"
    assert await cleanup_fixture(session) == 0
    assert station.archived_at == "prior cleanup marker"


@pytest.mark.asyncio
async def test_cleanup_rejects_unexpected_third_card_without_mutation():
    from scripts.t107_staging_seed import cleanup_fixture

    session, owner, station, drivers, cards, chargers, connectors = (
        _cleanup_session_fixture()
    )
    # A card issued by an unknown account must not be swept into T107 cleanup.
    original = list(session.scalars.side_effect)
    unexpected = SimpleNamespace(
        id=uuid4(), driver_id=drivers[0].id, issuer_id=uuid4(), status="active"
    )
    original[0] = SimpleNamespace(all=lambda: [cards[0], cards[1], unexpected])
    session.scalars.side_effect = iter(original)
    with pytest.raises(RuntimeError, match="Unexpected card inventory"):
        await cleanup_fixture(session)
    assert owner.status == "active" and station.archived_at is None
    assert all(d.status == "active" for d in drivers)
    assert all(c.status == "active" for c in cards)
