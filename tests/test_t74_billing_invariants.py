"""200 reproducible sessions; reference calculations never call billing helpers."""

import json
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from src.modules.billing.segmentation import MeterValue, TariffFrame, chia_doan

SEED = 7402026


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def reference_meter(at: datetime, samples: list[MeterValue]) -> Decimal:
    for sample in samples:
        if at == sample.timestamp:
            return sample.energy_wh
    for left, right in pairwise(samples):
        if left.timestamp < at < right.timestamp:
            # All generated timestamps have whole-second precision. Fractions
            # keep this oracle independent from Decimal timestamp arithmetic.
            elapsed = (at - left.timestamp) // timedelta(seconds=1)
            duration = (right.timestamp - left.timestamp) // timedelta(seconds=1)
            value = Fraction(left.energy_wh) + (
                Fraction(right.energy_wh - left.energy_wh) * Fraction(elapsed, duration)
            )
            whole, remainder = divmod(value.numerator, value.denominator)
            return Decimal(whole + int(2 * remainder >= value.denominator))
    raise AssertionError("Reference timestamp outside samples")


@pytest.mark.parametrize("case_id", range(200), ids=lambda n: f"seed-{SEED}-case-{n}")
def test_random_session_invariants(case_id: int) -> None:
    rng = random.Random(SEED + case_id)
    timezone = ["Asia/Ho_Chi_Minh", "Asia/Kolkata", "UTC"][case_id % 3]
    tz = ZoneInfo(timezone)
    anchor = datetime(2026, 1, 31, tzinfo=tz)
    # Include exact boundaries, sub-minute starts and the full 30-hour limit.
    second = [0, 21 * 3600 + 30 * 60, 23 * 3600, 86399][case_id % 4]
    if case_id % 5:
        second = rng.randrange(86400)
    start = (anchor + timedelta(seconds=second)).astimezone(UTC)
    duration = 30 * 3600 if case_id % 10 == 0 else rng.randint(1, 30 * 3600)
    end = start + timedelta(seconds=duration)
    count = min(duration, rng.randint(2, 20))
    if case_id % 2:
        offsets = {duration * i // count for i in range(count + 1)}
    else:
        offsets = {0, duration, *rng.sample(range(1, duration), count - 1)}
    energy = rng.randint(0, 10**9)
    samples: list[MeterValue] = []
    for index, offset in enumerate(sorted(offsets)):
        if index and case_id % 20:
            energy += 0 if rng.randrange(4) == 0 else rng.randint(1, 20000)
        samples.append(MeterValue(start + timedelta(seconds=offset), Decimal(energy)))

    tariffs: dict[date, list[TariffFrame]] = {}
    cuts = {start, end}
    day = start.astimezone(tz).date()
    while day <= end.astimezone(tz).date():
        boundaries = [0, *sorted(rng.sample(range(1, 1440), rng.randint(1, 5))), 1440]
        tariffs[day] = [
            TariffFrame(
                clock(a),
                clock(b),
                rng.choice([0, 2500, 3000, 3800]),
                str(day),
                f"band-{i}",
            )
            for i, (a, b) in enumerate(pairwise(boundaries))
        ]
        midnight = datetime.combine(day, time(), tzinfo=tz)
        for minute in boundaries:
            boundary = (midnight + timedelta(minutes=minute)).astimezone(UTC)
            if start < boundary < end:
                cuts.add(boundary)
        day += timedelta(days=1)

    context = json.dumps(
        {
            "seed": SEED,
            "case_id": case_id,
            "case_seed": SEED + case_id,
            "timezone": timezone,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "samples": [(s.timestamp.isoformat(), str(s.energy_wh)) for s in samples],
            "tariffs": {
                str(d): [
                    (f.start_time, f.end_time, f.price_vnd_per_kwh) for f in frames
                ]
                for d, frames in tariffs.items()
            },
        }
    )
    ordered = sorted(cuts)
    expected = []
    for left, right in pairwise(ordered):
        wh = reference_meter(right, samples) - reference_meter(left, samples)
        if wh:
            expected.append((left, right, wh))

    segments = chia_doan(start, end, samples, tariffs, timezone)
    actual = [
        (s["start_time"], s["end_time"], s["energy_consumed_wh"]) for s in segments
    ]
    assert actual == expected, context
    assert sum((s["energy_consumed_wh"] for s in segments), Decimal(0)) == (
        samples[-1].energy_wh - samples[0].energy_wh
    ), context

    previous_end = start
    total_amount = 0
    for segment in segments:
        left, right = segment["start_time"], segment["end_time"]
        assert start <= left < right <= end, context
        assert previous_end <= left, context
        # A gap is valid only if its rounded boundary readings are equal:
        # zero-consumption intervals are intentionally absent from the output.
        assert reference_meter(previous_end, samples) == reference_meter(
            left, samples
        ), context
        previous_end = right
        local = left.astimezone(tz)
        assert segment["local_date"] == local.date(), context
        frame = next(
            f
            for f in tariffs[local.date()]
            if f.start_time <= local.strftime("%H:%M") < f.end_time
        )
        assert segment["price_vnd_per_kwh"] == frame.price_vnd_per_kwh, context
        amount = int(
            (
                segment["energy_consumed_wh"] * frame.price_vnd_per_kwh / Decimal(1000)
            ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
        assert segment["amount_vnd"] == amount, context
        total_amount += amount
    assert reference_meter(previous_end, samples) == reference_meter(end, samples), (
        context
    )
    assert sum(s["amount_vnd"] for s in segments) == total_amount, context
