"""Pure validation of daily power schedule bands (S-45 / G2).

Endpoints own persistence. Minutes are local wall-clock boundaries [0, 1440).
Power limits are positive integer Watts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class PowerBandInput:
    start_min: int
    end_min: int
    power_limit_w: int


@dataclass(frozen=True)
class PowerBandIssue:
    code: str
    message: str
    input_indices: tuple[int, ...] = ()
    start_min: int | None = None
    end_min: int | None = None


class PowerBandsError(ValueError):
    def __init__(self, issues: Sequence[PowerBandIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def kiem_khung_gio_cong_suat(
    bands: Sequence[PowerBandInput],
) -> list[PowerBandInput]:
    """Normalize overnight bands, requiring exactly one power limit at every minute.

    Minutes are local wall-clock boundaries [0, 1440), not UTC timestamps.
    Power limit must be a positive integer in Watts (power_limit_w > 0).
    No input is mutated and no database is read.
    """
    issues: list[PowerBandIssue] = []
    normalized: list[tuple[PowerBandInput, int]] = []

    for index, band in enumerate(bands):
        valid = True
        if (
            type(band.start_min) is not int
            or type(band.end_min) is not int
            or not 0 <= band.start_min < 1440
            or not 0 <= band.end_min <= 1440
            or band.start_min == band.end_min
        ):
            issues.append(
                PowerBandIssue("invalid_time", "Mốc giờ không hợp lệ", (index,))
            )
            valid = False

        if (
            type(band.power_limit_w) is not int
            or not 0 < band.power_limit_w <= 2**63 - 1
        ):
            issues.append(
                PowerBandIssue(
                    "invalid_power_limit",
                    "Hạn mức công suất phải là số nguyên dương (Watt > 0)",
                    (index,),
                )
            )
            valid = False

        if not valid:
            continue

        if band.start_min < band.end_min:
            normalized.append((band, index))
        else:
            # Overnight band: split at 1440 (midnight)
            normalized.append(
                (
                    PowerBandInput(band.start_min, 1440, band.power_limit_w),
                    index,
                )
            )
            if band.end_min > 0:
                normalized.append(
                    (
                        PowerBandInput(0, band.end_min, band.power_limit_w),
                        index,
                    )
                )

    if issues:
        raise PowerBandsError(issues)

    boundaries = sorted(
        {0, 1440} | {p for b, _ in normalized for p in (b.start_min, b.end_min)}
    )
    for start, end in pairwise(boundaries):
        owners = tuple(
            sorted(i for b, i in normalized if b.start_min <= start < b.end_min)
        )
        if len(owners) == 1:
            continue
        code = "gap" if not owners else "overlap"
        if (
            issues
            and issues[-1].code == code
            and issues[-1].input_indices == owners
            and issues[-1].end_min == start
        ):
            start = issues.pop().start_min or 0
        title = "Khoảng hở" if code == "gap" else "Khoảng chồng"
        issues.append(
            PowerBandIssue(
                code, f"{title} {_clock(start)}–{_clock(end)}", owners, start, end
            )
        )

    if issues:
        raise PowerBandsError(issues)

    return [b for b, _ in sorted(normalized, key=lambda row: row[0].start_min)]
