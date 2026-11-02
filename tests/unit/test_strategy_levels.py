"""CPR, Camarilla, period aggregation and Pine built-ins, checked against hand calculations."""

import math
from datetime import date

import pytest

from app.strategy.levels import (
    HIST_POSSIBLE,
    HIST_SIDEWAYS,
    HIST_SIDEWAYS_TRADE,
    HIST_TRENDING,
    PeriodBar,
    calculate_camarilla,
    calculate_cpr,
    cpr_band,
    histogram,
)
from app.strategy.periods import Period, PeriodAggregator
from app.strategy.pine import Ema, Rma, Sma

NAN = math.nan
BAR = PeriodBar(open=100, high=110, low=90, close=105)


def test_cpr_matches_hand_calculation() -> None:
    cpr = calculate_cpr(BAR, 104, NAN, NAN)
    expected = {
        "pp": 305 / 3,
        "bc": 100.0,
        "tc": 305 / 3 * 2 - 100,
        "r1": 2 * 305 / 3 - 90,
        "s1": 2 * 305 / 3 - 110,
        "r2": 305 / 3 + 20,
        "s2": 305 / 3 - 20,
        "r3": 110 + 2 * (305 / 3 - 90),
        "s3": 90 - 2 * (110 - 305 / 3),
        "ph": 110.0,
        "pl": 90.0,
    }
    for name, value in expected.items():
        assert getattr(cpr, name) == pytest.approx(value, abs=1e-9), name
    assert cpr.r4 == pytest.approx(cpr.r3 + cpr.r2 - cpr.r1)
    assert cpr.s4 == pytest.approx(cpr.s3 + cpr.s2 - cpr.s1)


def test_tc_and_bc_swap_when_close_is_below_the_midpoint() -> None:
    cpr = calculate_cpr(PeriodBar(100, 110, 90, 95), 100, NAN, NAN)
    assert cpr.tc == 100.0
    assert cpr.bc == pytest.approx(295 / 3 * 2 - 100)
    assert cpr.tc > cpr.bc


def test_missing_history_gives_na_levels_and_no_relationship() -> None:
    cpr = calculate_cpr(None, 100, NAN, NAN)
    assert math.isnan(cpr.tc)
    assert cpr.relationship == "unchanged"
    assert cpr.bias == "Trend Rejected"
    assert cpr_band(None) == (NAN, NAN) or all(math.isnan(v) for v in cpr_band(None))


@pytest.mark.parametrize(
    ("prev_tc", "prev_bc", "session_open", "relationship", "bias"),
    [
        (99.0, 98.0, 104.0, "higher", "Bull Accept"),
        (99.0, 98.0, 99.5, "higher", "Sell here"),
        (110.0, 108.0, 100.0, "lower", "Bear Accept"),
        (110.0, 108.0, 104.0, "lower", "Buy here"),
        (104.0, 99.0, 102.0, "inside", "Inside - No Setup"),
        (104.0, 99.0, 115.0, "inside", "Bullish Breakout"),
        (102.0, 101.0, 102.0, "outside", "Outside - Target CPR"),
    ],
)
def test_cpr_relationship_and_bias(
    prev_tc: float, prev_bc: float, session_open: float, relationship: str, bias: str
) -> None:
    cpr = calculate_cpr(BAR, session_open, prev_tc, prev_bc)  # band is 100 to 103.33
    assert cpr.relationship == relationship
    assert cpr.bias == bias


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (0.0, HIST_TRENDING),
        (0.2499, HIST_TRENDING),
        (0.25, HIST_POSSIBLE),
        (0.5, HIST_SIDEWAYS),
        (0.75, HIST_SIDEWAYS_TRADE),
        (NAN, HIST_SIDEWAYS_TRADE),
    ],
)
def test_histogram_thresholds(width: float, expected: str) -> None:
    assert histogram(width) == expected


def test_camarilla_matches_hand_calculation() -> None:
    cam = calculate_camarilla(BAR, 104, NAN, NAN)
    assert cam.center == 105
    assert cam.h3 == pytest.approx(110.5)
    assert cam.l3 == pytest.approx(99.5)
    assert cam.h4 == pytest.approx(116.0)
    assert cam.l4 == pytest.approx(94.0)
    assert cam.h5 == pytest.approx(110 / 90 * 105)
    assert cam.h6 == pytest.approx(cam.h5 + 1.168 * (cam.h5 - cam.h4))
    assert cam.l5 == pytest.approx(105 - (cam.h5 - 105))
    assert cam.l6 == pytest.approx(105 - (cam.h6 - 105))


def test_camarilla_relationship() -> None:
    cam = calculate_camarilla(BAR, 112, prev_h3=99.0, prev_l3=95.0)
    assert cam.relationship == "higher"
    assert cam.bias == "Bull Accept"


def test_weekly_levels_use_the_previous_week_and_this_weeks_open() -> None:
    weekly = PeriodAggregator(Period.WEEK)
    # Week of 2025-06-09.
    weekly.add_day(date(2025, 6, 9), PeriodBar(100, 130, 110, 120))
    weekly.add_day(date(2025, 6, 13), PeriodBar(118, 105, 95, 102))
    # Week of 2025-06-16: Monday and Tuesday completed, evaluating Wednesday.
    weekly.add_day(date(2025, 6, 16), PeriodBar(101, 104, 99, 103))
    weekly.add_day(date(2025, 6, 17), PeriodBar(103, 140, 80, 90))
    levels = weekly.levels_for(date(2025, 6, 18), session_open=91)

    assert levels.open == 101  # Monday's open, not Wednesday's
    expected = calculate_cpr(PeriodBar(100, 130, 95, 102), 101, NAN, NAN)
    assert levels.cpr.tc == expected.tc
    assert levels.cpr.bc == expected.bc
    # The current week's extremes (140, 80) must not leak into its own levels.
    assert levels.cpr.ph == 130
    assert levels.cpr.pl == 95


def test_daily_levels_use_the_previous_session() -> None:
    daily = PeriodAggregator(Period.DAY)
    daily.add_day(date(2025, 6, 12), PeriodBar(100, 110, 90, 105))
    daily.add_day(date(2025, 6, 13), PeriodBar(105, 120, 100, 110))
    levels = daily.levels_for(date(2025, 6, 16), session_open=111)
    assert levels.open == 111
    assert levels.cpr.ph == 120
    prev_tc, prev_bc = cpr_band(PeriodBar(100, 110, 90, 105))
    assert levels.cpr == calculate_cpr(PeriodBar(105, 120, 100, 110), 111, prev_tc, prev_bc)


def test_out_of_order_days_are_rejected() -> None:
    daily = PeriodAggregator(Period.DAY)
    daily.add_day(date(2025, 6, 13), BAR)
    with pytest.raises(ValueError):
        daily.add_day(date(2025, 6, 12), BAR)


@pytest.mark.parametrize(
    ("day", "period", "same_as"),
    [
        (date(2025, 12, 29), Period.WEEK, date(2026, 1, 2)),  # ISO week spans the new year
        (date(2025, 6, 1), Period.MONTH, date(2025, 6, 30)),
        (date(2025, 1, 1), Period.YEAR, date(2025, 12, 31)),
    ],
)
def test_period_boundaries(day: date, period: Period, same_as: date) -> None:
    from app.strategy.periods import period_key

    assert period_key(day, period) == period_key(same_as, period)


def test_sma_is_na_until_full() -> None:
    sma = Sma(3)
    assert math.isnan(sma.update(1))
    assert math.isnan(sma.update(2))
    assert sma.update(3) == 2
    assert sma.update(6) == pytest.approx(11 / 3)


def test_rma_is_seeded_with_sma_then_smoothed() -> None:
    rma = Rma(2)
    assert math.isnan(rma.update(2))
    assert rma.update(4) == 3
    assert rma.update(6) == pytest.approx(0.5 * 6 + 0.5 * 3)


def test_ema_is_seeded_with_the_first_value() -> None:
    ema = Ema(3)
    assert ema.update(10) == 10
    assert ema.update(20) == pytest.approx(0.5 * 20 + 0.5 * 10)
