"""Execution rules checked on every trade of a strategy run over synthetic random-walk sessions.

The candles are labelled synthetic test data. These tests exercise the full strategy and engine
together across many sessions, complementing the hand-built cases in test_engine.py.
"""

from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache

import polars as pl
import pytest

from app.backtesting.engine import BAR, BacktestEngine, BacktestResult
from app.backtesting.settings import ExecutionSettings, RiskSettings
from app.data.ingestion.normalize import to_frame
from app.domain.candle import EXCHANGE_TZ
from app.domain.enums import ExecutionMethod, Side
from app.strategy.parameters import StrategyOptions, StrategyParameters
from app.strategy.runner import iter_evaluations
from tests.support.mock_market_data import RandomWalkProvider

START, END = date(2025, 1, 1), date(2025, 3, 31)
SETTINGS = {
    "next_open": (ExecutionSettings(method=ExecutionMethod.NEXT_OPEN), RiskSettings()),
    "signal_close": (ExecutionSettings(method=ExecutionMethod.SIGNAL_CLOSE), RiskSettings()),
    "slippage_and_limits": (
        ExecutionSettings(method=ExecutionMethod.NEXT_OPEN, slippage_points=0.5),
        RiskSettings(max_trades_per_day=2, max_daily_loss_points=40),
    ),
    "pivot_boss": (ExecutionSettings(method=ExecutionMethod.NEXT_OPEN), RiskSettings()),
}
PARAMETERS = {
    "pivot_boss": StrategyOptions(strategy="pivot_boss").apply(StrategyParameters()),
}


@lru_cache(maxsize=1)
def candles() -> tuple[pl.DataFrame, pl.DataFrame]:
    provider = RandomWalkProvider()
    instrument = provider.resolve_instrument("NIFTY50")
    intraday = to_frame(
        provider.get_historical_candles(instrument, "5m", START - timedelta(days=10), END).candles
    )
    daily = to_frame(
        provider.get_daily_candles(instrument, START - timedelta(days=60), END).candles
    )
    return intraday, daily


def run(name: str, end: date = END) -> BacktestResult:
    intraday, daily = candles()
    execution, risk = SETTINGS[name]
    return BacktestEngine(execution, risk).run(
        iter_evaluations(
            intraday.filter(pl.col("trading_date") <= end), daily, PARAMETERS.get(name)
        ),
        trade_from=START,
    )


@pytest.fixture(scope="module", params=list(SETTINGS))
def result(request: pytest.FixtureRequest) -> tuple[str, BacktestResult]:
    return request.param, run(request.param)


def test_the_run_produces_enough_trades_to_be_meaningful(result) -> None:
    _, outcome = result
    assert len(outcome.trades) >= 10


def test_every_candle_has_one_record(result) -> None:
    _, outcome = result
    times = [r.decision.timestamp for r in outcome.records]
    assert times == sorted(times)
    assert len(times) == len(set(times))


def test_no_position_is_held_overnight(result) -> None:
    _, outcome = result
    for trade in outcome.trades:
        entry_day = trade.entry_time.astimezone(EXCHANGE_TZ).date()
        exit_day = (trade.exit_time - timedelta(seconds=1)).astimezone(EXCHANGE_TZ).date()
        assert entry_day == exit_day == trade.trading_date


def test_positions_never_overlap(result) -> None:
    _, outcome = result
    for earlier, later in zip(outcome.trades, outcome.trades[1:], strict=False):
        assert later.entry_time >= earlier.exit_time


def test_opened_flags_match_trades(result) -> None:
    _, outcome = result
    assert sum(r.trade_opened for r in outcome.records) == len(outcome.trades)
    assert sum(r.position_closed for r in outcome.records) == len(outcome.trades)


def test_fills_follow_the_documented_rules(result) -> None:
    name, outcome = result
    slippage = SETTINGS[name][0].slippage_points
    bars = {r.decision.timestamp: r.decision for r in outcome.records}
    for t in outcome.trades:
        long = t.side == Side.LONG
        worse = -slippage if long else slippage
        gap = t.exit_reason.endswith("_GAP")
        bar = bars[t.exit_time if gap else t.exit_time - BAR]
        if t.exit_reason == "TARGET":
            assert t.exit_price == t.target
        elif t.exit_reason in ("STOP_LOSS", "TRAILING_STOP"):
            # A trailing stop records the level it had moved to.
            assert t.exit_price == pytest.approx(t.stop_loss + worse)
        elif t.exit_reason == "STOP_LOSS_GAP":
            assert t.exit_price == pytest.approx(bar.open + worse)
        elif t.exit_reason == "TARGET_GAP":
            assert t.exit_price == bar.open
        elif t.exit_reason in (
            "EOD_SQUARE_OFF",
            "SESSION_END_MISSING_DATA",
            "END_OF_DATA",
            "EMA_TRAIL_EXIT",
        ):
            assert t.exit_price == pytest.approx(bar.close + worse)
        # Before slippage, every fill lies within its candle's range.
        level = (
            t.exit_price - worse if t.exit_reason not in ("TARGET", "TARGET_GAP") else t.exit_price
        )
        assert bar.low - 1e-9 <= level <= bar.high + 1e-9


def test_stops_and_targets_are_on_the_correct_side(result) -> None:
    _, outcome = result
    for t in outcome.trades:
        # Trending-CPR trades have no target and exit on the EMA trail instead.
        if t.target is None:
            assert "EXIT_EMA_TRAIL" in t.entry_reasons
            assert t.exit_reason != "TARGET"
            continue
        if t.side == Side.LONG:
            assert t.stop_loss < t.target
        else:
            assert t.stop_loss > t.target


def test_entries_follow_a_signal_on_an_earlier_candle(result) -> None:
    name, outcome = result
    method = SETTINGS[name][0].method
    decisions = {r.decision.timestamp: r.decision for r in outcome.records}
    slippage = SETTINGS[name][0].slippage_points
    for t in outcome.trades:
        signal = decisions[t.entry_time - BAR]
        assert signal.action == ("BUY" if t.side == Side.LONG else "SELL")
        worse = slippage if t.side == Side.LONG else -slippage
        if method == ExecutionMethod.SIGNAL_CLOSE:
            assert t.entry_price == pytest.approx(signal.close + worse)
        else:
            assert t.entry_price == pytest.approx(decisions[t.entry_time].open + worse)


def test_daily_limits_are_respected() -> None:
    outcome = run("slippage_and_limits")
    per_day: dict[date, list[float]] = defaultdict(list)
    for t in outcome.trades:
        per_day[t.trading_date].append(t.net_points)
    for results in per_day.values():
        assert len(results) <= 2
        # Each trade started while the day's realised loss was still within the limit.
        for i in range(len(results)):
            assert sum(results[:i]) > -40


def test_later_candles_never_change_earlier_trades() -> None:
    full = run("next_open")
    cut = date(2025, 2, 14)
    partial = run("next_open", end=cut)
    closed_before = [t for t in full.trades if t.trading_date < cut]
    assert [t for t in partial.trades if t.trading_date < cut] == closed_before
    assert closed_before


def test_reruns_are_identical() -> None:
    assert run("next_open").result_hash() == run("next_open").result_hash()
