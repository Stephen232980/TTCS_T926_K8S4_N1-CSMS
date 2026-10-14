"""T-108 persisted run contract and independent integer-money oracle.

No imports from production billing: answers are calculated from sent readings.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    charge_point_id: UUID
    charge_point_code: str
    connector_id: UUID
    connector_number: int = 1
    driver_id: UUID
    driver_email: str
    card_tag: str
    seed_receipt_code: str
    wallet_id: UUID | None = None
    balance_before_vnd: int | None = None


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    run_id: UUID
    mode: str = "staging"
    created_at: datetime
    started_at: datetime
    station_timezone: str = "Asia/Ho_Chi_Minh"
    station_id: UUID
    owner_id: UUID
    tariff_id: UUID | None = None
    source_revision: str
    duration_seconds: int = Field(default=360, ge=2, le=3600)
    boundary_seconds: int = 180
    sample_seconds: int = Field(default=30, ge=1, le=60)
    energy_wh: int = Field(default=2000, ge=1, le=100000)
    rates: tuple[StrictInt, StrictInt, StrictInt] = (2000, 3000, 2500)
    seed_amount_vnd: int = Field(default=100000, gt=0, le=10000000)
    participants: list[Participant]

    @model_validator(mode="after")
    def validate_contract(self) -> "RunManifest":
        if self.schema_version != 1 or self.mode not in {"staging", "ci"}:
            raise ValueError("Unsupported manifest version or mode")
        if self.started_at.utcoffset() is None or self.created_at.utcoffset() is None:
            raise ValueError("Manifest timestamps must have offsets")
        local = self.started_at.astimezone(ZoneInfo(self.station_timezone))
        if local.second or local.microsecond:
            raise ValueError("Start must align with a local minute")
        if not 0 < self.boundary_seconds < self.duration_seconds:
            raise ValueError("Every session must cross the tariff boundary")
        if self.boundary_seconds % 60:
            raise ValueError("Tariff boundary must align with a local minute")
        if self.mode == "staging" and self.boundary_seconds != 180:
            raise ValueError("Staging requires the three-minute boundary")
        if any(type(rate) is not int or rate <= 0 for rate in self.rates):
            raise ValueError("Use three positive integer test rates")
        if self.rates[0] == self.rates[1]:
            raise ValueError("The crossed bands must have different rates")
        if not 1 <= len(self.participants) <= 100:
            raise ValueError("Count must be 1..100")
        if self.mode == "staging" and len(self.participants) != 20:
            raise ValueError("Staging acceptance requires 20 chargers")
        if (
            local.date()
            != (local + timedelta(seconds=self.duration_seconds + 120)).date()
        ):
            raise ValueError("Too close to station midnight; start a new run tomorrow")
        if self.second_boundary_minute >= 1440 or self.first_boundary_minute <= 0:
            raise ValueError("Three tariff bands must fit the station day")
        expected = make_participants(self.run_id, len(self.participants))
        for actual, planned in zip(self.participants, expected, strict=True):
            for field in Participant.model_fields:
                if field not in {"wallet_id", "balance_before_vnd"} and getattr(
                    actual, field
                ) != getattr(planned, field):
                    raise ValueError(f"Manifest identity mismatch: {field}")
        if self.station_id != uuid5(self.run_id, "station") or self.owner_id != uuid5(
            self.run_id, "owner"
        ):
            raise ValueError("Manifest station/owner mismatch")
        return self

    @property
    def first_boundary_minute(self) -> int:
        local = self.started_at.astimezone(ZoneInfo(self.station_timezone))
        return local.hour * 60 + local.minute + self.boundary_seconds // 60

    @property
    def second_boundary_minute(self) -> int:
        local = self.started_at.astimezone(ZoneInfo(self.station_timezone))
        return local.hour * 60 + local.minute + (self.duration_seconds + 120 + 59) // 60

    @property
    def ended_at(self) -> datetime:
        return self.started_at + timedelta(seconds=self.duration_seconds)

    @property
    def configuration_hash(self) -> str:
        values = self.model_dump(mode="json", exclude={"tariff_id"})
        for participant in values["participants"]:
            participant.pop("wallet_id")
            participant.pop("balance_before_vnd")
        return sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def make_participants(run_id: UUID, count: int) -> list[Participant]:
    return [
        Participant(
            index=index,
            charge_point_id=uuid5(run_id, f"charger:{index}"),
            charge_point_code=f"T108-{run_id.hex}-{index:03d}",
            connector_id=uuid5(run_id, f"connector:{index}"),
            driver_id=uuid5(run_id, f"driver:{index}"),
            driver_email=f"t108-{run_id.hex}-{index:03d}@example.com",
            card_tag=f"T108{run_id.hex[:12]}{index:03d}",
            seed_receipt_code=f"T108-{run_id.hex}-{index:03d}",
        )
        for index in range(1, count + 1)
    ]


def new_manifest(
    *,
    revision: str,
    mode: str = "staging",
    count: int = 20,
    duration: int = 360,
    boundary: int = 180,
    now: datetime | None = None,
    rates: tuple[int, int, int] = (2000, 3000, 2500),
    amount: int = 100000,
    energy_wh: int = 2000,
    sample_seconds: int = 30,
) -> RunManifest:
    now = now or datetime.now(UTC)
    if mode == "staging":
        start = (now + timedelta(minutes=3)).replace(second=0, microsecond=0)
    else:
        # Buffered historical source clock: fast CI is never staging evidence.
        start = now.replace(second=0, microsecond=0) - timedelta(
            seconds=((duration + 59) // 60) * 60
        )
    run_id = uuid4()
    return RunManifest(
        run_id=run_id,
        created_at=now,
        started_at=start,
        station_id=uuid5(run_id, "station"),
        owner_id=uuid5(run_id, "owner"),
        source_revision=revision,
        mode=mode,
        duration_seconds=duration,
        boundary_seconds=boundary,
        rates=rates,
        seed_amount_vnd=amount,
        energy_wh=energy_wh,
        sample_seconds=sample_seconds,
        participants=make_participants(run_id, count),
    )


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def readings(manifest: RunManifest) -> list[tuple[datetime, Decimal]]:
    offsets = sorted(
        {
            0,
            manifest.boundary_seconds,
            manifest.duration_seconds,
            *range(0, manifest.duration_seconds, manifest.sample_seconds),
        }
    )
    return [
        (
            manifest.started_at + timedelta(seconds=offset),
            Decimal(1000)
            + (
                Decimal(manifest.energy_wh) * offset / manifest.duration_seconds
            ).quantize(Decimal("0.000001")),
        )
        for offset in offsets
    ]


def expected_segments(
    manifest: RunManifest, samples: list[tuple[datetime, Decimal]]
) -> list[dict]:
    """Independent piecewise interpolation, half-up each price segment."""
    if samples[0][0] != manifest.started_at or samples[-1][0] != manifest.ended_at:
        raise ValueError("Readings must include the actual start and stop")
    if any(
        right[0] <= left[0] or right[1] < left[1] for left, right in pairwise(samples)
    ):
        raise ValueError("Readings must be strictly ordered and nondecreasing")
    boundary = manifest.started_at + timedelta(seconds=manifest.boundary_seconds)
    points = [manifest.started_at, boundary, manifest.ended_at]

    def at(stamp: datetime) -> Decimal:
        for left, right in pairwise(samples):
            if left[0] <= stamp <= right[0]:
                fraction = Decimal(str((stamp - left[0]).total_seconds())) / Decimal(
                    str((right[0] - left[0]).total_seconds())
                )
                return left[1] + (right[1] - left[1]) * fraction
        raise ValueError("Missing bracketing sample")

    result = []
    for index, (start, end) in enumerate(pairwise(points)):
        wh = at(end) - at(start)
        rate = manifest.rates[index]
        result.append(
            {
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "energy_wh": format(wh.normalize(), "f"),
                "rate_vnd": rate,
                "amount_vnd": int(
                    (wh * rate / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                ),
            }
        )
    return result
