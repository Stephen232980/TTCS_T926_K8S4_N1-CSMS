"""Pure validation of daily tariff bands; endpoints own persistence."""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class BandInput:
    start_min: int
    end_min: int
    energy_rate_vnd_per_kwh: int
    label: str = ""


@dataclass(frozen=True)
class BandIssue:
    code: str
    message: str
    input_indices: tuple[int, ...] = ()
    start_min: int | None = None
    end_min: int | None = None


class TariffBandsError(ValueError):
    def __init__(self, issues: Sequence[BandIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


def _clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def kiem_khung_gio(bands: Sequence[BandInput]) -> list[BandInput]:
    """Normalize overnight bands, requiring exactly one price at every minute.

    Minutes are local wall-clock boundaries, not UTC timestamps. Start is in
    [0, 1440), end in [0, 1440]; equal endpoints are invalid. Input indices in
    errors are zero-based. Rates must fit the schema's nonnegative BIGINT.
    No input is mutated and no database is read.
    """
    issues: list[BandIssue] = []
    normalized: list[tuple[BandInput, int]] = []
    for index, band in enumerate(bands):
        valid = True
        if (
            type(band.start_min) is not int
            or type(band.end_min) is not int
            or not 0 <= band.start_min < 1440
            or not 0 <= band.end_min <= 1440
            or band.start_min == band.end_min
        ):
            issues.append(BandIssue("invalid_time", "Mốc giờ không hợp lệ", (index,)))
            valid = False
        if (
            type(band.energy_rate_vnd_per_kwh) is not int
            or not 0 <= band.energy_rate_vnd_per_kwh <= 2**63 - 1
        ):
            issues.append(
                BandIssue(
                    "invalid_rate", "Đơn giá phải là đồng nguyên không âm", (index,)
                )
            )
            valid = False
        if not isinstance(band.label, str) or len(band.label) > 100:
            issues.append(BandIssue("invalid_label", "Nhãn tối đa 100 ký tự", (index,)))
            valid = False
        if not valid:
            continue
        if band.start_min < band.end_min:
            normalized.append((band, index))
        else:
            normalized.append(
                (
                    BandInput(
                        band.start_min, 1440, band.energy_rate_vnd_per_kwh, band.label
                    ),
                    index,
                )
            )
            if band.end_min > 0:
                normalized.append(
                    (
                        BandInput(
                            0, band.end_min, band.energy_rate_vnd_per_kwh, band.label
                        ),
                        index,
                    )
                )
    if issues:
        raise TariffBandsError(issues)

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
        # Merge adjacent intervals only when the same source rows are involved.
        if (
            issues
            and issues[-1].code == code
            and issues[-1].input_indices == owners
            and issues[-1].end_min == start
        ):
            start = issues.pop().start_min or 0
        title = "Khoảng hở" if code == "gap" else "Khoảng chồng"
        issues.append(
            BandIssue(
                code, f"{title} {_clock(start)}–{_clock(end)}", owners, start, end
            )
        )
    if issues:
        raise TariffBandsError(issues)
    return [b for b, _ in sorted(normalized, key=lambda row: row[0].start_min)]
