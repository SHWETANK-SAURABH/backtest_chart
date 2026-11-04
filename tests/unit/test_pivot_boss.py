"""Pivot Boss setups on hand-built candles (test data only, not market prices).

The daily candles are those of test_strategy_engine.py. With Friday's close at 102, Monday has:
- CPR 100 to 101.33, R1 106.33, R2 110.67, S1 96.33, S2 90.67.
- Camarilla H3 104.75, H4 107.5, H5 112.74, L3 99.25, L4 96.5.
- Daily bias -1 for Monday and Friday (each prior close below its own CPR); relationship lower.
- No weekly bias (two earlier weeks are needed), so the weekly filter allows both sides.
"""

from datetime import date

import polars as pl
import pytest

from app.domain.enums import DecisionAction
from app.strategy.parameters import StrategyOptions, StrategyParameters
from app.strategy.runner import evaluate
from tests.unit.test_strategy_engine import MONDAY, WEEK_BEFORE, intraday_frame

SELL, BUY, HOLD = DecisionAction.SELL, DecisionAction.BUY, DecisionAction.HOLD


def book(**options) -> StrategyParameters:
    return StrategyOptions(strategy="pivot_boss", **options).apply(StrategyParameters())


def daily(monday_open: float = 100.5, friday_close: float = 102) -> pl.DataFrame:
    week = [*WEEK_BEFORE[:-1], (date(2025, 6, 13), 104, 105, 95, friday_close)]
    rows = [*week, (MONDAY, monday_open, 102, 99.5, 101.5)]
    return pl.DataFrame(rows, schema=["trading_date", "open", "high", "low", "close"], orient="row")


# An outside reversal short whose signal candle pokes into the CPR (BC 100) and closes below it.
SHORT_AT_CPR = [
    (99.8, 100.0, 99.6, 99.9),
    (99.9, 100.4, 99.3, 99.4),
    (99.4, 99.5, 99.0, 99.1),
]


def test_context_records_the_book_biases() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book())[0]
    pivot_boss = decision.context["pivot_boss"]
    assert pivot_boss["daily_bias"] == -1
    assert pivot_boss["previous_daily_bias"] == -1
    assert pivot_boss["weekly_bias"] == 0
    assert pivot_boss["open_rejects_bias"] is False


def test_cpr_pullback_short_with_a_confirmed_bearish_bias() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book())[2]
    assert decision.action == SELL
    assert decision.reason_codes == [
        "CPR_PULLBACK_SHORT",
        "TRIGGER_OR",
        "TARGET_S1",
        "EXIT_FIXED_TARGET",
    ]
    assert decision.signal is not None
    assert decision.signal.stop_loss == pytest.approx(101.3333333)  # beyond the far side, TC
    assert decision.signal.target == pytest.approx(96.3333333)
    assert decision.signal.patterns == ["CPR_PULLBACK"]


def test_the_cpr_pullback_is_a_morning_trade() -> None:
    late = intraday_frame([(99.5, 99.6, 99.4, 99.5)] * 30 + SHORT_AT_CPR)
    decisions = evaluate(late, daily(), book(book_setups=("CPR_PULLBACK",)))
    assert decisions[-1].action == HOLD


def test_floor_pivot_short_in_an_established_downtrend() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book(book_setups=("FLOOR_PIVOT",)))[
        2
    ]
    assert decision.action == SELL
    assert decision.reason_codes[0] == "FLOOR_PIVOT_SHORT"
    assert decision.signal is not None
    assert decision.signal.target == pytest.approx(96.3333333)


def test_a_rejected_open_fades_the_cpr_with_the_reversal_candle_as_stop() -> None:
    # Bearish bias, but Monday opens at 102, above TC: the open rejects it.
    bars = [
        (101.8, 102.0, 101.6, 101.7),
        (101.7, 102.2, 101.2, 102.1),  # outside reversal long dipping into TC (101.33)
        (102.1, 102.5, 102.0, 102.4),
    ]
    decisions = evaluate(intraday_frame(bars), daily(monday_open=102), book())
    assert decisions[0].context["pivot_boss"]["open_rejects_bias"] is True
    decision = decisions[2]
    assert decision.action == BUY
    assert decision.reason_codes[0] == "CPR_FADE_LONG"
    assert decision.signal is not None
    assert decision.signal.stop_loss == 101.2  # the reversal candle's low
    assert decision.signal.target == pytest.approx(106.3333333)  # R1


def test_camarilla_h3_reversal_needs_a_confirming_candle() -> None:
    bars = [
        (103.5, 104.0, 103.4, 103.9),
        (103.9, 105.0, 103.8, 104.2),  # wick through H3 (104.75), closes back below
        (104.2, 104.5, 103.5, 103.6),  # stays below H3 and closes below the prior close
    ]
    decisions = evaluate(intraday_frame(bars), daily(), book(book_setups=("CAM_REVERSAL",)))
    assert decisions[1].action == HOLD  # not on the wick candle itself
    assert decisions[2].action == SELL
    assert decisions[2].signal is not None
    assert decisions[2].signal.stop_loss == pytest.approx(107.5)  # H4
    assert decisions[2].signal.target == pytest.approx(99.25)  # L3


def test_camarilla_breakout_waits_for_a_close_above_the_earlier_tests() -> None:
    bars = [
        (106.5, 107.0, 106.4, 106.9),
        (106.9, 107.7, 106.8, 107.2),  # tests H4 (107.5) and fails
        (107.2, 107.4, 107.0, 107.3),
        (107.3, 107.8, 107.2, 107.6),  # closes above H4 but not above the test's high 107.7
        (107.6, 108.0, 107.5, 107.9),
    ]
    decisions = evaluate(intraday_frame(bars), daily(), book(book_setups=("CAM_BREAKOUT",)))
    assert [d.action for d in decisions] == [HOLD, HOLD, HOLD, HOLD, HOLD]
    bars[3] = (107.3, 108.0, 107.2, 107.9)  # now the first close above H4 clears 107.7
    decisions = evaluate(intraday_frame(bars), daily(), book(book_setups=("CAM_BREAKOUT",)))
    assert decisions[3].action == BUY
    assert decisions[3].signal is not None
    assert decisions[3].signal.stop_loss == pytest.approx(104.75)  # H3
    assert decisions[3].signal.target == pytest.approx(112.7368421)  # H5


def test_breakaway_on_a_narrow_cpr_gap_day() -> None:
    # Friday close 100.3: CPR 100 to 100.2 (Trending), R1 105.2, R2 110.1, R3 115.2, prior high 105.
    bars = [(106.0, 106.5, 105.0, 106.2), (106.2, 106.8, 106.0, 106.6)]
    decisions = evaluate(intraday_frame(bars), daily(monday_open=106, friday_close=100.3), book())
    decision = decisions[0]
    assert decision.action == BUY
    assert decision.reason_codes == ["BREAKAWAY_LONG", "TARGET_R3", "EXIT_ATR_TRAIL"]
    assert decision.signal is not None
    assert decision.signal.stop_loss == 105.0  # the day's low
    assert decision.signal.target == pytest.approx(115.2)
    # Only the first candle can start a breakaway.
    assert decisions[1].action == HOLD


def test_breakaway_needs_a_narrow_cpr() -> None:
    bars = [(106.0, 106.5, 105.0, 106.2)]
    # Friday close 102 gives a 1.32% wide CPR: Sideways Trading.
    decision = evaluate(intraday_frame(bars), daily(monday_open=106), book())[0]
    assert "BREAKAWAY_LONG" not in decision.reason_codes


def test_book_options_validate() -> None:
    assert StrategyOptions(book_setups=("CAM_BREAKOUT", "MAGNET")).book_setups == (
        "MAGNET",
        "CAM_BREAKOUT",
    )
    with pytest.raises(ValueError, match="at least one"):
        StrategyOptions(book_setups=())
    with pytest.raises(ValueError, match="Unknown"):
        StrategyOptions(book_setups=("XX",))


# Full trend analysis. On the fixture Monday the relationship is Lower Value and the open (100.5)
# is below TC, so the day is shorts only. The S1/R1 trend turned down when Wednesday closed at 110,
# below its S1 (111.67), and no later close went above R1. The weekly trend is neutral.


def test_trend_analysis_context() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book(trend_analysis=True))[0]
    assert decision.context["pivot_boss"]["trend"] == {
        "day_sides": ["short"],
        "strong_signal_side": None,
        "awaiting_cpr_break": False,
        "pivot_trend": "short",
        "weekly_trend": None,
    }


def test_trend_analysis_lets_a_with_trend_setup_through() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book(trend_analysis=True))[2]
    assert decision.action == SELL
    assert decision.reason_codes[0] == "CPR_PULLBACK_SHORT"


def test_a_rejecting_open_flips_the_day_but_the_pivot_trend_must_agree() -> None:
    bars = [
        (101.8, 102.0, 101.6, 101.7),
        (101.7, 102.2, 101.2, 102.1),
        (102.1, 102.5, 102.0, 102.4),
    ]
    decisions = evaluate(intraday_frame(bars), daily(monday_open=102), book(trend_analysis=True))
    # Lower Value opening above TC: the day flips to longs.
    assert decisions[0].context["pivot_boss"]["trend"]["day_sides"] == ["long"]
    # The CPR fade long matches the day, but the S1/R1 trend is still down.
    assert decisions[2].action == HOLD
    assert decisions[2].reason_codes == ["AGAINST_PIVOT_TREND"]


def test_an_outside_value_day_allows_both_sides() -> None:
    rows = [*WEEK_BEFORE[:-1], (date(2025, 6, 13), 104, 111, 97, 110), (MONDAY, 105, 106, 104, 105)]
    frame = pl.DataFrame(
        rows, schema=["trading_date", "open", "high", "low", "close"], orient="row"
    )
    decision = evaluate(intraday_frame(SHORT_AT_CPR), frame, book(trend_analysis=True))[0]
    assert decision.context["pivot_boss"]["trend"]["day_sides"] == ["long", "short"]


def test_camarilla_pattern_on_a_wide_day_targets_the_opposite_level() -> None:
    bars = [
        (104.2, 104.4, 104.0, 104.3),
        (104.3, 104.9, 103.8, 103.9),  # outside reversal short poking through H3 (104.75)
        (103.9, 104.0, 103.6, 103.7),
    ]
    decision = evaluate(intraday_frame(bars), daily(), book(book_setups=("CAM_PATTERN",)))[2]
    assert decision.action == SELL
    assert decision.reason_codes == [
        "CAM_PATTERN_SHORT",
        "TRIGGER_OR",
        "TARGET_L3",
        "EXIT_FIXED_TARGET",
    ]
    assert decision.signal is not None
    assert decision.signal.stop_loss == pytest.approx(107.5)  # H4


def test_camarilla_pattern_on_a_narrow_day_trails_with_the_ema() -> None:
    # Friday close 100.3: Trending CPR; H3 103.05, H4 105.8.
    bars = [
        (102.5, 102.7, 102.3, 102.6),
        (102.6, 103.2, 102.1, 102.2),
        (102.2, 102.3, 101.9, 102.0),
    ]
    decision = evaluate(
        intraday_frame(bars), daily(friday_close=100.3), book(book_setups=("CAM_PATTERN",))
    )[2]
    assert decision.action == SELL
    assert decision.reason_codes == ["CAM_PATTERN_SHORT", "TRIGGER_OR", "EXIT_EMA_TRAIL"]
    assert decision.signal is not None
    assert decision.signal.target is None
    assert decision.signal.stop_loss == pytest.approx(105.8)  # H4


def test_person_plan_sells_the_cpr_in_the_s1_r1_downtrend() -> None:
    decision = evaluate(intraday_frame(SHORT_AT_CPR), daily(), book(book_setups=("PERSON_PLAN",)))[
        2
    ]
    assert decision.action == SELL
    assert decision.reason_codes[0] == "PERSON_PLAN_SHORT"
    assert decision.signal is not None
    assert decision.signal.stop_loss == pytest.approx(101.3333333)  # TC
    assert decision.signal.target == pytest.approx(96.3333333)  # S1


def test_clear_trend_only_blocks_trend_setups_without_a_weekly_trend() -> None:
    # The weekly trend is neutral on the fixture, so the trend is not clear.
    blocked = evaluate(
        intraday_frame(SHORT_AT_CPR), daily(), book(clear_trend=True, book_setups=("CPR_PULLBACK",))
    )[2]
    assert blocked.reason_codes == ["TREND_NOT_CLEAR"]
    # Range setups are not trend setups, so they still trade.
    bars = [
        (103.5, 104.0, 103.4, 103.9),
        (103.9, 105.0, 103.8, 104.2),
        (104.2, 104.5, 103.5, 103.6),
    ]
    reversal = evaluate(
        intraday_frame(bars), daily(), book(clear_trend=True, book_setups=("CAM_REVERSAL",))
    )[2]
    assert reversal.action == SELL


def test_trend_change_after_a_strong_down_day() -> None:
    # Friday closed at the lowest of the last 5 closes (102) with a range of 10, above ADR(3) 8.67.
    parameters = StrategyOptions(strategy="pivot_boss", book_setups=("TREND_CHANGE",)).apply(
        StrategyParameters(adr_length=3)
    )
    bars = [
        (99.7, 99.8, 99.5, 99.6),
        (99.6, 100.5, 99.4, 99.5),  # wick reversal short reaching BC (100)
        (99.5, 99.6, 99.2, 99.3),
    ]
    decisions = evaluate(intraday_frame(bars), daily(), parameters)
    assert decisions[0].context["pivot_boss"]["strong_day"] == "short"
    assert decisions[2].action == SELL
    assert decisions[2].reason_codes == [
        "TREND_CHANGE_SHORT",
        "TRIGGER_WR",
        "TARGET_S1",
        "EXIT_FIXED_TARGET",
    ]
    assert decisions[2].signal is not None
    assert decisions[2].signal.stop_loss == 100.5  # the wick candle's high
    assert decisions[2].signal.target == pytest.approx(96.3333333)


def test_no_trend_change_without_a_strong_day() -> None:
    bars = [
        (99.7, 99.8, 99.5, 99.6),
        (99.6, 100.5, 99.4, 99.5),
        (99.5, 99.6, 99.2, 99.3),
    ]
    # ADR(10) needs 10 days of history, which the fixture lacks.
    decisions = evaluate(intraday_frame(bars), daily(), book(book_setups=("TREND_CHANGE",)))
    assert decisions[0].context["pivot_boss"]["strong_day"] is None
    assert decisions[2].action == HOLD
