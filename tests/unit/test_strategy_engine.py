"""MTZ reversal decisions on hand-built candles (test data only, not market prices).

Setup used throughout:
- Week of 2025-06-09: Monday high 130, Friday low 95 and close 102. Weekly MTZ for the week of
  2025-06-16 is 105.5 to 112.5.
- Friday 2025-06-13: high 105, low 95, close 102. Daily MTZ for Monday 2025-06-16 is 100 to 101.33.
"""

from datetime import date, datetime, timedelta

import polars as pl
import pytest

from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DecisionAction
from app.strategy.parameters import MtzChoice, StrategyOptions, StrategyParameters
from app.strategy.runner import code_hash, evaluate

MONDAY = date(2025, 6, 16)
WEEK_BEFORE = [
    (date(2025, 6, 9), 120, 130, 110, 118),
    (date(2025, 6, 10), 118, 119, 112, 115),
    (date(2025, 6, 11), 115, 116, 108, 110),
    (date(2025, 6, 12), 110, 111, 103, 104),
    (date(2025, 6, 13), 104, 105, 95, 102),
]


def daily_frame(extra: list[tuple] | None = None, friday_close: float = 102) -> pl.DataFrame:
    """Friday's close sets Monday's daily CPR width: 102 gives 1.32% (Sideways Trading),
    100.9 gives 0.60% (Sideways) and 100.3 gives 0.20% (Trending)."""
    week = [*WEEK_BEFORE[:-1], (*WEEK_BEFORE[-1][:4], friday_close)]
    rows = [*week, (MONDAY, 100.5, 102, 99.5, 101.5), *(extra or [])]
    return pl.DataFrame(rows, schema=["trading_date", "open", "high", "low", "close"], orient="row")


def with_options(**options) -> StrategyParameters:
    return StrategyOptions(**options).apply(StrategyParameters())


def intraday_frame(
    bars: list[tuple[float, float, float, float]], day: date = MONDAY
) -> pl.DataFrame:
    start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=EXCHANGE_TZ)
    return pl.DataFrame(
        {
            "trading_date": [day] * len(bars),
            "timestamp": [start + timedelta(minutes=5 * i) for i in range(len(bars))],
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
        }
    )


LONG_AT_DAILY_MTZ = [
    (100.5, 101.0, 100.2, 100.6),
    (100.3, 101.3, 100.0, 101.2),  # outside bar touching the daily MTZ
    (101.2, 101.6, 101.1, 101.5),  # confirmation
]


def test_levels_come_from_the_previous_day_and_week() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())[0]
    daily = decision.context["cpr_daily"]
    weekly = decision.context["cpr_weekly"]
    assert daily["bc"] == pytest.approx(100.0)
    assert daily["tc"] == pytest.approx(101.3333333)
    assert weekly["bc"] == pytest.approx(105.5)
    assert weekly["tc"] == pytest.approx(112.5)
    assert decision.context["session_open"] == 100.5
    assert decision.context["session_open_source"] == "daily_candle"


def test_reversal_at_daily_mtz_buys_toward_the_weekly_mtz() -> None:
    decisions = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())
    assert [d.action for d in decisions] == [
        DecisionAction.HOLD,
        DecisionAction.HOLD,
        DecisionAction.BUY,
    ]
    signal = decisions[2].signal
    assert signal is not None
    assert signal.side == "long"
    assert signal.patterns == ["OR"]
    assert signal.touched_zones == ["daily_mtz"]
    assert signal.stop_loss == 100.0  # the outside bar's low
    assert signal.target == pytest.approx(105.5)  # weekly MTZ near edge
    assert signal.target_zone == "weekly_mtz"
    assert decisions[2].reason_codes == [
        "OR_LONG",
        "AT_DAILY_MTZ",
        "TARGET_WEEKLY_MTZ",
        "EXIT_MTZ_TARGET",
    ]
    assert signal.exit_mode == "EXIT_MTZ_TARGET"
    assert "Outside reversal (long) confirmed." in decisions[2].explanation
    assert "Stop 100.00, target 105.50." in decisions[2].explanation


def test_short_with_no_mtz_below_is_not_taken() -> None:
    bars = [
        (101.0, 101.2, 100.8, 101.0),
        (101.1, 101.3, 100.5, 100.6),  # outside bar touching the daily MTZ
        (100.6, 100.7, 100.3, 100.4),
    ]
    decision = evaluate(intraday_frame(bars), daily_frame())[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes[0] == "NO_TARGET_ZONE"
    assert "OR_SHORT" in decision.reason_codes


def test_reversal_away_from_any_mtz_is_not_taken() -> None:
    bars = [
        (103.0, 103.5, 102.7, 103.0),
        (102.8, 103.8, 102.5, 103.7),
        (103.7, 104.0, 103.6, 103.9),
    ]
    decision = evaluate(intraday_frame(bars), daily_frame())[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["REVERSAL_NOT_AT_MTZ", "OR_LONG"]


def test_bars_without_a_signal_hold_with_a_reason() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ[:1]), daily_frame())[0]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["NO_REVERSAL_SIGNAL"]
    assert decision.explanation == "No reversal candle confirmed on this bar."


def test_without_history_there_are_no_levels() -> None:
    daily = pl.DataFrame(
        [(MONDAY, 100.5, 102, 99.5, 101.5)],
        schema=["trading_date", "open", "high", "low", "close"],
        orient="row",
    )
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily)[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["NO_MTZ_LEVELS"]
    assert decision.context["cpr_daily"]["tc"] is None


def test_missing_daily_candle_falls_back_to_first_bar_open() -> None:
    daily = daily_frame().filter(pl.col("trading_date") != MONDAY)
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily)[0]
    assert decision.context["session_open"] == 100.5
    assert decision.context["session_open_source"] == "first_intraday_bar"


def test_decisions_never_depend_on_later_data() -> None:
    bars = [*LONG_AT_DAILY_MTZ, (101.5, 102.0, 101.0, 101.8), (101.8, 101.9, 99.0, 99.2)]
    full = evaluate(intraday_frame(bars), daily_frame())

    for cut in range(1, len(bars)):
        prefix = evaluate(intraday_frame(bars[:cut]), daily_frame())
        assert [d.reason_codes for d in prefix] == [d.reason_codes for d in full[:cut]]

    # Wildly different future sessions change nothing on Monday.
    future = [(date(2025, 6, 17), 50, 500, 1, 400), (date(2025, 6, 18), 400, 900, 300, 350)]
    with_future = evaluate(intraday_frame(bars), daily_frame(future))
    assert [(d.action, d.reason_codes, d.context) for d in with_future] == [
        (d.action, d.reason_codes, d.context) for d in full
    ]


def test_todays_daily_high_and_low_are_not_used_before_the_close() -> None:
    altered = daily_frame().with_columns(
        pl.when(pl.col("trading_date") == MONDAY)
        .then(999.0)
        .otherwise(pl.col("high"))
        .alias("high")
    )
    original = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())
    changed = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), altered)
    assert [d.context for d in original] == [d.context for d in changed]


def test_adr_usage_uses_the_range_so_far() -> None:
    decisions = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())
    assert [d.context["adr"]["current_range"] for d in decisions] == pytest.approx([0.8, 1.3, 1.6])
    # Five completed sessions are fewer than the 10-day ADR length.
    assert decisions[0].context["adr"]["value"] is None


def test_results_are_deterministic() -> None:
    first = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())
    second = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame())
    assert [(d.action, d.reason_codes, d.context) for d in first] == [
        (d.action, d.reason_codes, d.context) for d in second
    ]


def test_multi_day_runs_feed_each_daily_candle_after_its_session() -> None:
    tuesday = date(2025, 6, 17)
    bars = intraday_frame(LONG_AT_DAILY_MTZ)
    frame = pl.concat([bars, intraday_frame(LONG_AT_DAILY_MTZ, tuesday)])
    daily = daily_frame([(tuesday, 101.0, 103, 100, 102)])
    decisions = evaluate(frame, daily)
    tuesday_levels = decisions[3].context["cpr_daily"]
    # Tuesday's levels come from Monday's daily candle: high 102, low 99.5.
    assert tuesday_levels["ph"] == 102
    assert tuesday_levels["pl"] == 99.5


def test_a_session_cannot_start_after_its_own_daily_candle_was_added() -> None:
    from app.strategy.engine import MtzReversalStrategy, SessionInfo
    from app.strategy.levels import PeriodBar

    strategy = MtzReversalStrategy()
    strategy.add_completed_session(MONDAY, PeriodBar(100, 102, 99, 101))
    with pytest.raises(ValueError, match="would see"):
        strategy.start_session(SessionInfo(MONDAY, 100, "daily_candle"))
    with pytest.raises(ValueError, match="date order"):
        strategy.add_completed_session(MONDAY, PeriodBar(100, 102, 99, 101))


def test_code_hash_is_stable_and_well_formed() -> None:
    assert code_hash() == code_hash()
    assert len(code_hash()) == 64


def test_cpr_histogram_of_each_fixture() -> None:
    for close, histogram in ((102, "Sideways Trading"), (100.9, "Sideways"), (100.3, "Trending")):
        decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(friday_close=close))[0]
        assert decision.context["cpr_daily"]["histogram"] == histogram


def test_trending_cpr_trails_with_the_ema_and_has_no_target() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(friday_close=100.3))[2]
    assert decision.action == DecisionAction.BUY
    assert decision.signal is not None
    assert decision.signal.target is None
    assert decision.signal.target_zone is None
    assert decision.signal.exit_mode == "EXIT_EMA_TRAIL"
    assert decision.reason_codes == ["OR_LONG", "AT_DAILY_MTZ", "EXIT_EMA_TRAIL"]
    assert "target none" in decision.explanation


def test_sideways_cpr_means_no_trades_that_day() -> None:
    decision = evaluate(intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(friday_close=100.9))[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["CPR_SIDEWAYS_NO_TRADE", "OR_LONG"]


def test_no_entries_after_price_touches_r2_or_s2() -> None:
    # Monday's daily R2 is 110.67 and S2 is 90.67 (pivot 100.67, Friday's range 10).
    for touch in ((100.5, 111.0, 100.4, 100.5), (100.5, 100.6, 90.0, 100.5)):
        decisions = evaluate(intraday_frame([touch, *LONG_AT_DAILY_MTZ]), daily_frame())
        assert decisions[3].action == DecisionAction.HOLD
        assert decisions[3].reason_codes == ["R2_S2_REACHED", "OR_LONG"]


def test_only_chosen_patterns_can_enter() -> None:
    decision = evaluate(
        intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), with_options(entry_patterns=("DR", "WR"))
    )[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["NO_REVERSAL_SIGNAL"]
    # The candle itself is still recorded as an outside reversal.
    assert decision.context["reversal_signals"] == [{"code": "OR", "side": "long"}]


def test_daily_only_enters_at_the_daily_mtz_and_targets_the_weekly() -> None:
    decision = evaluate(
        intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), with_options(mtz=MtzChoice.DAILY)
    )[2]
    assert decision.action == DecisionAction.BUY
    assert decision.signal is not None
    assert decision.signal.target_zone == "weekly_mtz"


def test_weekly_only_ignores_reversals_at_the_daily_mtz() -> None:
    decision = evaluate(
        intraday_frame(LONG_AT_DAILY_MTZ), daily_frame(), with_options(mtz=MtzChoice.WEEKLY)
    )[2]
    assert decision.action == DecisionAction.HOLD
    assert decision.reason_codes == ["REVERSAL_NOT_AT_MTZ", "OR_LONG"]


def test_strategy_options_validate_and_normalise_patterns() -> None:
    assert StrategyOptions(entry_patterns=("WR", "OR")).entry_patterns == ("OR", "WR")
    with pytest.raises(ValueError, match="at least one"):
        StrategyOptions(entry_patterns=())
    with pytest.raises(ValueError, match="Unknown"):
        StrategyOptions(entry_patterns=("XX",))
