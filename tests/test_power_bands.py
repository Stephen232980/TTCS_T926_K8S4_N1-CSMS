"""Unit tests for power schedule bands validator (S-45 / G2)."""

import pytest

from src.modules.stations.power_bands import (
    PowerBandInput,
    PowerBandsError,
    kiem_khung_gio_cong_suat,
)


@pytest.mark.parametrize(
    "bands, expected",
    [
        ([PowerBandInput(0, 1440, 50000)], [(0, 1440)]),
        (
            [
                PowerBandInput(360, 1320, 30000),
                PowerBandInput(1320, 1440, 15000),
                PowerBandInput(0, 360, 15000),
            ],
            [(0, 360), (360, 1320), (1320, 1440)],
        ),
        (
            [
                PowerBandInput(1320, 120, 15000),  # 22:00 -> 02:00 overnight
                PowerBandInput(120, 1320, 30000),
            ],
            [(0, 120), (120, 1320), (1320, 1440)],
        ),
        (
            [
                PowerBandInput(1320, 0, 15000),
                PowerBandInput(0, 1320, 30000),
            ],
            [(0, 1320), (1320, 1440)],
        ),
    ],
)
def test_valid_daily_coverage(bands, expected):
    original = list(bands)
    result = kiem_khung_gio_cong_suat(bands)
    assert [(b.start_min, b.end_min) for b in result] == expected
    assert sum(b.end_min - b.start_min for b in result) == 1440
    assert bands == original
    assert kiem_khung_gio_cong_suat(result) == result


def test_overnight_preserves_power_limit():
    result = kiem_khung_gio_cong_suat(
        [
            PowerBandInput(1320, 120, 15000),
            PowerBandInput(120, 1320, 30000),
        ]
    )
    assert result[0] == PowerBandInput(0, 120, 15000)
    assert result[-1] == PowerBandInput(1320, 1440, 15000)


@pytest.mark.parametrize(
    "bands, code, start, end",
    [
        ([], "gap", 0, 1440),
        ([PowerBandInput(60, 1440, 10000)], "gap", 0, 60),
        (
            [PowerBandInput(0, 360, 10000), PowerBandInput(420, 1440, 10000)],
            "gap",
            360,
            420,
        ),
        ([PowerBandInput(0, 1380, 10000)], "gap", 1380, 1440),
        (
            [PowerBandInput(0, 600, 10000), PowerBandInput(540, 1440, 20000)],
            "overlap",
            540,
            600,
        ),
    ],
)
def test_coverage_issues(bands, code, start, end):
    with pytest.raises(PowerBandsError) as exc_info:
        kiem_khung_gio_cong_suat(bands)
    issue = exc_info.value.issues[0]
    assert issue.code == code
    assert issue.start_min == start
    assert issue.end_min == end


@pytest.mark.parametrize(
    "power_limit",
    [0, -1, -50000],
)
def test_non_positive_power_limit_rejected(power_limit):
    with pytest.raises(PowerBandsError) as exc_info:
        kiem_khung_gio_cong_suat([PowerBandInput(0, 1440, power_limit)])
    issue = exc_info.value.issues[0]
    assert issue.code == "invalid_power_limit"


@pytest.mark.parametrize(
    "start, end",
    [
        (-1, 60),
        (0, 1441),
        (60, 60),
    ],
)
def test_invalid_time_endpoints(start, end):
    with pytest.raises(PowerBandsError) as exc_info:
        kiem_khung_gio_cong_suat([PowerBandInput(start, end, 10000)])
    issue = exc_info.value.issues[0]
    assert issue.code == "invalid_time"
