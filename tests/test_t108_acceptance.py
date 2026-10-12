"""T-108 guards, independent answers and PostgreSQL fixture isolation."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from scripts.t108_staging import verify_suite
from simulator.t108_contract import (
    RunManifest,
    expected_segments,
    new_manifest,
    readings,
)
from simulator.t108_fixture import cleanup_manifest, seed_manifest, user
from simulator.t108_report import compare, write_evidence
from src.modules.charging.models import ChargingCard
from src.modules.wallet.models import Wallet, WalletLedger
from tests.test_effective_tariffs import committed_tariff_db as isolated_t108_db

committed_tariff_db = isolated_t108_db

NOW = datetime(2026, 10, 12, 3, tzinfo=UTC)


def manifest(**kwargs):
    return new_manifest(revision="test-revision", now=NOW, **kwargs)


def test_staging_defaults_and_three_minute_minute_aligned_boundary():
    run = manifest()
    assert len(run.participants) == 20
    assert run.started_at.second == 0
    assert run.boundary_seconds == 180
    assert len({p.card_tag for p in run.participants}) == 20
    assert max(len(p.card_tag) for p in run.participants) <= 20
    assert run.station_id != manifest().station_id


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "unknown"},
        {"schema_version": 2},
        {"boundary_seconds": 60},
        {"duration_seconds": 180},
        {"rates": [2000, 2000, 2500]},
        {"rates": [True, 3000, 2500]},
        {"started_at": "2026-10-12T03:00:01+00:00"},
        {"started_at": "2026-10-12T03:00:00"},
    ],
)
def test_invalid_run_contract_rejected(change):
    values = manifest().model_dump(mode="json") | change
    with pytest.raises(ValidationError):
        RunManifest.model_validate(values)


def test_midnight_and_manifest_identity_guards():
    with pytest.raises(ValidationError, match="midnight|bands"):
        new_manifest(revision="test", now=datetime(2026, 10, 12, 16, 55, tzinfo=UTC))
    values = manifest().model_dump(mode="json")
    values["participants"][0]["driver_email"] = "real-user@example.com"
    with pytest.raises(ValidationError, match="identity"):
        RunManifest.model_validate(values)


def test_independent_answers_default_2000_plus_3000_equals_5000():
    run = manifest()
    answer = expected_segments(run, readings(run))
    assert [s["energy_wh"] for s in answer] == ["1000", "1000"]
    assert [s["amount_vnd"] for s in answer] == [2000, 3000]


def test_independent_rounding_half_up_at_each_segment_and_interpolation():
    run = manifest(mode="ci", count=1, duration=120, boundary=60)
    run.energy_wh = 1
    run.rates = (5, 7, 9)
    samples = [(run.started_at, Decimal(0)), (run.ended_at, Decimal(1))]
    assert [r["amount_vnd"] for r in expected_segments(run, samples)] == [0, 0]
    run.rates = (1000, 1000, 1000)
    assert [r["amount_vnd"] for r in expected_segments(run, samples)] == [1, 1]
    with pytest.raises(ValueError, match="nondecreasing"):
        expected_segments(
            run, [(run.started_at, Decimal(1)), (run.ended_at, Decimal(0))]
        )


def good_evidence(run):
    participant = run.participants[0]
    participant.wallet_id = uuid4()
    participant.balance_before_vnd = 100000
    trace = {
        "session_id": 42,
        "start_delay_seconds": 0,
        "samples": [{"at": at.isoformat(), "wh": str(wh)} for at, wh in readings(run)],
    }
    segments = expected_segments(run, readings(run))
    total = sum(s["amount_vnd"] for s in segments)
    actual = {
        "sessions": [42],
        "session_id": 42,
        "driver_id": str(participant.driver_id),
        "station_id": str(run.station_id),
        "started_at": run.started_at.isoformat(),
        "ended_at": run.ended_at.isoformat(),
        "energy_wh": "2000",
        "settled": True,
        "settlement_reason": "debited",
        "invoice_count": 1,
        "total_vnd": total,
        "lines": [
            s
            | {
                "tariff_id": str(run.tariff_id),
                "line_type": "energy",
                "band_label": f"T108-{i:02d}",
            }
            for i, s in enumerate(segments, 1)
        ],
        "debit_amounts": [-total],
        "debit_wallets": [str(participant.wallet_id)],
        "balance_vnd": 100000 - total,
        "ledger_sum_vnd": 100000 - total,
        "topup_amounts": [100000],
    }
    return participant, trace, actual


@pytest.mark.parametrize(
    "change",
    [
        {"debit_amounts": [-5000, -5000]},
        {"settled": False},
        {"balance_vnd": 100000},
        {"ledger_sum_vnd": 7},
        {"invoice_count": 0},
        {"sessions": [42, 43]},
        {"lines": []},
        {"energy_wh": "1999"},
        {"debit_wallets": ["wrong-wallet"]},
    ],
)
def test_comparison_rejects_wrong_or_missing_financial_evidence(change):
    run = manifest(mode="ci", count=1)
    participant, trace, actual = good_evidence(run)
    assert compare(run, participant, trace, actual)["passed"]
    assert not compare(run, participant, trace, actual | change)["passed"]


def test_spreadsheet_formula_comes_from_sent_readings(tmp_path):
    from openpyxl import load_workbook

    run = manifest(mode="ci", count=1)
    participant, trace, actual = good_evidence(run)
    row = compare(run, participant, trace, actual)
    report = write_evidence(tmp_path, run, {"1": trace}, [row])
    assert report["passed"] and not report["staging_acceptance_candidate"]
    book = load_workbook(tmp_path / "reconciliation.xlsx")
    assert book["Independent answers"]["I2"].value == "=ROUND(G2*H2,0)"
    assert book["Independent answers"]["E2"].value.startswith("='Sent readings'!C")
    assert len(book["Sent readings"]["A"]) == len(trace["samples"]) + 1


def test_three_run_suite_rejects_ci_duplicate_and_partial_reports(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"{index}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": str(uuid4()),
                    "station_id": str(uuid4()),
                    "staging_acceptance_candidate": True,
                    "environment": "staging",
                    "passed": True,
                    "count": 20,
                    "rows": [
                        {
                            "passed": True,
                            "failures": [],
                            "index": i,
                            "code": f"test-{i}",
                            "session_id": i,
                        }
                        for i in range(1, 21)
                    ],
                }
            )
        )
        paths.append(path)
    assert verify_suite(paths)
    assert not verify_suite([paths[0]] * 3)
    value = json.loads(paths[2].read_text())
    value["staging_acceptance_candidate"] = False
    paths[2].write_text(json.dumps(value))
    assert not verify_suite(paths)


def test_saved_manifest_rejects_configuration_overrides(monkeypatch):
    from scripts.t108_staging import arguments

    monkeypatch.setattr(
        "sys.argv", ["t108", "run", "--manifest", "saved.json", "--count=2"]
    )
    with pytest.raises(SystemExit):
        arguments()


@pytest.mark.asyncio
async def test_postgres_two_runs_retry_after_debit_cleanup_and_rollback(
    committed_tariff_db,
):
    factory = committed_tariff_db
    admin_id = uuid4()
    async with factory() as db, db.begin():
        await user(db, admin_id, "t108-test-admin@example.com", ["admin"])
    run = new_manifest(revision="test", mode="ci", count=2)
    other = new_manifest(revision="test", mode="ci", count=1)
    import asyncio

    async def concurrent_seed():
        async with factory() as db, db.begin():
            return await seed_manifest(
                db, run.model_copy(deep=True), "t108-test-admin@example.com"
            )

    assert sorted(await asyncio.gather(concurrent_seed(), concurrent_seed())) == [0, 2]
    async with factory() as db, db.begin():
        assert await seed_manifest(db, run, "t108-test-admin@example.com") == 0
        assert await seed_manifest(db, other, "t108-test-admin@example.com") == 1
    async with factory() as db, db.begin():
        assert await seed_manifest(db, run, "t108-test-admin@example.com") == 0
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 3
        from src.modules.wallet.service import ghi_so_cai

        await ghi_so_cai(
            db,
            wallet_id=run.participants[0].wallet_id,
            entry_type="charging_debit",
            amount_vnd=-1000,
            reference_type="charging_session",
            reference_id="test-debit",
        )
    async with factory() as db, db.begin():
        assert await seed_manifest(db, run, "t108-test-admin@example.com") == 0
        assert (
            await db.get(Wallet, run.participants[0].wallet_id)
        ).balance_vnd == 99000
    broken = run.model_copy(deep=True)
    broken.seed_amount_vnd = 200000
    with pytest.raises(ValueError, match="station"):
        async with factory() as db, db.begin():
            await seed_manifest(db, broken, "t108-test-admin@example.com")
    # A conflict on the second driver must roll back the first driver's topup
    # and all newly created run objects, while preserving the conflicting card.
    failing = new_manifest(revision="test", mode="ci", count=2)
    from src.modules.charging.service import tag_hash
    from src.modules.stations.models import Station

    async with factory() as db, db.begin():
        session_card = ChargingCard(
            tag_hash=tag_hash(failing.participants[1].card_tag),
            tag_tail="test",
            driver_id=other.participants[0].driver_id,
            issuer_id=other.owner_id,
            status="active",
        )
        db.add(session_card)
    with pytest.raises(ValueError, match="card"):
        async with factory() as db, db.begin():
            await seed_manifest(db, failing, "t108-test-admin@example.com")
    async with factory() as db:
        assert await db.get(Station, failing.station_id) is None
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 4
    async with factory() as db, db.begin():
        await cleanup_manifest(db, run)
        await cleanup_manifest(db, run)
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(WalletLedger)) == 4
        cards = list(
            await db.scalars(
                select(ChargingCard).where(
                    ChargingCard.driver_id == other.participants[0].driver_id
                )
            )
        )
        assert all(c.status == "active" for c in cards)
    with pytest.raises(ValueError, match="identity"):
        async with factory() as db, db.begin():
            await seed_manifest(db, run, "t108-test-admin@example.com")
