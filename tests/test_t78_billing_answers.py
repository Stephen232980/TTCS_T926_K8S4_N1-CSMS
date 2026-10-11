"""S-32/T-78: fixed, reviewed T-77 answers exercise the production calculators."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.modules.billing.idle_fee import tinh_phi_chiem_tru
from src.modules.billing.invoicing import _idle_lines
from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan
from src.modules.charging.models import ChargingSession
from src.modules.pricing.models import Tariff
from src.modules.stations.models import Station

ANSWER = json.loads(
    (Path(__file__).resolve().parents[1] / "docs/s32/dap_an_tay.json").read_text(
        encoding="utf-8"
    )
)


def same(case_id, part, field, actual, expected):
    difference = (
        actual - expected
        if isinstance(actual, (int, Decimal)) and isinstance(expected, (int, Decimal))
        else "n/a"
    )
    assert actual == expected, (
        f"{case_id} | {part} | {field} | dap_an_tay={expected} | ket_qua_ma={actual} | "
        f"chenh={difference}" + (" dong" if "vnd" in field else "")
    )


def hhmm(minute):
    return f"{minute // 60:02}:{minute % 60:02}"


@pytest.mark.parametrize("case", ANSWER["cases"], ids=lambda case: case["case_id"])
def test_reviewed_billing_case(case):
    case_id, expected = case["case_id"], case["expected"]
    days = ANSWER["tariff_profiles"][case["tariff_profile"]]
    frames = {
        date.fromisoformat(day): [
            TariffFrame(
                hhmm(b["start_min"]),
                hhmm(b["end_min"]),
                b["rate_vnd"],
                tariff.get("effective_from", day),
                b["label"],
            )
            for b in tariff["bands"]
        ]
        for day, tariff in days.items()
    }
    segments = chia_doan(
        datetime.fromisoformat(case["started_at"]),
        datetime.fromisoformat(case["ended_at"]),
        [
            MeterValue(datetime.fromisoformat(s["at"]), Decimal(s["cumulative_wh"]))
            for s in case["samples"]
        ],
        frames,
        case["timezone"],
    )
    same(case_id, "energy", "line_count", len(segments), len(expected["segments"]))
    for n, (actual, wanted) in enumerate(
        zip(segments, expected["segments"], strict=True), 1
    ):
        part = f"energy[{n}]"
        for field, value in {
            "local_date": date.fromisoformat(wanted["local_date"]),
            "start_time": datetime.fromisoformat(wanted["started_at"]),
            "end_time": datetime.fromisoformat(wanted["ended_at"]),
            "energy_consumed_wh": Decimal(wanted["energy_wh"]),
            "price_vnd_per_kwh": wanted["rate_vnd"],
            "frame_label": wanted["band_label"],
            "amount_vnd": wanted["amount_vnd"],
            "tariff_version": days[wanted["local_date"]].get(
                "effective_from", wanted["local_date"]
            ),
        }.items():
            same(case_id, part, field, actual[field], value)
        same(
            case_id,
            part,
            "interpolated",
            actual["start_interpolated"] or actual["end_interpolated"],
            wanted["interpolated"],
        )
    energy_total = sum(s["amount_vnd"] for s in segments)
    same(
        case_id, "total", "energy_total_vnd", energy_total, expected["energy_total_vnd"]
    )
    same(
        case_id,
        "total",
        "energy_wh",
        sum(s["energy_consumed_wh"] for s in segments),
        case["samples"][-1]["cumulative_wh"] - case["samples"][0]["cumulative_wh"],
    )
    idle_start = (
        datetime.fromisoformat(case["idle_since"]) if case["idle_since"] else None
    )
    end = datetime.fromisoformat(case["ended_at"])
    minutes, _ = tinh_phi_chiem_tru(idle_start, end, case["grace_minutes"], 1)
    same(case_id, "idle", "billed_minutes", minutes, expected["idle_billed_minutes"])
    versions = {
        date.fromisoformat(day): Tariff(
            id=uuid4(),
            grace_minutes=tariff["grace_minutes"],
            idle_rate_vnd_per_minute=tariff["idle_rate_vnd_per_minute"],
        )
        for day, tariff in days.items()
    }
    # Exercise the actual T-80 day-price adapter, rather than duplicate its algorithm.
    lines = _idle_lines(
        ChargingSession(
            started_at=datetime.fromisoformat(case["started_at"]), idle_since=idle_start
        ),
        Station(timezone=case["timezone"]),
        end,
        versions,
        uuid4(),
    )
    same(case_id, "idle", "line_count", len(lines), len(expected["idle_lines"]))
    for n, (actual, wanted) in enumerate(
        zip(lines, expected["idle_lines"], strict=True), 1
    ):
        for field, value in {
            "started_at": datetime.fromisoformat(wanted["started_at"]),
            "ended_at": datetime.fromisoformat(wanted["ended_at"]),
            "local_date": datetime.fromisoformat(wanted["started_at"]).date(),
            "rate_vnd": wanted["rate_vnd_per_minute"],
            "amount_vnd": wanted["amount_vnd"],
        }.items():
            same(case_id, f"idle[{n}]", field, getattr(actual, field), value)
    idle_total = sum(line.amount_vnd for line in lines)
    same(case_id, "total", "idle_total_vnd", idle_total, expected["idle_total_vnd"])
    same(
        case_id, "total", "total_vnd", energy_total + idle_total, expected["total_vnd"]
    )


def test_mismatch_message_identifies_case_segment_values_and_dong_difference():
    with pytest.raises(AssertionError) as failure:
        same("KT-10", "energy[1]", "amount_vnd", 2, 3)
    for text in ["KT-10", "energy[1]", "dap_an_tay=3", "ket_qua_ma=2", "chenh=-1 dong"]:
        assert text in str(failure.value)
