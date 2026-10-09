"""T-65: exercise normalization and exact daily coverage without a database."""

import pytest

from src.modules.pricing.bands import BandInput, TariffBandsError, kiem_khung_gio


@pytest.mark.parametrize(
    "bands, expected",
    [
        ([BandInput(0, 1440, 0)], [(0, 1440)]),
        (
            [
                BandInput(360, 1320, 3000),
                BandInput(1320, 1440, 2000),
                BandInput(0, 360, 2000),
            ],
            [(0, 360), (360, 1320), (1320, 1440)],
        ),
        (
            [BandInput(1320, 120, 2000, "Đêm"), BandInput(120, 1320, 3000)],
            [(0, 120), (120, 1320), (1320, 1440)],
        ),
        (
            [BandInput(1320, 0, 2000), BandInput(0, 1320, 3000)],
            [(0, 1320), (1320, 1440)],
        ),
    ],
)
def test_valid_daily_coverage(bands, expected):
    original = list(bands)
    result = kiem_khung_gio(bands)
    assert [(b.start_min, b.end_min) for b in result] == expected
    assert sum(b.end_min - b.start_min for b in result) == 1440
    assert bands == original
    assert kiem_khung_gio(result) == result


def test_overnight_preserves_rate_and_label():
    result = kiem_khung_gio(
        [BandInput(1320, 120, 2000, "Đêm"), BandInput(120, 1320, 3000)]
    )
    assert result[0] == BandInput(0, 120, 2000, "Đêm")
    assert result[-1] == BandInput(1320, 1440, 2000, "Đêm")


@pytest.mark.parametrize(
    "bands, code, start, end, indices",
    [
        ([], "gap", 0, 1440, ()),
        ([BandInput(60, 1440, 1000)], "gap", 0, 60, ()),
        ([BandInput(0, 360, 1000), BandInput(420, 1440, 1000)], "gap", 360, 420, ()),
        ([BandInput(0, 1380, 1000)], "gap", 1380, 1440, ()),
        (
            [BandInput(0, 600, 1000), BandInput(540, 1440, 2000)],
            "overlap",
            540,
            600,
            (0, 1),
        ),
        (
            [BandInput(0, 1440, 1000), BandInput(600, 660, 1000)],
            "overlap",
            600,
            660,
            (0, 1),
        ),
        (
            [BandInput(0, 1440, 1000), BandInput(0, 1440, 1000)],
            "overlap",
            0,
            1440,
            (0, 1),
        ),
        (
            [BandInput(1320, 120, 1000), BandInput(60, 1320, 2000)],
            "overlap",
            60,
            120,
            (0, 1),
        ),
    ],
)
def test_exact_gap_and_overlap(bands, code, start, end, indices):
    with pytest.raises(TariffBandsError) as error:
        kiem_khung_gio(bands)
    issue = error.value.issues[0]
    assert (issue.code, issue.start_min, issue.end_min, issue.input_indices) == (
        code,
        start,
        end,
        indices,
    )
    assert (
        f"{start // 60:02d}:{start % 60:02d}–{end // 60:02d}:{end % 60:02d}"
        in issue.message
    )


@pytest.mark.parametrize(
    "start,end",
    [
        (0, 0),
        (60, 60),
        (-1, 60),
        (1440, 60),
        (0, 1441),
        (0, -1),
        (False, 1440),
        (0, 1.5),
    ],
)
def test_invalid_time(start, end):
    with pytest.raises(TariffBandsError) as error:
        kiem_khung_gio([BandInput(start, end, 1000)])
    assert error.value.issues[0].code == "invalid_time"


@pytest.mark.parametrize("rate", [-1, 1.5, True, "1000", 2**63])
def test_invalid_money(rate):
    with pytest.raises(TariffBandsError) as error:
        kiem_khung_gio([BandInput(0, 1440, rate)])
    assert error.value.issues[0].code == "invalid_rate"


def test_reports_all_disjoint_errors():
    with pytest.raises(TariffBandsError) as error:
        kiem_khung_gio([BandInput(60, 600, 1000), BandInput(540, 1380, 2000)])
    assert [(i.code, i.start_min, i.end_min) for i in error.value.issues] == [
        ("gap", 0, 60),
        ("overlap", 540, 600),
        ("gap", 1380, 1440),
    ]


def test_label_length_and_bigint_boundary():
    assert kiem_khung_gio([BandInput(0, 1440, 2**63 - 1, "x" * 100)])
    with pytest.raises(TariffBandsError) as error:
        kiem_khung_gio([BandInput(0, 1440, 1000, "x" * 101)])
    assert error.value.issues[0].code == "invalid_label"
