"""Reversal candles, trade direction and hot zones. All bars are hand-built test values."""

import math
from datetime import date

from app.strategy.hot_zones import detect_hot_zones, hot_zone_breakouts, is_near
from app.strategy.levels import PeriodBar, calculate_cpr
from app.strategy.periods import Period, PeriodAggregator
from app.strategy.reversal import Bar, ReversalDetector
from app.strategy.trade_direction import (
    AGG_FULL,
    AGG_NONE,
    AGG_SCALP,
    LOC_ABOVE_BOTH,
    LOC_BELOW_BOTH,
    MS_BEAR_FAILURE,
    MS_BULL_FAILURE,
    MS_STRONG_BULL,
    resolve_market_state,
    trade_direction,
)

NAN = math.nan


def run(bars: list[Bar], warmup: list[Bar] | None = None):
    detector = ReversalDetector()
    for bar in warmup or []:
        detector.update(bar)
    result = []
    for bar in bars:
        result = detector.update(bar)
    return result


def codes(signals) -> set[tuple[str, bool]]:
    return {(s.code, s.is_long) for s in signals}


def test_outside_reversal_long() -> None:
    two_back = Bar(100, 105, 95, 100)
    prev = Bar(96, 107, 94, 106)
    signals = run([two_back, prev, Bar(106, 108, 105, 107)])
    assert ("OR", True) in codes(signals)
    assert next(s for s in signals if s.code == "OR").signal_bar == prev


def test_outside_reversal_short_needs_lower_confirmation_close() -> None:
    two_back = Bar(100, 105, 95, 100)
    prev = Bar(104, 106, 93, 94)
    assert ("OR", False) in codes(run([two_back, prev, Bar(94, 95, 92, 93)]))
    assert ("OR", False) not in codes(run([two_back, prev, Bar(94, 96, 93, 95)]))


def test_doji_reversal_uses_the_previous_bars_average() -> None:
    warmup = [Bar(100, 101, 99, 100)] * 9
    prev = Bar(95, 96, 94, 95.05)  # body 0.05 of a 2.0 range
    signals = run([prev, Bar(95.1, 97.5, 95, 97)], warmup)
    assert ("DR", True) in codes(signals)


def test_doji_with_zero_range_is_not_a_signal() -> None:
    warmup = [Bar(100, 101, 99, 100)] * 9
    assert not codes(run([Bar(95, 95, 95, 95), Bar(95, 98, 95, 97)], warmup)) & {("DR", True)}


def test_wick_reversal_long() -> None:
    prev = Bar(100, 100.6, 95, 100.5)
    signals = run([prev, Bar(100.5, 101.5, 100.4, 101)])
    assert codes(signals) == {("WR", True)}
    assert signals[0].signal_bar == prev


def test_extreme_reversal_is_labelled_on_the_confirming_bar() -> None:
    warmup = [Bar(100, 100.5, 99.5, 100.2)] * 60  # average range 1.0, body 0.2
    big_red = Bar(110, 110.2, 105, 105.1)
    confirm = Bar(105.2, 106.5, 105.1, 106)
    signals = run([big_red, confirm], warmup)
    extreme = [s for s in signals if s.code == "ER"]
    assert len(extreme) == 1
    assert extreme[0].is_long
    assert extreme[0].signal_bar == confirm


def test_extreme_reversal_needs_fifty_bars_of_history() -> None:
    big_red = Bar(110, 110.2, 105, 105.1)
    assert ("ER", True) not in codes(run([big_red, Bar(105.2, 106.5, 105.1, 106)]))


def levels(prev_tc: float, prev_bc: float, bar: PeriodBar, session_open: float):
    return calculate_cpr(bar, session_open, prev_tc, prev_bc)


def test_strong_bull_trend_allows_longs_with_full_aggression() -> None:
    narrow = PeriodBar(100, 100.4, 99.8, 100.3)  # width under 0.25%
    day = levels(99.0, 98.5, narrow, 101)
    week = levels(99.0, 98.5, narrow, 101)
    td = trade_direction(day, week, 101)
    assert td.market_state == MS_STRONG_BULL
    assert td.allow_long and not td.allow_short
    assert td.aggression == AGG_FULL


def test_failure_states_take_precedence_in_the_resolver() -> None:
    assert resolve_market_state("BULL", "BEAR", LOC_BELOW_BOTH, True, False) == MS_BEAR_FAILURE
    assert resolve_market_state("BEAR", "BULL", LOC_ABOVE_BOTH, False, True) == MS_BULL_FAILURE


def test_sell_here_maps_to_bear_and_open_below_both_is_a_strong_bear_trend() -> None:
    narrow = PeriodBar(100, 100.4, 99.8, 100.3)
    trade = levels(99.0, 98.5, narrow, 90)  # higher relationship, open below BC: "Sell here"
    direction = levels(101.5, 101.0, narrow, 90)  # lower relationship, open below TC: "Bear Accept"
    assert trade.bias == "Sell here"
    assert direction.bias == "Bear Accept"
    td = trade_direction(trade, direction, 90)
    assert td.trade_bias == td.direction_bias == "BEAR"
    assert td.market_state == "STRONG_BEAR_TREND"
    assert td.allow_short


def test_missing_levels_fall_into_table_tennis_as_in_the_script() -> None:
    # An na CPR width is not below any threshold, so the script classifies it as
    # "Sideways Trading", which with a neutral state enables table tennis in both directions.
    empty = calculate_cpr(None, 100, NAN, NAN)
    td = trade_direction(empty, empty, 100)
    assert td.histogram == "Sideways Trading"
    assert td.table_tennis
    assert td.allow_long and td.allow_short
    assert td.aggression == AGG_SCALP
    assert td.aggression != AGG_NONE


def test_is_near_uses_percent_of_the_midpoint() -> None:
    assert is_near(100, 100.25, 0.25)
    assert not is_near(100, 100.3, 0.25)
    assert not is_near(NAN, 100, 0.25)


def test_hot_zone_scores_day_week_convergence() -> None:
    bar = PeriodBar(100, 110, 90, 105)
    aggregators = {p: PeriodAggregator(p) for p in Period}
    for aggregator in aggregators.values():
        aggregator.add_day(date(2025, 6, 13), bar)
    day, week, month, year = (aggregators[p].levels_for(date(2025, 6, 16), 104) for p in Period)
    zones = detect_hot_zones(day, week, month, year, 0.25, 2)
    # Day and week share the same prior bar, so every level converges. June has no completed
    # prior month or year, so those levels are na and add nothing.
    assert {z.level for z in zones} == {
        "PP", "TC", "BC", "R1", "S1", "CAM-H3", "CAM-L3", "CAM-H4", "CAM-L4"
    }  # fmt: skip
    assert all(z.score == 2 and z.description.endswith("Day+Week") for z in zones)
    assert math.isnan(month.cpr.tc)
    up, down = hot_zone_breakouts(zones, day.camarilla.h4, day.camarilla.l4, 117, 115)
    assert up and not down
