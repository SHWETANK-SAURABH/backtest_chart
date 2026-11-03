"""Execution rules, driven by scripted decisions on hand-built candles (test values only)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pytest

from app.backtesting.engine import BacktestEngine
from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import DecisionAction, ExecutionMethod
from app.strategy.engine import Decision, EntrySignal

DAY = date(2025, 6, 16)
NEXT_DAY = date(2025, 6, 17)
CLOSE_FILL = ExecutionSettings(method=ExecutionMethod.SIGNAL_CLOSE)
OPEN_FILL = ExecutionSettings(method=ExecutionMethod.NEXT_OPEN)


@dataclass
class Step:
    decision: Decision
    final_bar_of_session: bool = False


def time(index: int, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, 9, 15, tzinfo=EXCHANGE_TZ) + timedelta(
        minutes=5 * index
    )


def bar(
    index: int,
    o: float,
    h: float,
    low: float,
    c: float,
    action: DecisionAction = DecisionAction.HOLD,
    stop: float = 98.0,
    target: float | None = 104.0,
    day: date = DAY,
    final: bool = False,
    ema: float | None = None,
) -> Step:
    signal = None
    if action != DecisionAction.HOLD:
        side = "long" if action == DecisionAction.BUY else "short"
        trail = target is None
        signal = EntrySignal(
            side,
            ["OR"],
            ["daily_mtz"],
            h,
            low,
            stop,
            target,
            None if trail else "weekly_mtz",
            "EXIT_EMA_TRAIL" if trail else "EXIT_MTZ_TARGET",
        )
    codes = ["TEST_SIGNAL"] if signal else ["NO_REVERSAL_SIGNAL"]
    decision = Decision(
        time(index, day),
        day,
        o,
        h,
        low,
        c,
        action,
        codes,
        "test",
        signal,
        {"i": index, "ema_fast": ema},
    )
    return Step(decision, final)


BUY = DecisionAction.BUY
SELL = DecisionAction.SELL


def run(steps: list[Step], execution=CLOSE_FILL, risk=None, trade_from=None, minutes=5):
    engine = BacktestEngine(execution, risk, bar=timedelta(minutes=minutes))
    return engine.run(steps, trade_from=trade_from)


def test_long_target_hit_at_target_price() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 105, 99.5, 104.5)])
    [trade] = result.trades
    assert (trade.entry_price, trade.exit_price, trade.exit_reason) == (100, 104, "TARGET")
    assert trade.gross_points == 4
    assert trade.net_points == 4
    assert trade.cost_points == 0
    assert trade.entry_time == time(1)  # the signal candle's close
    assert trade.exit_time == time(2)  # the close of the candle that touched the target
    assert result.records[0].trade_opened
    assert result.records[0].position_state == "long"
    assert result.records[1].position_closed
    assert result.records[1].position_state == "flat"
    assert result.equity == [(time(2), 4.0)]


def test_signal_close_never_checks_the_signal_candle_itself() -> None:
    # The signal candle's low is below the stop, but the entry happened at its close.
    result = run([bar(0, 99, 100.5, 97, 100, BUY), bar(1, 100, 101, 99, 100.5)])
    assert result.trades == [] or result.trades[0].exit_reason == "END_OF_DATA"


def test_slippage_worsens_entry_and_stop_exit() -> None:
    execution = ExecutionSettings(method=ExecutionMethod.SIGNAL_CLOSE, slippage_points=0.5)
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 100.2, 97, 97.5)], execution)
    [trade] = result.trades
    assert trade.entry_price == 100.5
    assert trade.exit_price == 97.5
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.gross_points == -3.0


def test_target_exit_gets_no_slippage() -> None:
    execution = ExecutionSettings(method=ExecutionMethod.SIGNAL_CLOSE, slippage_points=0.5)
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 105, 99.5, 104.5)], execution)
    assert result.trades[0].exit_price == 104


def test_stop_and_target_in_one_candle_assumes_the_stop() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 105, 97, 101)])
    [trade] = result.trades
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == 98
    assert trade.notes == ["SAME_CANDLE_AMBIGUITY"]
    assert "STOP_AND_TARGET_SAME_CANDLE_STOP_ASSUMED" in result.records[1].execution_notes


def test_open_beyond_stop_exits_at_the_open() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 96, 97, 95, 96.5)])
    [trade] = result.trades
    assert (trade.exit_reason, trade.exit_price, trade.exit_time) == ("STOP_LOSS_GAP", 96, time(1))


def test_open_beyond_target_fills_at_the_open() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 106, 107, 105, 106)])
    assert (result.trades[0].exit_reason, result.trades[0].exit_price) == ("TARGET_GAP", 106)


def test_short_trades_are_mirrored() -> None:
    steps = [bar(0, 101, 101.5, 99.5, 100, SELL, stop=102, target=96), bar(1, 100, 100.5, 95, 95.5)]
    [trade] = run(steps).trades
    assert (trade.side, trade.exit_price, trade.gross_points) == ("short", 96, 4)


def test_next_open_entry_fills_at_the_next_candles_open() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 101, 104.5, 100.5, 104)], OPEN_FILL)
    [trade] = result.trades
    assert trade.entry_price == 101
    assert trade.entry_time == time(1)
    assert trade.exit_reason == "TARGET"  # the entry candle itself can reach the target
    assert "ENTRY_PENDING_NEXT_OPEN" in result.records[0].execution_notes
    assert not result.records[0].trade_opened
    assert result.records[1].trade_opened


@pytest.mark.parametrize(
    ("open_price", "note"),
    [(97.5, "ENTRY_SKIPPED_OPEN_BEYOND_STOP"), (104.5, "ENTRY_SKIPPED_OPEN_BEYOND_TARGET")],
)
def test_next_open_entry_is_skipped_when_the_open_has_passed_a_level(open_price, note) -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, open_price, 105, 97, 100)], OPEN_FILL)
    assert result.trades == []
    assert note in result.records[1].execution_notes


def test_position_is_squared_off_at_the_session_close() -> None:
    steps = [bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 101, 99.5, 100.8, final=True)]
    [trade] = run(steps).trades
    assert (trade.exit_reason, trade.exit_price, trade.exit_time) == (
        "EOD_SQUARE_OFF",
        100.8,
        time(2),
    )


@pytest.mark.parametrize("execution", [CLOSE_FILL, OPEN_FILL])
def test_no_entry_on_the_final_candle(execution) -> None:
    result = run(
        [bar(0, 99, 100.5, 98.5, 100, BUY, final=True), bar(0, 100, 101, 99, 100, day=NEXT_DAY)],
        execution,
    )
    assert result.trades == []
    assert "SIGNAL_IGNORED_SESSION_CLOSING" in result.records[0].execution_notes


def test_missing_final_candle_still_prevents_overnight_holding() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 101, 99.5, 100.6),
        bar(0, 103, 104, 102, 103, day=NEXT_DAY),
    ]
    result = run(steps)
    [trade] = result.trades
    assert trade.exit_reason == "SESSION_END_MISSING_DATA"
    assert trade.exit_price == 100.6
    assert trade.exit_time == time(2)
    assert result.records[1].position_state == "flat"
    assert result.records[2].position_state == "flat"


def test_pending_entry_does_not_carry_into_the_next_session() -> None:
    steps = [bar(0, 99, 100.5, 98.5, 100, BUY), bar(0, 100, 101, 99, 100.5, day=NEXT_DAY)]
    result = run(steps, OPEN_FILL)
    assert result.trades == []
    assert "PENDING_ENTRY_CANCELLED_NEW_SESSION" in result.records[1].execution_notes


def test_one_position_at_a_time() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 101, 99.5, 100.5, BUY),
        bar(2, 100.5, 101, 99.5, 100.2, SELL, stop=102, target=96),
        bar(3, 100, 105, 99.5, 104.5),
    ]
    result = run(steps)
    assert len(result.trades) == 1
    assert "SIGNAL_IGNORED_POSITION_OPEN" in result.records[1].execution_notes
    assert "SIGNAL_IGNORED_POSITION_OPEN" in result.records[2].execution_notes


def test_new_entry_is_allowed_after_an_exit_on_the_same_candle() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 105, 99.5, 104.5, BUY, stop=103, target=108),
        bar(2, 104.5, 108.5, 104, 108),
    ]
    result = run(steps)
    assert [t.exit_reason for t in result.trades] == ["TARGET", "TARGET"]
    assert result.records[1].position_closed and result.records[1].trade_opened


def test_daily_trade_limit() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 105, 99.5, 104.5),
        bar(2, 104, 104.5, 103, 104, BUY, stop=102, target=108),
    ]
    result = run(steps, risk=RiskSettings(max_trades_per_day=1))
    assert len(result.trades) == 1
    assert "SIGNAL_IGNORED_DAILY_TRADE_LIMIT" in result.records[2].execution_notes


def test_daily_loss_limit_resets_next_session() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 100.2, 97, 97.5),  # loses 2 points
        bar(2, 97.5, 98, 97, 97.8, BUY, stop=96, target=100),
        bar(0, 99, 100.5, 98.5, 100, BUY, day=NEXT_DAY),
    ]
    result = run(steps, risk=RiskSettings(max_daily_loss_points=2))
    assert "SIGNAL_IGNORED_DAILY_LOSS_LIMIT" in result.records[2].execution_notes
    assert result.records[3].trade_opened


def test_open_position_at_end_of_data_is_closed_and_flagged() -> None:
    [trade] = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 101, 99.5, 100.4)]).trades
    assert (trade.exit_reason, trade.exit_price) == ("END_OF_DATA", 100.4)


def test_candles_before_the_start_date_only_warm_up() -> None:
    steps = [bar(0, 99, 100.5, 98.5, 100, BUY, day=DAY), bar(0, 100, 101, 99, 100.5, day=NEXT_DAY)]
    result = run(steps, trade_from=NEXT_DAY)
    assert result.trades == []
    assert [r.decision.trading_date for r in result.records] == [NEXT_DAY]


def test_results_are_deterministic_and_hashed() -> None:
    steps = [bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 105, 99.5, 104.5)]
    assert run(steps).result_hash() == run(steps).result_hash()
    # A lower high misses the target, so the trade ends differently.
    changed = [steps[0], bar(1, 100, 103, 99.5, 102.5)]
    assert run(changed).result_hash() != run(steps).result_hash()


def test_trades_closed_before_a_cut_do_not_depend_on_later_candles() -> None:
    steps = [
        bar(0, 99, 100.5, 98.5, 100, BUY),
        bar(1, 100, 105, 99.5, 104.5),
        bar(2, 104, 104.5, 103, 104, SELL, stop=106, target=100),
        bar(3, 104, 104.2, 99, 99.5),
    ]
    assert run(steps[:2]).trades == run(steps).trades[:1]


def test_assumptions_label_signal_close_as_idealised_and_units_as_points() -> None:
    assumptions = BacktestEngine(CLOSE_FILL).assumptions()
    assert assumptions["signal_close_is_idealised"] is True
    assert "not rupees" in assumptions["units"]
    assert BacktestEngine(OPEN_FILL).assumptions()["signal_close_is_idealised"] is False


def test_trailing_long_exits_on_a_red_candle_closing_below_the_ema() -> None:
    result = run(
        [
            bar(0, 99, 100.5, 98.5, 100, BUY, target=None, ema=99.5),
            bar(1, 100, 103, 99.8, 102.5, ema=100.5),  # green, above the EMA: hold
            bar(2, 102.5, 104, 101.5, 101.8, ema=102.0),  # red, closes below the EMA: exit
            bar(3, 101.8, 102, 100, 100.5, ema=101.5),
        ]
    )
    [trade] = result.trades
    assert trade.exit_reason == "EMA_TRAIL_EXIT"
    assert trade.exit_price == 101.8  # the red candle's close
    assert trade.exit_time == time(3)
    assert trade.target is None


def test_trailing_long_ignores_a_red_candle_closing_above_the_ema() -> None:
    result = run(
        [
            bar(0, 99, 100.5, 98.5, 100, BUY, target=None, ema=99.5),
            bar(1, 101, 101.5, 100.2, 100.6, ema=100.3),  # red, but above the EMA
            bar(2, 100.6, 101, 100.2, 100.8, ema=100.9),  # below the EMA, but green
        ]
    )
    [trade] = result.trades
    assert trade.exit_reason == "END_OF_DATA"


def test_trailing_short_exits_on_a_green_candle_closing_above_the_ema() -> None:
    result = run(
        [
            bar(0, 101, 101.5, 99.5, 100, SELL, stop=102, target=None, ema=100.5),
            bar(1, 100, 100.2, 98, 98.5, ema=99.5),
            bar(2, 98.5, 99.6, 98.2, 99.4, ema=99.2),  # green, close above the EMA
        ]
    )
    [trade] = result.trades
    assert (trade.exit_reason, trade.exit_price) == ("EMA_TRAIL_EXIT", 99.4)


def test_trailing_trade_still_stops_out() -> None:
    result = run(
        [
            bar(0, 99, 100.5, 98.5, 100, BUY, target=None, ema=99.5),
            bar(1, 100, 100.2, 97, 97.5, ema=99.0),  # red below EMA, but the stop comes first
        ]
    )
    [trade] = result.trades
    assert (trade.exit_reason, trade.exit_price) == ("STOP_LOSS", 98)


def test_targets_are_never_hit_without_a_target() -> None:
    result = run(
        [
            bar(0, 99, 100.5, 98.5, 100, BUY, target=None, ema=99.5),
            bar(1, 100, 500, 99.5, 499, ema=200),
        ]
    )
    assert result.trades[0].exit_reason == "END_OF_DATA"


def test_fifteen_minute_bars_time_exits_by_the_bar_length() -> None:
    result = run([bar(0, 99, 100.5, 98.5, 100, BUY), bar(1, 100, 105, 99.5, 104.5)], minutes=15)
    [trade] = result.trades
    assert trade.entry_time == time(0) + timedelta(minutes=15)
    assert trade.exit_time == time(1) + timedelta(minutes=15)
    assert result.assumptions["bar_minutes"] == 15
