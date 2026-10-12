"""T-107 boundary tests: no station creation if T-108 fixture is absent."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from scripts.t107_manifest_run import apply_run, cleanup_run, verify_prepared_run
from simulator.t108_contract import RunManifest, new_manifest


def test_manifest_generates_distinct_run_scoped_receipts():
    first = new_manifest(revision="test", mode="ci", count=2)
    second = new_manifest(revision="test", mode="ci", count=2)
    assert first.run_id != second.run_id
    assert {p.seed_receipt_code for p in first.participants}.isdisjoint(
        p.seed_receipt_code for p in second.participants
    )
    assert len({p.card_tag for p in first.participants}) == 2


def test_changed_run_config_changes_station_marker():
    manifest = new_manifest(revision="test", mode="ci", count=2)
    changed = manifest.model_copy(deep=True)
    changed.seed_amount_vnd += 1
    assert changed.configuration_hash != manifest.configuration_hash


@pytest.mark.asyncio
async def test_missing_t108_station_prevents_any_funding():
    manifest = new_manifest(revision="test", mode="ci", count=2)
    session = SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=None))
    with (
        patch(
            "scripts.t107_manifest_run.seed_manifest", new_callable=AsyncMock
        ) as seed,
        pytest.raises(ValueError, match="not prepared"),
    ):
        await apply_run(session, manifest, "admin@example.com")

    seed.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_run_uses_shared_adapter_and_advisory_lock():
    manifest = new_manifest(revision="test", mode="ci", count=2)
    session = SimpleNamespace(execute=AsyncMock())
    with patch(
        "scripts.t107_manifest_run.cleanup_manifest", new_callable=AsyncMock
    ) as cleanup:
        await cleanup_run(session, manifest)
    session.execute.assert_awaited_once()
    cleanup.assert_awaited_once_with(session, manifest)


@pytest.mark.asyncio
async def test_validation_refuses_wrong_station_marker():
    manifest = new_manifest(revision="test", mode="ci", count=2)
    station = SimpleNamespace(
        owner_id=uuid4(), name="not-my-run", address="wrong", status="active"
    )
    session = SimpleNamespace(get=AsyncMock(return_value=station))
    with pytest.raises(ValueError, match="station not prepared"):
        await verify_prepared_run(session, manifest)


def test_staging_contract_requires_twenty_run_scoped_identities():
    now = datetime(2026, 10, 12, 3, tzinfo=UTC)
    run = new_manifest(revision="test", now=now)
    assert len(run.participants) == 20
    assert len({p.driver_id for p in run.participants}) == 20
    assert len({p.card_tag for p in run.participants}) == 20
    assert len({p.seed_receipt_code for p in run.participants}) == 20
    assert run.boundary_seconds == 180
    with pytest.raises(ValidationError, match="20 chargers"):
        new_manifest(revision="test", count=2, now=now)


@pytest.mark.parametrize("field", ["driver_email", "card_tag", "seed_receipt_code"])
def test_saved_contract_rejects_identity_tampering(field):
    run = new_manifest(revision="test", now=datetime(2026, 10, 12, 3, tzinfo=UTC))
    payload = run.model_dump(mode="json")
    payload["participants"][9][field] = "not-owned-by-run"
    with pytest.raises(ValidationError, match="identity mismatch"):
        RunManifest.model_validate(payload)
